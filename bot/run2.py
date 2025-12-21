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
    "cmt_ethusdt": {
        "asset_id": 0,
        "step_size": 0.0001,   # Adjust based on your exchange
        "min_size": 0.01,      # Adjust based on your exchange
    },
}

DRY_RUN = True
KILL_SWITCH = False

RISK_PER_TRADE = 0.06
SYMBOL_DRAWDOWN_LIMIT = -0.20
PORTFOLIO_DRAWDOWN_LIMIT = -0.30
MAX_CONCURRENT_TRADES = 4

LEVERAGE = 5
MAX_NOTIONAL_PCT = 0.75
MAX_MARGIN_PER_TRADE = 0.15  # 15% max margin per trade

INITIAL_CAPITAL = 500.0


# ======================
# LOGGING
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("logs/run2.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# ======================
# HELPER FUNCTIONS
# ======================

def round_to_step_size(size, step_size):
    """Round size down to nearest step_size increment"""
    if step_size == 0:
        return size
    return math.floor(size / step_size) * step_size


def seconds_until_next_candle(tf):
    now = datetime.utcnow()
    minutes = int(tf.replace("m", ""))
    current = now.replace(second=0, microsecond=0)
    next_close = (
        current
        - timedelta(minutes=current.minute % minutes)
        + timedelta(minutes=minutes, seconds=2)
    )
    return max(1, int((next_close - now).total_seconds()))


# ======================
# STATISTICS
# ======================

def calculate_statistics(trades_df, portfolio, state):
    """Calculate comprehensive trading statistics"""
    stats = {
        "timestamp": datetime.utcnow(),
        "total_trades": len(trades_df),
        "open_positions": sum(len(s["open_trades"]) for s in state.values()),
        "portfolio_equity": portfolio["equity"],
        "portfolio_margin_used": portfolio["margin_used"],
        "portfolio_available_margin": portfolio["available_margin"],
    }
    
    if len(trades_df) > 0:
        stats["total_pnl"] = trades_df["pnl"].sum()
        stats["winning_trades"] = (trades_df["pnl"] > 0).sum()
        stats["losing_trades"] = (trades_df["pnl"] < 0).sum()
        stats["win_rate"] = stats["winning_trades"] / len(trades_df) * 100
        stats["avg_pnl"] = trades_df["pnl"].mean()
        stats["profit_factor"] = abs(trades_df[trades_df["pnl"] > 0]["pnl"].sum() / 
                                     trades_df[trades_df["pnl"] < 0]["pnl"].sum()) if stats["losing_trades"] > 0 else float('inf')
        stats["avg_roi_on_margin"] = (trades_df["pnl"] / trades_df["margin_used"] * 100).mean()
        
        for symbol in SYMBOLS.keys():
            symbol_trades = trades_df[trades_df["symbol"] == symbol]
            if len(symbol_trades) > 0:
                stats[f"{symbol}_trades"] = len(symbol_trades)
                stats[f"{symbol}_pnl"] = symbol_trades["pnl"].sum()
                stats[f"{symbol}_win_rate"] = (symbol_trades["pnl"] > 0).sum() / len(symbol_trades) * 100
    
    return stats


def save_logs(trades_df, equity_df, open_positions_df, closed_positions_df, 
              statistics_df, drawdown_df):
    """Save all log files"""
    try:
        trades_df.to_csv("logs/trades.csv", index=False)
        equity_df.to_csv("logs/equity.csv", index=False)
        open_positions_df.to_csv("logs/open_positions.csv", index=False)
        closed_positions_df.to_csv("logs/closed_positions.csv", index=False)
        statistics_df.to_csv("logs/statistics.csv", index=False)
        drawdown_df.to_csv("logs/drawdown.csv", index=False)
        logger.info("✅ All logs saved")
    except Exception as e:
        logger.error(f"Error saving logs: {e}")


# ======================
# MAIN
# ======================

def main():
    logger.info(f"Starting run2.py | DRY={DRY_RUN} | LEVERAGE={LEVERAGE}x")

    if KILL_SWITCH:
        logger.warning("Kill switch active — exiting")
        return

    client = WeexClient()
    market = MarketData(client)
    inference = InferenceEngine("research/global_trading_model.bundle")

    state, portfolio = setup_state(SYMBOLS, INITIAL_CAPITAL)

    # Initialize margin tracking
    for symbol in SYMBOLS:
        state[symbol]["margin_used"] = 0.0
        state[symbol]["available_margin"] = state[symbol]["equity"]

    portfolio["margin_used"] = 0.0
    portfolio["available_margin"] = portfolio["equity"]
    portfolio["peak_equity"] = portfolio["equity"]

    # Initialize DataFrames with columns
    trades_df = pd.DataFrame(columns=[
        "timestamp", "symbol", "direction", "entry_price", "exit_price",
        "size", "margin_used", "leverage", "pnl"
    ])
    
    equity_df = pd.DataFrame(columns=[
        "timestamp", "symbol", "equity", "margin_used", "available_margin"
    ])
    
    open_positions_df = pd.DataFrame(columns=[
        "timestamp", "symbol", "num_positions", "total_size", 
        "total_margin_used", "avg_time_held_min", 
        "total_unrealized_pnl", "total_unrealized_roi_pct"
    ])
    
    closed_positions_df = pd.DataFrame(columns=[
        "close_timestamp", "symbol", "direction", "entry_price", "exit_price",
        "entry_time", "exit_time", "duration_min", "size", "margin_used",
        "leverage", "pnl", "roi_on_margin_pct", "equity_after"
    ])
    
    statistics_df = pd.DataFrame()
    
    drawdown_df = pd.DataFrame(columns=[
        "timestamp", "equity", "peak_equity", "drawdown_pct", "drawdown_amount"
    ])

    while True:
        try:
            time.sleep(seconds_until_next_candle(TIMEFRAME))

            total_open_trades = sum(len(s["open_trades"]) for s in state.values())

            for symbol, meta in SYMBOLS.items():
                candles = market.get_candles(symbol, TIMEFRAME, LOOKBACK)
                if candles is None or len(candles) < 50:
                    continue

                closed_candle = candles.iloc[-2]
                if closed_candle["open_time"] == state[symbol]["last_candle_time"]:
                    continue

                state[symbol]["last_candle_time"] = closed_candle["open_time"]

                # ---- Daily reset ----
                today = date.today()
                if today != state[symbol]["current_day"]:
                    state[symbol]["daily_pnl"] = 0.0
                    state[symbol]["day_start_equity"] = state[symbol]["equity"]
                    state[symbol]["trading_enabled"] = True
                    state[symbol]["current_day"] = today

                if today != portfolio["current_day"]:
                    portfolio["daily_pnl"] = 0.0
                    portfolio["day_start_equity"] = portfolio["equity"]
                    portfolio["trading_enabled"] = True
                    portfolio["current_day"] = today

                # ---- Drawdown checks ----
                if portfolio["daily_pnl"] <= PORTFOLIO_DRAWDOWN_LIMIT * portfolio["day_start_equity"]:
                    portfolio["trading_enabled"] = False
                    logger.warning("PORTFOLIO DD HIT")

                if state[symbol]["daily_pnl"] <= SYMBOL_DRAWDOWN_LIMIT * state[symbol]["day_start_equity"]:
                    state[symbol]["trading_enabled"] = False
                    logger.warning(f"[{symbol}] Symbol DD hit")

                # ---- Features & Signal ----
                features = build_features(candles)
                if features is None or features.empty:
                    continue

                features["asset_id"] = meta["asset_id"]
                signal = inference.infer(features, symbol)

                logger.info(
                    f"[{symbol}] ML | Dir={signal['direction']} "
                    f"Conf={signal['confidence']:.3f} Trade={signal['should_trade']}"
                )

                # ---- Entry Logic ----
                if (
                    signal["should_trade"]
                    and state[symbol]["trading_enabled"]
                    and portfolio["trading_enabled"]
                    and total_open_trades < MAX_CONCURRENT_TRADES
                ):
                    last_price = market.get_last_price(symbol)
                    atr = features.iloc[-1].get("atr_14")
                    
                    if last_price and atr and atr > 0:
                        # Step 1: Calculate "ideal" size based on ATR risk
                        risk_amt = state[symbol]["equity"] * RISK_PER_TRADE
                        size_by_risk = risk_amt / atr
                        
                        # Step 2: Calculate what margin that would require
                        notional_by_risk = size_by_risk * last_price
                        margin_by_risk = notional_by_risk / LEVERAGE
                        
                        # Step 3: Define your max margin per trade
                        max_margin_this_trade = portfolio["equity"] * MAX_MARGIN_PER_TRADE
                        
                        # Step 4: Scale down if needed
                        if margin_by_risk > max_margin_this_trade:
                            scaling_factor = max_margin_this_trade / margin_by_risk
                            size = size_by_risk * scaling_factor
                            
                            logger.debug(
                                f"[{symbol}] Size scaled down by {scaling_factor:.2%} "
                                f"(ATR suggested {size_by_risk:.6f}, using {size:.6f})"
                            )
                        else:
                            size = size_by_risk
                        
                        # Step 5: Round to exchange step size
                        step_size = meta.get("step_size", 0.00001)
                        min_size = meta.get("min_size", 0.001)
                        
                        size = round_to_step_size(size, step_size)
                        
                        # Check if size meets minimum requirements
                        if size < min_size:
                            logger.info(
                                f"[{symbol}] Size {size:.6f} below minimum {min_size:.6f}, skipping"
                            )
                            continue
                        
                        # Recalculate margin with rounded size
                        notional_value = size * last_price
                        margin_required = notional_value / LEVERAGE
                        
                        # Step 6: Check if we have enough margin available
                        portfolio_max_margin = portfolio["equity"] * MAX_NOTIONAL_PCT
                        
                        if (portfolio["margin_used"] + margin_required <= portfolio_max_margin and
                            margin_required <= state[symbol]["available_margin"]):
                            
                            entry_time = datetime.utcnow()

                            trade = {
                                "direction": signal["direction"],
                                "entry_price": last_price,
                                "size": size,
                                "margin_used": margin_required,
                                "entry_time": entry_time,
                                "target_exit_time": entry_time + timedelta(minutes=59),
                            }

                            state[symbol]["open_trades"].append(trade)
                            state[symbol]["margin_used"] += margin_required
                            state[symbol]["available_margin"] -= margin_required
                            portfolio["margin_used"] += margin_required
                            portfolio["available_margin"] -= margin_required
                            total_open_trades += 1

                            logger.info(
                                f"[{symbol}] OPEN | "
                                f"{'LONG' if signal['direction']==1 else 'SHORT'} "
                                f"Size={size:.6f} (step={step_size}) "
                                f"Margin=${margin_required:.2f} "
                                f"Notional=${notional_value:.2f} ATR=${atr:.2f} "
                                f"Portfolio: ${portfolio['margin_used']:.2f}/${portfolio_max_margin:.2f}"
                            )
                        else:
                            if margin_required > state[symbol]["available_margin"]:
                                logger.info(
                                    f"[{symbol}] Insufficient symbol margin "
                                    f"(need ${margin_required:.2f}, have ${state[symbol]['available_margin']:.2f})"
                                )
                            else:
                                logger.info(
                                    f"Portfolio margin cap hit "
                                    f"(would use ${portfolio['margin_used'] + margin_required:.2f}/"
                                    f"${portfolio_max_margin:.2f})"
                                )

                # ---- Log Open Positions (once per candle per symbol) ----
                now = datetime.utcnow()
                if len(state[symbol]["open_trades"]) > 0:
                    # Aggregate open positions for this symbol
                    total_size = sum(t["size"] for t in state[symbol]["open_trades"])
                    # Get current price for calculating margin
                    current_price_for_margin = market.get_last_price(symbol)
                    if not current_price_for_margin:
                        current_price_for_margin = state[symbol]["open_trades"][0]["entry_price"]
                    
                    # Backward compatibility: handle old trades without margin_used
                    total_margin = sum(
                        t.get("margin_used", (t["size"] * current_price_for_margin) / LEVERAGE) 
                        for t in state[symbol]["open_trades"]
                    )
                    
                    # Calculate aggregate unrealized PnL
                    current_price = market.get_last_price(symbol)
                    if current_price:
                        total_unrealized_pnl = 0
                        for trade in state[symbol]["open_trades"]:
                            log_ret = math.log(current_price / trade["entry_price"]) * trade["direction"]
                            total_unrealized_pnl += trade["size"] * trade["entry_price"] * (math.exp(log_ret) - 1)
                        
                        avg_time_held = sum((now - t["entry_time"]).total_seconds() / 60 for t in state[symbol]["open_trades"]) / len(state[symbol]["open_trades"])
                        total_unrealized_roi = (total_unrealized_pnl / total_margin) * 100 if total_margin > 0 else 0
                        
                        open_positions_df.loc[len(open_positions_df)] = [
                            now, symbol, len(state[symbol]["open_trades"]), total_size,
                            total_margin, avg_time_held, total_unrealized_pnl, total_unrealized_roi
                        ]

                # ---- Exit Logic ----
                for trade in state[symbol]["open_trades"][:]:
                    # Ensure trade has margin_used field (backward compatibility)
                    if "margin_used" not in trade:
                        trade["margin_used"] = (trade["size"] * trade["entry_price"]) / LEVERAGE
                        logger.warning(f"[{symbol}] Added missing margin_used to old trade")
                    
                    if now < trade["target_exit_time"]:
                        continue

                    exit_price = market.get_last_price(symbol)
                    if not exit_price:
                        continue

                    exit_time = datetime.utcnow()
                    log_ret = math.log(exit_price / trade["entry_price"]) * trade["direction"]
                    pnl = trade["size"] * trade["entry_price"] * (math.exp(log_ret) - 1)

                    # Update equity
                    state[symbol]["equity"] += pnl
                    state[symbol]["daily_pnl"] += pnl
                    portfolio["equity"] += pnl
                    portfolio["daily_pnl"] += pnl
                    portfolio["peak_equity"] = max(portfolio["peak_equity"], portfolio["equity"])

                    # Release margin
                    margin_to_release = trade["margin_used"]
                    state[symbol]["margin_used"] -= margin_to_release
                    state[symbol]["available_margin"] += margin_to_release
                    portfolio["margin_used"] -= margin_to_release
                    portfolio["available_margin"] += margin_to_release

                    roi_on_margin = (pnl / margin_to_release) * 100
                    duration_min = (exit_time - trade["entry_time"]).total_seconds() / 60

                    # Log to trades_df
                    trades_df.loc[len(trades_df)] = [
                        exit_time, symbol, trade["direction"],
                        trade["entry_price"], exit_price,
                        trade["size"], margin_to_release, LEVERAGE, pnl
                    ]

                    # Log to closed_positions_df
                    closed_positions_df.loc[len(closed_positions_df)] = [
                        exit_time, symbol, trade["direction"],
                        trade["entry_price"], exit_price,
                        trade["entry_time"], exit_time, duration_min,
                        trade["size"], margin_to_release, LEVERAGE,
                        pnl, roi_on_margin, state[symbol]["equity"]
                    ]

                    logger.info(
                        f"[{symbol}] CLOSE | Entry={trade['entry_price']:.2f} "
                        f"Exit={exit_price:.2f} Duration={duration_min:.1f}min "
                        f"PnL={pnl:.2f} ROI={roi_on_margin:.2f}% "
                        f"Equity={state[symbol]['equity']:.2f}"
                    )

                    state[symbol]["open_trades"].remove(trade)
                    total_open_trades -= 1

                # Equity snapshot every candle
                equity_df.loc[len(equity_df)] = [
                    now, symbol, state[symbol]["equity"],
                    state[symbol]["margin_used"],
                    state[symbol]["available_margin"]
                ]

                # Drawdown tracking
                drawdown_pct = (portfolio["equity"] - portfolio["peak_equity"]) / portfolio["peak_equity"] * 100
                drawdown_df.loc[len(drawdown_df)] = [
                    now, portfolio["equity"], portfolio["peak_equity"],
                    drawdown_pct, portfolio["equity"] - portfolio["peak_equity"]
                ]

            # Calculate statistics only when trades close
            if len(trades_df) > 0 and len(trades_df) != len(statistics_df):
                stats = calculate_statistics(trades_df, portfolio, state)
                statistics_df = pd.concat([statistics_df, pd.DataFrame([stats])], ignore_index=True)

            # Periodic saves
            if len(trades_df) % 10 == 0 and len(trades_df) > 0:
                save_logs(trades_df, equity_df, open_positions_df,
                         closed_positions_df, statistics_df, drawdown_df)

            save_state(state, portfolio)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            save_state(state, portfolio)
            save_logs(trades_df, equity_df, open_positions_df,
                     closed_positions_df, statistics_df, drawdown_df)
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
    logger.info(f"Portfolio equity: {portfolio['equity']:.2f}")
    logger.info(f"Peak equity: {portfolio['peak_equity']:.2f}")

    if len(trades_df) > 0:
        stats = calculate_statistics(trades_df, portfolio, state)
        logger.info(f"Win Rate: {stats['win_rate']:.2f}%")
        logger.info(f"Profit Factor: {stats['profit_factor']:.2f}")
        logger.info(f"Avg ROI: {stats['avg_roi_on_margin']:.2f}%")

        save_logs(trades_df, equity_df, open_positions_df,
                 closed_positions_df, statistics_df, drawdown_df)


if __name__ == "__main__":
    main()