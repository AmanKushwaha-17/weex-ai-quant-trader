class RiskManager:
    def __init__(self, client):
        self.client = client
        print("RiskManager initialized")

    def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: int = 1  # 1 = Cross, 3 = Isolated
    ):
        payload = {
            "symbol": symbol,
            "marginMode": margin_mode,
            "longLeverage": str(leverage),
            "shortLeverage": str(leverage),
        }

        return self.client.set_leverage(payload)



if __name__ == "__main__":
    print("risk.py loaded successfully")
