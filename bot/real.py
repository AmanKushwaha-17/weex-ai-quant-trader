import time
import math
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from bot.client import WeexClient
from bot.market import MarketData
from bot.orders import OrderManager
from bot.risk import RiskManager
from bot.inference import InferenceEngine
from research.features_builder import build_features
from decimal import Decimal, ROUND_DOWN

# ============================================================
# CONFIG
# ============================================================

TIMEFRAME = "15m"
LOOKBACK = 300
SYMBOL = "cmt_ethusdt"
ASSET_ID = 0

STEP_SIZE = 0.001
MIN_SIZE = 0.01

LEVERAGE = 5
RISK_PER_TRADE = 0.06
MAX_MARGIN_PCT = 0.75
MAX_MARGIN_PER_TRADE = 0.15   # 15% per trade


MAX_LONG_CONCURRENT_TRADES = 2
MAX_SHORT_CONCURRENT_TRADES = 2

LONG_STOP_ATR = 0.8
LONG_TARGET_ATR = 2.0
LONG_EARLY_FAIL_ATR = 0.15
LONG_EARLY_FAIL_MIN = 119
LONG_MAX_HOLD_MIN = 179

SHORT_STOP_ATR = 0.4
SHORT_TARGET_ATR = 1.8
SHORT_EARLY_FAIL_ATR = 0.35
SHORT_EARLY_FAIL_MIN = 44
SHORT_MAX_HOLD_MIN = 119

KILL_SWITCH = False

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "research" / "global_trading_model.bundle"


# Operational resilience
REJECT_COOLDOWN_SEC = 30

# ============================================================
# PATHS
# ============================================================

os.makedirs("logs", exist_ok=True)
UI_STATE_PATH = Path("ui_state/state.json")
TRADE_HISTORY_PATH = Path("ui_state/trade_history.json")
UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/real_portfolio.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# HELPERS
# ============================================================

def safe_call(fn, retries=3, delay=1.0, fail_value=None):
    """
    Engine-level retry wrapper.
    Retries logical/API failures, not just network failures.
    """
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            if i == retries - 1:
                logger.error(f"❌ Final failure in {fn.__name__}: {e}")
                return fail_value
            logger.warning(
                f"⚠️ {fn.__name__} failed (attempt {i+1}/{retries}): {e}"
            )
            time.sleep(delay)


def seconds_until_next_candle(tf: str) -> int:
    """
    Supports formats like '1m', '5m', '15m'.
    Falls back safely if malformed.
    """
    try:
        if not tf.endswith("m"):
            raise ValueError(f"Invalid timeframe format: {tf}")

        minutes = int(tf[:-1])
        if minutes <= 0:
            raise ValueError("Timeframe must be positive")

        now = datetime.utcnow()
        base = now.replace(second=0, microsecond=0)
        next_close = (
            base - timedelta(minutes=base.minute % minutes)
            + timedelta(minutes=minutes, seconds=1)
        )

        return max(1, int((next_close - now).total_seconds()))

    except Exception as e:
        logger.error(f"Invalid TIMEFRAME='{tf}', defaulting to 60s | {e}")
        return 60


