import time
import json
import logging
from typing import Optional, Dict, Tuple, List

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Production-safe OrderManager for WEEX Futures.

    Principles:
    - Market orders only
    - Engine controls exits (NO conditional orders here)
    - Best-effort verification (never blocks trading)
    - Incremental fill fetching
    """

    def __init__(self, client):
        self.client = client
        self.last_fill_timestamp = 0

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _parse_response(self, status: int, response) -> Tuple[bool, Optional[dict]]:
        if status is None or response is None:
            logger.error("❌ API request failed: empty response")
            return False, None

        if status != 200:
            logger.error(f"❌ API error | status={status} | resp={response}")
            return False, None

        try:
            data = json.loads(response) if isinstance(response, str) else response

            # Some WEEX endpoints return dict with code/msg
            if isinstance(data, dict) and data.get("code", 0) != 0:
                logger.error(f"❌ API error | code={data.get('code')} | msg={data.get('msg')}")
                return False, None

            return True, data

        except Exception as e:
            logger.error(f"❌ Response parse error: {e}")
            return False, None

    def _verify_position(
        self,
        symbol: str,
        side: str,
        expected_size: float,
        tolerance: float = 1e-6,
        attempts: int = 3,
        delay: float = 1.0,
    ) -> bool:
        """
        Best-effort verification.
        DOES NOT block execution.
        """
        for i in range(attempts):
            if i > 0:
                time.sleep(delay)

            try:
                status, resp = self.client.get_positions()
                ok, data = self._parse_response(status, resp)
                if not ok:
                    continue

                # WEEX returns LIST
                positions = data if isinstance(data, list) else []

                for p in positions:
                    if (
                        p.get("symbol") == symbol
                        and p.get("side") == side
                        and abs(float(p.get("size", 0)) - expected_size) <= tolerance
                    ):
                        logger.info(f"✅ Position verified | {side} {expected_size}")
                        return True

            except Exception as e:
                logger.warning(f"⚠️ Verify position error: {e}")

        logger.warning("⚠️ Position verification inconclusive — continuing")
        return False

    # =====================================================
    # CORE ORDER METHODS
    # =====================================================

    def place_market_order(self, symbol: str, size: str, side: str):
        payload = {
            "symbol": symbol,
            "client_oid": f"weex_{int(time.time()*1000)}",
            "size": size,
            "type": side,          # 1=open long, 2=open short, 3=close long, 4=close short
            "order_type": "0",     # normal
            "match_price": "1",    # market
            "price": "0",
        }
        return self.client.place_order(payload)

    # =====================================================
    # OPEN POSITIONS
    # =====================================================

    
    def open_long(self, symbol: str, size: float):
        size_str = f"{size:.6f}"
        logger.info(f"🟢 OPEN LONG | {symbol} | size={size_str}")

        status, resp = self.place_market_order(symbol, size_str, side="1")
        ok, data = self._parse_response(status, resp)

        if not ok:
            logger.error("❌ OPEN LONG failed")
            return False, None

        order_id = None
        if isinstance(data, dict):
            order_id = data.get("data", {}).get("orderId")

        self._verify_position(symbol, "LONG", size)
        return True, order_id



    def open_short(self, symbol: str, size: float):
        size_str = f"{size:.6f}"
        logger.info(f"🔴 OPEN SHORT | {symbol} | size={size_str}")

        status, resp = self.place_market_order(symbol, size_str, side="2")
        ok, data = self._parse_response(status, resp)

        if not ok:
            logger.error("❌ OPEN SHORT failed")
            return False, None

        order_id = None
        if isinstance(data, dict):
            order_id = data.get("data", {}).get("orderId")

        self._verify_position(symbol, "SHORT", size)
        return True, order_id


    # =====================================================
    # CLOSE POSITIONS
    # =====================================================

    def close_long(self, symbol: str, size: float) -> bool:
        size_str = f"{size:.3f}"
        logger.info(f"🔵 CLOSE LONG | {symbol} | size={size_str}")

        status, resp = self.place_market_order(symbol, size_str, side="3")
        ok, _ = self._parse_response(status, resp)

        if not ok:
            logger.error("❌ CLOSE LONG failed")
            return False

        return True

    def close_short(self, symbol: str, size: float) -> bool:
        size_str = f"{size:.3f}"
        logger.info(f"🔴 CLOSE SHORT | {symbol} | size={size_str}")

        status, resp = self.place_market_order(symbol, size_str, side="4")
        ok, _ = self._parse_response(status, resp)

        if not ok:
            logger.error("❌ CLOSE SHORT failed")
            return False

        return True

    # =====================================================
    # FILLS (OPTIMIZED)
    # =====================================================

    def get_fills_optimized(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """
        Fetch only NEW fills since last poll.
        """
        try:
            status, resp = self.client.get_fills(
                symbol=symbol,
                start_time=self.last_fill_timestamp + 1 if self.last_fill_timestamp else None,
                limit=limit,
            )

            ok, data = self._parse_response(status, resp)
            if not ok:
                return []

            fills = data.get("data", []) if isinstance(data, dict) else []
            if fills:
                self.last_fill_timestamp = max(int(f["timestamp"]) for f in fills)

            return fills

        except Exception as e:
            logger.error(f"❌ Fetch fills error: {e}")
            return []

    # =====================================================
    # PASSTHROUGHS (OPTIONAL)
    # =====================================================

    def cancel_order(self, order_id: str = None, client_oid: str = None):
        if not order_id and not client_oid:
            raise ValueError("order_id or client_oid required")

        payload = {}
        if order_id:
            payload["orderId"] = order_id
        if client_oid:
            payload["clientOid"] = client_oid

        return self.client.cancel_order(payload)

    def get_order_info(self, order_id: str):
        return self.client.get_order_detail(order_id)

    def get_order_history(self, symbol: str = None, page_size: int = 10, create_date: int = None):
        return self.client.get_order_history(
            symbol=symbol,
            page_size=page_size,
            create_date=create_date,
        )

    def get_current_orders(
        self,
        symbol: str = None,
        order_id: int = None,
        start_time: int = None,
        end_time: int = None,
        limit: int = 100,
        page: int = 0,
    ):
        return self.client.get_current_orders(
            symbol=symbol,
            order_id=order_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            page=page,
        )
