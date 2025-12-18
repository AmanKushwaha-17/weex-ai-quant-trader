from bot.client import WeexClient
from bot.risk import RiskManager
import time

def main():
    print("Bot starting...")

    kill_switch = False
    if kill_switch:
        print("Kill switch active — exiting safely")
        return

    client = WeexClient()
    risk = RiskManager()

    status, response = client.get_account_balance()

    if status == 200:
        print("Account assets fetched successfully")
        print(response)
    else:
        print(f"API call failed | Status: {status}")
        print(response)

    print("READ-ONLY API MODE — no trading")

    time.sleep(3)
    print("Bot exiting cleanly")

if __name__ == "__main__":
    main()
