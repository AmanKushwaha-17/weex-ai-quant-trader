import json
import logging
import pandas as pd

logger = logging.getLogger(__name__)


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
    
    # ======================================================
    # Get OHLCV Candles
    # ======================================================
    def get_candles(self, symbol: str, timeframe: str, limit: int = 300):
        """
        Fetch OHLCV candles from WEEX
        """
        status, response = self.client.get_candles(
            symbol=symbol,
            period=timeframe,
            limit=limit,
        )

        if status != 200 or response is None:
            logger.error(f"Candle fetch failed for {symbol}")
            return None

        try:
            raw = response["data"]
        except Exception:
            logger.error(f"Invalid candle response for {symbol}")
            return None

        df = pd.DataFrame(
            raw,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
            ],
        )

        # Type casting
        df["open_time"] = df["open_time"].astype("int64")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # Ensure correct order
        df = df.sort_values("open_time").reset_index(drop=True)
        return df
    # ======================================================
    # 🆕 ADD 2️⃣: Feature Builder (ML-ready)
    # ======================================================
    def get_features(
        self,
        symbol: str,
        timeframe: str,
        lookback: int = 300,
    ):
        """
        Returns ML feature DataFrame
        """
        candles = self.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=lookback,
        )

        if candles is None or len(candles) < 50:
            logger.warning(f"Not enough data for features: {symbol}")
            return None

        # Import here to avoid circular dependency
        from research.features_builder import build_features

        features_df = build_features(candles)
        return features_df
