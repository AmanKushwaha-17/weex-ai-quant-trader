import logging
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any


logger = logging.getLogger(__name__)


class InferenceEngine:
    """
    ML inference engine.
    Responsible ONLY for:
      - loading model bundle
      - validating features
      - running predict_proba
      - returning direction + confidence
    """

    # ML-only config (do NOT mix with trading / risk logic)
    MIN_CONFIDENCE = 0.60

    def __init__(self, model_bundle_path: str):
        """
        Load model + metadata ONCE at startup.
        """
        try:
            bundle = joblib.load(model_bundle_path)

            self.model = bundle["model"]
            self.feature_cols = bundle["feature_cols"]
            self.label_quantiles = bundle.get("label_quantiles", {})
            self.horizon = bundle.get("horizon", None)

            logger.info("InferenceEngine initialized successfully")
            logger.info(f"Loaded {len(self.feature_cols)} features")
            if self.horizon is not None:
                logger.info(f"Model horizon: {self.horizon} candles")

        except Exception as e:
            logger.exception("Failed to load model bundle")
            raise RuntimeError("InferenceEngine initialization failed") from e

    def infer(self,features_df: pd.DataFrame,symbol: str,timestamp=None) -> Dict[str, Any]:
        """
        Run inference on the latest row of features_df.

        Returns:
            {
                symbol,
                prediction,
                direction,
                confidence,
                should_trade
            }
        """

        # ---------- Default safe output ----------
        result = {
            "symbol": symbol,
            "prediction": None,
            "direction": 0,
            "confidence": 0.0,
            "should_trade": False,
        }

        # ---------- Basic validation ----------
        if features_df is None or len(features_df) == 0:
            logger.warning(f"[INFER] Empty features_df for {symbol}")
            return result

        # ---------- Feature presence check ----------
        missing = [c for c in self.feature_cols if c not in features_df.columns]
        if missing:
            logger.warning(
                f"[INFER] Missing features for {symbol}: {missing}"
            )
            return result

        # ---------- Extract latest row ----------
        try:
            X_live = features_df.iloc[-1][self.feature_cols]

            # Check NaNs
            if X_live.isna().any():
                logger.warning(
                    f"[INFER] NaN values detected in features for {symbol}"
                )
                return result

            # LightGBM expects 2D input
            X_live = X_live.values.reshape(1, -1)

        except Exception as e:
            logger.exception(f"[INFER] Feature extraction failed for {symbol}")
            return result

        # ---------- Model inference ----------
        try:
            proba = self.model.predict_proba(X_live)[0]

            confidence = float(np.max(proba))
            prediction = int(np.argmax(proba))

            # Direction mapping
            # 1 -> extreme positive -> LONG
            # 0 -> extreme negative -> SHORT
            direction = 1 if prediction == 1 else -1

            should_trade = confidence >= self.MIN_CONFIDENCE

            result.update(
                {
                    "prediction": prediction,
                    "direction": direction,
                    "confidence": confidence,
                    "should_trade": should_trade,
                }
            )

            logger.info(
                f"[ML INFER] {symbol} | "
                f"dir={direction:+d} | "
                f"conf={confidence:.3f} | "
                f"trade={should_trade}"
            )

            return result

        except Exception as e:
            logger.exception(f"[INFER] Model inference failed for {symbol}")
            return result
