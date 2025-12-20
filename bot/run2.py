import time
import math
import logging
from datetime import datetime, date, timedelta

import pandas as pd

from bot.client import WeexClient
from bot.market import MarketData
from bot.inference import InferenceEngine
from research.features_builder import build_features
from bot.state_persistence import setup_state, save_state


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

    state, portfolio = setup_state(SYMBOLS, INITIAL_CAPITAL)

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

                # 🔍 DEBUG: Check what interval we're actually getting
                time_diff = candles.iloc[-1]["open_time"] - candles.iloc[-2]["open_time"]
                logger.info(f"[DEBUG] {symbol} Candle interval: {time_diff.total_seconds()/60:.0f} minutes")
                logger.info(f"[DEBUG] Inference horizon: {inference.horizon} candles")

                closed_candle = candles.iloc[-2]
                candle_time = closed_candle["open_time"]

                if candle_time == state[symbol]["last_candle_time"]:
                    logger.info(f"[{symbol}] Skipping duplicate candle @ {candle_time}")
                    continue

                state[symbol]["last_candle_time"] = candle_time

                logger.info(f"[{symbol}] Candle closed @ {candle_time}")

                # ---- Daily reset (safety backup) ----
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
                    logger.info(f"[{symbol}] Max concurrent trades reached ({MAX_CONCURRENT_TRADES})")
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

                        entry_time = datetime.utcnow()
                        target_exit_time = entry_time + timedelta(hours=1)

                        state[symbol]["open_trades"].append({
                            "direction": signal["direction"],
                            "entry_price": last_price,
                            "size": size,
                            "entry_time": entry_time,
                            "target_exit_time": target_exit_time
                        })

                        logger.info(
                            f"[{symbol}] DRY-OPEN | "
                            f"{'LONG' if signal['direction']==1 else 'SHORT'} "
                            f"Entry={last_price:.2f} "
                            f"Size={size:.4f} "
                            f"Target_Exit={target_exit_time.strftime('%H:%M:%S')}"
                        )

                # ---- Manage open trades ----
                current_time = datetime.utcnow()
                for trade in state[symbol]["open_trades"][:]:
                    time_held = (current_time - trade["entry_time"]).total_seconds() / 60
                    
                    # Check if 1 hour has passed
                    if current_time < trade["target_exit_time"]:
                        logger.info(
                            f"[{symbol}] Position held for {time_held:.1f} min "
                            f"(target: {(trade['target_exit_time'] - trade['entry_time']).total_seconds()/60:.0f} min)"
                        )
                        continue  # Not yet 1 hour, skip this trade

                    exit_price = market.get_last_price(symbol)
                    if exit_price is None:
                        continue

                    log_ret = math.log(exit_price / trade["entry_price"]) * trade["direction"]
                    pnl = trade["size"] * trade["entry_price"] * (math.exp(log_ret) - 1)

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
                        f"Entry={trade['entry_price']:.2f} "
                        f"Exit={exit_price:.2f} "
                        f"Held={time_held:.1f}min "
                        f"PnL={pnl:.2f} "
                        f"Equity={state[symbol]['equity']:.2f}"
                    )

                    state[symbol]["open_trades"].remove(trade)

            # ✅ Save state after processing all symbols
            save_state(state, portfolio)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            save_state(state, portfolio)
            break
        except Exception:
            logger.exception("Main loop error")
            save_state(state, portfolio)
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