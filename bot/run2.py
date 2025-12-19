import time
import math
import logging
from datetime import datetime, date, timedelta

import pandas as pd

from bot.client import WeexClient
from bot.market import MarketData
from bot.inference import InferenceEngine
from research.features_builder import build_features


# ======================
# CONFIGURATION
# ======================

TIMEFRAME = "15m"
LOOKBACK = 300

SYMBOLS = {
    "cmt_btcusdt": {"asset_id": 1},
    "cmt_ethusdt": {"asset_id": 0},
}


DRY_RUN = True
KILL_SWITCH = False

# ===== Risk Controls =====
RISK_PER_TRADE = 0.06
SYMBOL_DRAWDOWN_LIMIT = -0.05
PORTFOLIO_DRAWDOWN_LIMIT = -0.10
MAX_CONCURRENT_TRADES = 3

# 🆕 Conservative exposure cap
MAX_NOTIONAL_PCT = 0.25

INITIAL_CAPITAL = 100.0


# ======================
# LOGGING
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/run2.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ======================
# TIMING HELPERS
# ======================

def seconds_until_next_candle(timeframe: str) -> int:
    now = datetime.utcnow()

    if not timeframe.endswith("m"):
        raise ValueError("Only minute timeframes supported")

    minutes = int(timeframe.replace("m", ""))

    # floor to current candle
    current = now.replace(second=0, microsecond=0)
    delta = timedelta(minutes=minutes)
    next_close = (current - timedelta(
        minutes=current.minute % minutes
    )) + delta + timedelta(seconds=2)

    return max(1, int((next_close - now).total_seconds()))


# ======================
# MAIN
# ======================

