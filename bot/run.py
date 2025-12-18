import time
import logging
from bot.client import WeexClient
from bot.risk import RiskManager
from bot.market import MarketData
from bot.orders import OrderManager
import math


# ======================
# BOT CONFIGURATION
# ======================

TRADE_SYMBOL = "cmt_btcusdt"
NOTIONAL_USDT = 10
LEVERAGE = 2
ROUND_PRECISION = 6
DRY_RUN = True
KILL_SWITCH = False

# ======================
# LOGGING SETUP
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    logger.info("Bot starting")

    # ======================
    # Kill Switch
    # ======================
    if KILL_SWITCH:
        logger.warning("Kill switch active — exiting safely")
        return

    client = WeexClient()
    risk = RiskManager(client)
    market = MarketData(client)
    orders = OrderManager(client)

    # ======================
    # 1️⃣ Account Balance
    # ======================
    status, response = client.get_account_balance()
    if status == 200:
        logger.info("Account assets fetched successfully")
        logger.info(response)
    else:
        logger.error(f"Account balance API failed | Status: {status}")
        logger.error(response)
        return

    # ======================
    # 2️⃣ Set Leverage
    # ======================
    logger.info("Setting leverage")
    status, response = risk.set_leverage(
        symbol=TRADE_SYMBOL,
        leverage=LEVERAGE
    )

    if status == 200:
        logger.info("Leverage set successfully")
        logger.info(response)
    else:
        logger.warning("Failed to set leverage")
        logger.warning(f"Status: {status}")
        logger.warning(response)
        logger.warning("Proceeding with existing leverage")

    # ======================
    # 3️⃣ Fetch Ticker
    # ======================
    logger.info("Fetching price ticker")
    status, response = market.get_ticker(TRADE_SYMBOL)

    if status != 200 or response is None:
        logger.error("Failed to fetch ticker")
        return

    logger.info("Ticker fetched successfully")
    logger.info(response)

    # ======================
    # 4️⃣ Last Price
    # ======================
    last_price = market.get_last_price(TRADE_SYMBOL)
    logger.info(f"Last price: {last_price}")

    if last_price is None or last_price <= 0:
        logger.error("Invalid market price")
        return

    # ======================
    # 5️⃣ Quantity Calculation
    # ======================
    logger.info("Calculating order quantity...")

    raw_qty = NOTIONAL_USDT / last_price
    STEP_SIZE = 0.0001

    qty = math.floor(raw_qty / STEP_SIZE) * STEP_SIZE
    qty = round(qty, 4)  # match step precision

    if qty <= 0:
        logger.error("Calculated quantity is invalid after step adjustment")
        return

    logger.info(f"Raw qty: {raw_qty}")
    logger.info(f"Adjusted qty (stepSize={STEP_SIZE}): {qty}")


    # ======================
    # 6️⃣ Dry-Run Order Preview
    # ======================
    logger.info("Order preview (DRY RUN)")

    order_preview = {
        "symbol": TRADE_SYMBOL,
        "side": "OPEN_LONG",
        "order_type": "MARKET",
        "notional_usdt": NOTIONAL_USDT,
        "size": qty,
        "reference_price": last_price,
        "leverage": LEVERAGE,
        "dry_run": DRY_RUN
    }

    for k, v in order_preview.items():
        logger.info(f"{k}: {v}")

    if not DRY_RUN:
        logger.info("EXECUTING LIVE ORDER (ONE TIME ONLY)")

        status, response = orders.place_market_order(
            symbol=TRADE_SYMBOL,
            size=str(qty),     # qty already calculated safely
            side="1"           # 1 = OPEN LONG
        )

        if status == 200:
            logger.info("Order placed successfully")
            logger.info(response)
        else:
            logger.error("Order placement failed")
            logger.error(f"Status: {status}")
            logger.error(response)

        logger.info("Execution complete — no further actions")

    # ======================
    # 7️⃣ Read-Only Order State Checks
    # ======================
    logger.info("Checking current orders (expected empty)")
    logger.info(orders.get_current_orders(symbol=TRADE_SYMBOL))

    logger.info("Checking order history (expected empty)")
    logger.info(orders.get_order_history(symbol=TRADE_SYMBOL, page_size=5))

    logger.info("Checking fills (expected empty)")
    logger.info(orders.get_fills(symbol=TRADE_SYMBOL, limit=5))

    time.sleep(2)
    logger.info("Bot exiting cleanly")


if __name__ == "__main__":
    main()
