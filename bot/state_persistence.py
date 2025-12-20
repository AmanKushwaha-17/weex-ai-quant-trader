import json
import os
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

STATE_FILE = "logs/state.json"

# ======================
# PERSISTENCE FUNCTIONS
# ======================

def save_state(state, portfolio):
    """Save current state to JSON file"""
    try:
        # Convert date objects to strings for JSON serialization
        state_to_save = {}
        for symbol, data in state.items():

            open_trades_serializable = []
            for trade in data["open_trades"]:
                trade_copy = trade.copy()
                trade_copy["entry_time"] = trade["entry_time"].isoformat()
                trade_copy["target_exit_time"] = trade["target_exit_time"].isoformat()
                open_trades_serializable.append(trade_copy)

            state_to_save[symbol] = {
                "equity": data["equity"],
                "day_start_equity": data["day_start_equity"],
                "daily_pnl": data["daily_pnl"],
                "current_day": data["current_day"].isoformat(),
                "trading_enabled": data["trading_enabled"],
                "open_trades": open_trades_serializable,  # ✅ Now serializable
                "last_candle_time": data["last_candle_time"].isoformat() if data["last_candle_time"] else None,
            }
        
        portfolio_to_save = {
            "equity": portfolio["equity"],
            "day_start_equity": portfolio["day_start_equity"],
            "daily_pnl": portfolio["daily_pnl"],
            "trading_enabled": portfolio["trading_enabled"],
            "current_day": portfolio["current_day"].isoformat(),  # date -> string
        }
        
        data = {
            "state": state_to_save,
            "portfolio": portfolio_to_save,
            "saved_at": datetime.utcnow().isoformat()
        }
        
        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)
        
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.debug(f"State saved to {STATE_FILE}")
        
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def load_state():
    """Load previous state from JSON file"""
    if not os.path.exists(STATE_FILE):
        logger.info(f"No previous state found at {STATE_FILE}")
        return None
    
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        
        # Convert string dates back to date objects
        state = {}
        for symbol, symbol_data in data["state"].items():
            # Convert open_trades strings back to datetime objects
            open_trades_deserialized = []
            for trade in symbol_data["open_trades"]:
                trade_copy = trade.copy()
                trade_copy["entry_time"] = datetime.fromisoformat(trade["entry_time"])
                trade_copy["target_exit_time"] = datetime.fromisoformat(trade["target_exit_time"])
                open_trades_deserialized.append(trade_copy)

            state[symbol] = {
                "equity": symbol_data["equity"],
                "day_start_equity": symbol_data["day_start_equity"],
                "daily_pnl": symbol_data["daily_pnl"],
                "current_day": date.fromisoformat(symbol_data["current_day"]),
                "trading_enabled": symbol_data["trading_enabled"],
                "open_trades": open_trades_deserialized,  # ✅ Now datetime objects
                "last_candle_time": datetime.fromisoformat(symbol_data["last_candle_time"]) if symbol_data["last_candle_time"] else None,
            }
                    
        portfolio = {
            "equity": data["portfolio"]["equity"],
            "day_start_equity": data["portfolio"]["day_start_equity"],
            "daily_pnl": data["portfolio"]["daily_pnl"],
            "trading_enabled": data["portfolio"]["trading_enabled"],
            "current_day": date.fromisoformat(data["portfolio"]["current_day"]),  # string -> date
        }
        
        logger.info(f"Loaded previous state from {STATE_FILE} (saved at {data['saved_at']})")
        return {"state": state, "portfolio": portfolio}
        
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        return None


def initialize_state(symbols, initial_capital):
    """Initialize fresh state for all symbols"""
    state = {}
    for symbol in symbols:
        state[symbol] = {
            "equity": initial_capital,
            "day_start_equity": initial_capital,
            "daily_pnl": 0.0,
            "current_day": date.today(),
            "trading_enabled": True,
            "open_trades": [],
            "last_candle_time": None,
        }
    
    portfolio = {
        "equity": initial_capital * len(symbols),
        "day_start_equity": initial_capital * len(symbols),
        "daily_pnl": 0.0,
        "trading_enabled": True,
        "current_day": date.today(),
    }
    
    logger.info("Initialized fresh state")
    return state, portfolio


def setup_state(symbols, initial_capital):
    """
    Load previous state or create fresh state
    
    NEW LOGIC:
    1. Try to load previous state
    2. If file exists -> always load equity (even if old)
    3. If different day -> reset daily PnL, but KEEP equity
    4. If no file -> start fresh with initial capital
    """
    saved_data = load_state()
    
    if saved_data:
        today = date.today()
        saved_day = saved_data["portfolio"]["current_day"]
        
        if today == saved_day:
            # Same day - resume session exactly as is
            logger.info(f"✅ Resuming trading session for {today}")
            logger.info(f"Portfolio equity: ${saved_data['portfolio']['equity']:.2f}")
            return saved_data["state"], saved_data["portfolio"]
        else:
            # Different day - KEEP EQUITY, reset daily metrics
            days_diff = (today - saved_day).days
            logger.info(f"📅 Bot was offline for {days_diff} day(s)")
            logger.info(f"New trading day: {today}")
            logger.info(f"Continuing with equity: ${saved_data['portfolio']['equity']:.2f}")
            
            # Reset daily metrics but preserve equity
            for symbol in saved_data["state"]:
                saved_data["state"][symbol]["daily_pnl"] = 0.0
                saved_data["state"][symbol]["day_start_equity"] = saved_data["state"][symbol]["equity"]
                saved_data["state"][symbol]["current_day"] = today
                saved_data["state"][symbol]["trading_enabled"] = True
                # Keep: equity, open_trades
            
            saved_data["portfolio"]["daily_pnl"] = 0.0
            saved_data["portfolio"]["day_start_equity"] = saved_data["portfolio"]["equity"]
            saved_data["portfolio"]["current_day"] = today
            saved_data["portfolio"]["trading_enabled"] = True
            
            return saved_data["state"], saved_data["portfolio"]
    else:
        # No previous state - first time running
        logger.info("🆕 No previous state found, starting fresh")
        logger.info(f"Initial capital: ${initial_capital * len(symbols):.2f}")
        return initialize_state(symbols, initial_capital)