def main():
    logger.info("Starting run2.py — MULTI-SYMBOL | PORTFOLIO RISK | DRY-RUN")

    if KILL_SWITCH:
        logger.warning("Kill switch active — exiting")
        return

    client = WeexClient()
    market = MarketData(client)
    inference = InferenceEngine(
        model_bundle_path="research/global_trading_model.bundle"
    )

    # ======================
    # STATE
    # ======================

    state = {}
    for symbol in SYMBOLS:
        state[symbol] = {
            "equity": INITIAL_CAPITAL,
            "day_start_equity": INITIAL_CAPITAL,
            "daily_pnl": 0.0,
            "current_day": date.today(),
            "trading_enabled": True,
            "open_trades": [],
            "last_candle_time": None,
        }

    portfolio = {
        "equity": INITIAL_CAPITAL * len(SYMBOLS),
        "day_start_equity": INITIAL_CAPITAL * len(SYMBOLS),
        "daily_pnl": 0.0,
        "trading_enabled": True,
        "current_day": date.today(),
    }

    # ======================
    # DATA STORAGE
    # ======================

    trades_df = pd.DataFrame(columns=[
        "timestamp", "symbol", "direction",
        "entry_price", "exit_price",
        "size", "pnl"
    ])

    equity_df = pd.DataFrame(columns=[
        "timestamp", "symbol", "equity"
    ])

    # ======================
    # MAIN LOOP
    # ======================

    while True:
        try:
            sleep_seconds = seconds_until_next_candle(TIMEFRAME)
            logger.info(f"Sleeping {sleep_seconds}s until next candle close")
            time.sleep(sleep_seconds)

            for symbol, meta in SYMBOLS.items():

                # ---- Fetch candles ONCE per close ----
                candles = market.get_candles(symbol, TIMEFRAME, limit=LOOKBACK)
                if candles is None or len(candles) < 50:
                    logger.warning(f"[{symbol}] Not enough candle data")
                    continue

                closed_candle = candles.iloc[-2]
                candle_time = closed_candle["open_time"]

                if candle_time == state[symbol]["last_candle_time"]:
                    continue

                state[symbol]["last_candle_time"] = candle_time

                logger.info(
                    f"[{symbol}] Candle closed @ "
                    f"{candle_time}"

                )

                # ---- Daily reset ----
                today = date.today()
                if today != state[symbol]["current_day"]:
                    state[symbol]["daily_pnl"] = 0.0
                    state[symbol]["day_start_equity"] = state[symbol]["equity"]
                    state[symbol]["trading_enabled"] = True
                    state[symbol]["current_day"] = today
                    logger.info(f"[{symbol}] Daily reset")

                if today != portfolio["current_day"]:
                    portfolio["daily_pnl"] = 0.0
                    portfolio["day_start_equity"] = portfolio["equity"]
                    portfolio["trading_enabled"] = True
                    portfolio["current_day"] = today
                    logger.info("PORTFOLIO daily reset")

                # ---- Portfolio DD ----
                if portfolio["daily_pnl"] <= PORTFOLIO_DRAWDOWN_LIMIT * portfolio["day_start_equity"]:
                    portfolio["trading_enabled"] = False
                    logger.warning("PORTFOLIO DAILY DD HIT — TRADING STOPPED")

                # ---- Features ----
                features_df = build_features(candles)
                if features_df is None or len(features_df) == 0:
                    continue

                features_df["asset_id"] = meta["asset_id"]

                # ---- Inference ----
                signal = inference.infer(features_df, symbol)

                logger.info(
                    f"[{symbol}] ML | "
                    f"Dir={signal['direction']} "
                    f"Conf={signal['confidence']:.3f} "
                    f"Trade={signal['should_trade']}"
                )

                # ---- Symbol DD ----
                if state[symbol]["daily_pnl"] <= SYMBOL_DRAWDOWN_LIMIT * state[symbol]["day_start_equity"]:
                    state[symbol]["trading_enabled"] = False
                    logger.warning(f"[{symbol}] Symbol DD hit — trading disabled")

                # ---- Entry ----
                if not (
                    signal["should_trade"]
                    and state[symbol]["trading_enabled"]
                    and portfolio["trading_enabled"]
                ):
                    pass

                elif len(state[symbol]["open_trades"]) >= MAX_CONCURRENT_TRADES:
                    pass

                else:
                    last_price = market.get_last_price(symbol)
                    atr = features_df.iloc[-1].get("atr_14")

                    if last_price and atr and atr > 0:
                        risk_amount = state[symbol]["equity"] * RISK_PER_TRADE
                        atr_size = risk_amount / atr

                        max_notional = state[symbol]["equity"] * MAX_NOTIONAL_PCT
                        max_size = max_notional / last_price

                        size = min(atr_size, max_size)

                        state[symbol]["open_trades"].append({
                            "direction": signal["direction"],
                            "entry_price": last_price,
                            "size": size,
                            "bars_left": inference.horizon,
                        })

                        logger.info(
                            f"[{symbol}] DRY-OPEN | "
                            f"{'LONG' if signal['direction']==1 else 'SHORT'} "
                            f"Price={last_price:.2f} "
                            f"Size={size:.4f}"
                        )

                # ---- Manage open trades ----
                for trade in state[symbol]["open_trades"][:]:
                    trade["bars_left"] -= 1
                    if trade["bars_left"] > 0:
                        continue

                    exit_price = market.get_last_price(symbol)
                    if exit_price is None:
                        continue

                    log_ret = math.log(exit_price / trade["entry_price"]) * trade["direction"]
                    pnl = trade["size"] * (math.exp(log_ret) - 1)

                    state[symbol]["equity"] += pnl
                    state[symbol]["daily_pnl"] += pnl
                    portfolio["equity"] += pnl
                    portfolio["daily_pnl"] += pnl

                    trades_df.loc[len(trades_df)] = [
                        datetime.utcnow(), symbol, trade["direction"],
                        trade["entry_price"], exit_price,
                        trade["size"], pnl
                    ]

                    equity_df.loc[len(equity_df)] = [
                        datetime.utcnow(), symbol, state[symbol]["equity"]
                    ]

                    logger.info(
                        f"[{symbol}] DRY-CLOSE | "
                        f"PnL={pnl:.2f} Equity={state[symbol]['equity']:.2f}"
                    )

                    state[symbol]["open_trades"].remove(trade)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception:
            logger.exception("Main loop error")
            time.sleep(5)

    # ======================
    # FINAL SUMMARY
    # ======================

    logger.info("=" * 50)
    logger.info("RUN FINISHED")
    logger.info("=" * 50)
    logger.info(f"Total trades: {len(trades_df)}")
    logger.info(f"Final portfolio equity: {portfolio['equity']:.2f}")

    if len(trades_df) > 0:
        trades_df.to_csv("logs/trades.csv", index=False)
        equity_df.to_csv("logs/equity.csv", index=False)
        logger.info("Saved logs/trades.csv and logs/equity.csv")


if __name__ == "__main__":
    main()