def round_qty(qty):
    step = Decimal(str(STEP_SIZE))
    q = Decimal(str(qty))
    return float((q // step) * step)

def safe_json(resp):
    return json.loads(resp) if isinstance(resp, str) else resp

def extract_usdt_equity(balance_resp):
    """
    WEEX returns balance as a LIST, not a dict.
    Example:
    [
      {"coinName":"USDT","available":"995.63", ...}
    ]
    """
    data = safe_json(balance_resp)

    if not isinstance(data, list):
        logger.error(f"Unexpected balance format: {data}")
        return None

    for a in data:
        if a.get("coinName") == "USDT":
            return float(a.get("available", 0))

    return None


def fetch_positions(client):
    status, resp = client.get_positions()
    if status != 200:
        return []

    data = safe_json(resp)
    if not isinstance(data, list):
        return []

    return [p for p in data if p.get("symbol") == SYMBOL]




def compute_position_size(equity, atr, price):
    """
    Each trade uses at most MAX_MARGIN_PER_TRADE of equity.
    Risk is capped per trade, not globally.
    """
    # Max margin allowed for THIS trade
    max_margin = equity * MAX_MARGIN_PER_TRADE

    # Convert margin → max position size
    max_size_by_margin = (max_margin * LEVERAGE) / price

    # Risk-based size (ATR)
    risk_amt = equity * RISK_PER_TRADE
    size_by_risk = risk_amt / atr

    # Take the safer (smaller) size
    raw_size = min(size_by_risk, max_size_by_margin)

    size = round_qty(raw_size)
    if size < MIN_SIZE:
        return None, None

    margin = (size * price) / LEVERAGE
    return size, margin


# ============================================================
# ENTRY GENERATOR
# ============================================================

def generate_entry_signal(signal, f, candle, candles, long_count, short_count):
    """
    Returns:
        (direction, reason)
        direction: 1 | -1 | None
        reason: string
    """

    # ================= SHORT =================
    if signal["direction"] == -1:
        if short_count >= MAX_SHORT_CONCURRENT_TRADES:
            return None, "max short positions reached"

        if signal["confidence"] < 0.50:
            return None, "confidence below threshold"

        if candle["close"] >= candles.iloc[-3]["low"]:
            return None, "no bearish break"

        if f.get("rsi_14", 100) > 50:
            return None, "RSI too high for short"

        if f.get("vol_ratio", 0) < 0.7:
            return None, "low volume confirmation"

        return -1, "short conditions satisfied"

    # ================= LONG =================
    if signal["direction"] == 1:
        if long_count >= MAX_LONG_CONCURRENT_TRADES:
            return None, "max long positions reached"

        if signal["confidence"] < 0.50:
            return None, "confidence below threshold"

        if f["atr_pct"] > f["atr_pct_q75"]:
            return None, (
                f"atr_pct too high ({f['atr_pct']:.4f} > {f['atr_pct_q75']:.4f})"
            )

        if f["price_to_sma24"] > f["price_to_sma24_q75"]:
            return None, "price stretched above SMA"

        return 1, "long conditions satisfied"

    return None, "no valid direction"


def record_closed_trade(trade):
    history = []

    if TRADE_HISTORY_PATH.exists():
        history = json.loads(TRADE_HISTORY_PATH.read_text())

    history.append(trade)

    TRADE_HISTORY_PATH.write_text(
        json.dumps(history, indent=2, default=str)
    )




def build_ai_log(
    order_id,
    signal,
    features_row,
    direction,
    reason
):
    return {
        "orderId": order_id,
        "stage": "Decision Making",
        "model": "LightGBM-global-v1",
        "input": {
            "features": {
                "atr_14": float(features_row["atr_14"]),
                "atr_pct": float(features_row["atr_pct"]),
                "rsi_14": float(features_row.get("rsi_14", 0)),
                "price_to_sma24": float(features_row["price_to_sma24"]),
            },
            "signal_context": {
                "symbol": SYMBOL,
                "timeframe": TIMEFRAME
            }
        },
        "output": {
            "direction": "LONG" if direction == 1 else "SHORT",
            "confidence": float(signal["confidence"]),
            "should_trade": bool(signal["should_trade"])
        },
        "explanation": reason[:1000]  
    }


# ============================================================
# UI EXPORT
# ============================================================

def export_ui_state(state):
    tmp = UI_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(UI_STATE_PATH)

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    logger.info("===== LIVE PORTFOLIO ENGINE (HARDENED) =====")

    if KILL_SWITCH:
        logger.warning("KILL SWITCH ACTIVE")
        return

    client = WeexClient()
    market = MarketData(client)
    orders = OrderManager(client)
    risk = RiskManager(client)
    inference = InferenceEngine(str(MODEL_PATH))


    risk.set_leverage(symbol=SYMBOL, leverage=LEVERAGE)
    last_candle_time = None
    last_reject_time = 0

    while True:
        try:
            time.sleep(seconds_until_next_candle(TIMEFRAME))
            last_action = "HOLD"

            # ✅ Safe balance fetch
            balance_resp = safe_call(
                lambda: client.get_account_balance(),
                fail_value=(None, None)
            )

            if not balance_resp or balance_resp[0] != 200:
                continue

            equity = extract_usdt_equity(balance_resp[1])
            if equity is None or equity <= 0:
                continue

            # ✅ Safe positions fetch
            positions = safe_call(
                lambda: fetch_positions(client),
                fail_value=[]
            )

            # ✅ Safe price fetch
            price = safe_call(
                lambda: market.get_last_price(SYMBOL),
                fail_value=None
            )

            if price is None:
                continue

            # ✅ Safe candles fetch
            candles = safe_call(
                lambda: market.get_candles(SYMBOL, TIMEFRAME, LOOKBACK),
                fail_value=None
            )

            if candles is None or len(candles) < 50:
                continue

            closed = candles.iloc[-2]
            if closed["open_time"] == last_candle_time:
                continue
            last_candle_time = closed["open_time"]

            features = build_features(candles)
            features["asset_id"] = ASSET_ID
            features["atr_pct_q75"] = features["atr_pct"].rolling(50).quantile(0.75)
            features["price_to_sma24_q75"] = features["price_to_sma24"].rolling(24).quantile(0.75)

            f = features.iloc[-2]
            candle = candles.iloc[-2]
            atr = f["atr_14"]
            if atr is None or atr <= 0:
                continue

            now = datetime.utcnow()

            # ================= EXIT =================
            for p in positions:
                direction = 1 if p["side"] == "LONG" else -1
                entry = float(p["open_value"]) / float(p["size"])
                mins = (
                    now - datetime.fromtimestamp(p["created_time"] / 1000)
                ).total_seconds() / 60

                size = float(p["size"])

                move = (price - entry) * direction
                atr_move = move / atr

                exit_reason = None

                if direction == 1:
                    if atr_move <= -LONG_STOP_ATR:
                        exit_reason = "STOP"
                    elif atr_move >= LONG_TARGET_ATR:
                        exit_reason = "TARGET"
                    elif mins >= LONG_EARLY_FAIL_MIN and atr_move < LONG_EARLY_FAIL_ATR:
                        exit_reason = "EARLY_FAIL"
                    elif mins >= LONG_MAX_HOLD_MIN:
                        exit_reason = "TIMEOUT"
                else:
                    if atr_move <= -SHORT_STOP_ATR:
                        exit_reason = "STOP"
                    elif atr_move >= SHORT_TARGET_ATR:
                        exit_reason = "TARGET"
                    elif mins >= SHORT_EARLY_FAIL_MIN and atr_move < SHORT_EARLY_FAIL_ATR:
                        exit_reason = "EARLY_FAIL"
                    elif mins >= SHORT_MAX_HOLD_MIN:
                        exit_reason = "TIMEOUT"

                if exit_reason:
                    last_action = f"EXIT_{p['side']}_{exit_reason}"
                    logger.warning(f"[EXIT] {last_action} | size={size}")

                    # ✅ Safe exit execution
                    if direction == 1:
                        ok = safe_call(
                            lambda: orders.close_long(SYMBOL, size),
                            fail_value=False
                        )
                        if not ok:
                            logger.error("❌ EXIT LONG FAILED after retries")
                    else:
                        ok = safe_call(
                            lambda: orders.close_short(SYMBOL, size),
                            fail_value=False
                        )
                        if not ok:
                            logger.error("❌ EXIT SHORT FAILED after retries")


                    exit_price = price
                    entry_price = float(p["open_value"]) / float(p["size"])
                    direction = 1 if p["side"] == "LONG" else -1

                    pnl = (exit_price - entry_price) * float(p["size"]) * direction

                    closed_trade = {
                        "symbol": p["symbol"],
                        "side": p["side"],
                        "size": float(p["size"]),
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(exit_price, 4),
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason,
                        "opened_at": datetime.fromtimestamp(p["created_time"]/1000).isoformat(),
                        "closed_at": now.isoformat(),
                        "duration_min": round(mins, 2)
                    }

                    record_closed_trade(closed_trade)



            # ================= ENTRY =================
            signal = inference.infer(features, SYMBOL)

            if signal["should_trade"]:
                if time.time() - last_reject_time < REJECT_COOLDOWN_SEC:
                    logger.info("[ENTRY SKIPPED] cooldown after rejection")
                    continue

                long_count = sum(1 for p in positions if p["side"] == "LONG")
                short_count = sum(1 for p in positions if p["side"] == "SHORT")

                entry_dir, entry_reason = generate_entry_signal(
                    signal, f, candle, candles, long_count, short_count
                )

                if entry_dir is None:
                    logger.info(
                        f"[ENTRY BLOCKED] {entry_reason} | "
                        f"dir={signal['direction']} conf={signal['confidence']:.3f}"
                    )
                    continue

                qty, margin = compute_position_size(equity, atr, price)
                if not qty:
                    logger.info("[ENTRY BLOCKED] size < MIN_SIZE")
                    continue

                logger.warning(
                    f"[ENTRY] {'LONG' if entry_dir==1 else 'SHORT'} | "
                    f"qty={qty:.4f} | margin={margin:.2f} | reason={entry_reason}"
                )

                # ---- SINGLE execution ----
                if entry_dir == 1:
                    ok, order_id = safe_call(
                        lambda: orders.open_long(SYMBOL, qty),
                        fail_value=(False, None)
                    )
                else:
                    ok, order_id = safe_call(
                        lambda: orders.open_short(SYMBOL, qty),
                        fail_value=(False, None)
                    )

                if not ok:
                    logger.error("❌ ENTRY FAILED after retries")
                    last_reject_time = time.time()
                    continue

                # 🔄 Refresh positions after successful entry
                positions = safe_call(
                    lambda: fetch_positions(client),
                    fail_value=positions
                )

                last_action = f"ENTRY_{'LONG' if entry_dir == 1 else 'SHORT'}"


                # ---- AI LOG (competition mandatory) ----
                ai_log = build_ai_log(
                    order_id=order_id,
                    signal=signal,
                    features_row=f,
                    direction=entry_dir,
                    reason=entry_reason
                )

                safe_call(
                    lambda: client.upload_ai_log(ai_log),
                    retries=2,
                    delay=0.5
                )



            enriched_positions = []

            for p in positions:
                elapsed_min = (
                    now - datetime.fromtimestamp(p["created_time"] / 1000)
                ).total_seconds() / 60

                max_hold = LONG_MAX_HOLD_MIN if p["side"] == "LONG" else SHORT_MAX_HOLD_MIN
                early_fail = LONG_EARLY_FAIL_MIN if p["side"] == "LONG" else SHORT_EARLY_FAIL_MIN

                time_left = max(0, max_hold - elapsed_min)

                if elapsed_min < early_fail:
                    exit_phase = "NORMAL"
                elif elapsed_min < max_hold:
                    exit_phase = "EARLY_FAIL_WINDOW"
                else:
                    exit_phase = "FORCED_EXIT"

                enriched_positions.append({
                    # Identity
                    "symbol": p["symbol"],
                    "side": p["side"],

                    # Size & leverage
                    "size": float(p["size"]),
                    "leverage": float(p["leverage"]),
                    "margin": float(p["marginSize"]),

                    # Entry
                    "open_value": float(p["open_value"]),
                    "entry_price": (
                        float(p["open_value"]) / float(p["size"])
                        if float(p["size"]) > 0 else None
                    ),

                    # Fees
                    "open_fee": float(p["open_fee"]),
                    "funding_fee": float(p["funding_fee"]),
                    "cum_open_fee": float(p["cum_open_fee"]),
                    "cum_close_fee": float(p["cum_close_fee"]),
                    "cum_funding_fee": float(p["cum_funding_fee"]),

                    # PnL
                    "unrealized_pnl": float(p["unrealizePnl"]),
                    "liquidation_price": float(p["liquidatePrice"]),

                    # Time (RAW)
                    "created_time": p["created_time"],
                    "updated_time": p["updated_time"],

                    # 🆕 Time diagnostics (THIS IS WHAT YOU WANT)
                    "time_open_min": round(elapsed_min, 2),
                    "time_left_min": round(time_left, 2),
                    "exit_phase": exit_phase,
                })

            closed_trades = []
            if TRADE_HISTORY_PATH.exists():
                closed_trades = json.loads(TRADE_HISTORY_PATH.read_text())[-10:]



            export_ui_state({
                "timestamp": now.isoformat(),
                "symbol": SYMBOL,
                "equity": round(equity, 2),
                "price": round(price, 4),
                "signal": signal,

                "positions": enriched_positions,      # OPEN trades
                "closed_trades": closed_trades,        # CLOSED trades

                "last_action": last_action,
                "engine_status": "RUNNING",
            })



        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception:
            logger.exception("Engine error")
            time.sleep(5)

if __name__ == "__main__":
    main()