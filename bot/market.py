import json

class MarketData:
    def __init__(self, client):
        self.client = client

    def get_ticker(self, symbol: str):
        status, response = self.client.get_price_ticker(symbol)

        if status != 200:
            print(f"Failed to fetch ticker | Status: {status}")
            print(response)
            return status, None

        return status, response

    def get_last_price(self, symbol: str):
        status, response = self.get_ticker(symbol)

        if status != 200 or response is None:
            return None

        data = json.loads(response)
        return float(data["last"])
