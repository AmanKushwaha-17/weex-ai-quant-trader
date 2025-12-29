import os
import time
import hmac
import hashlib
import base64
import json
import logging
import requests

from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

load_dotenv()


class WeexClient:
    def __init__(self):
        self.api_key = os.getenv("WEEX_API_KEY")
        self.api_secret = os.getenv("WEEX_API_SECRET")
        self.api_passphrase = os.getenv("WEEX_API_PASSPHRASE")
        self.base_url = os.getenv("WEEX_BASE_URL")

        if not all([self.api_key, self.api_secret, self.api_passphrase, self.base_url]):
            raise ValueError("WEEX API credentials not fully loaded")

        print("API credential loaded successfully")

        # ==============================
        # 🔒 STABLE SESSION (CRITICAL)
        # ==============================
        self.session = requests.Session()

        retries = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False
        )

        adapter = HTTPAdapter(
            max_retries=retries,
            pool_connections=10,
            pool_maxsize=10
        )

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.default_headers = {
            "Content-Type": "application/json",
            "locale": "en-US",
            "Connection": "keep-alive",
        }

    # =====================================================
    # 🔐 SIGNATURE HELPERS
    # =====================================================
    def _generate_signature_get(self, timestamp, method, request_path, query_string):
        msg = timestamp + method.upper() + request_path + query_string
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode()

    def _generate_signature_post(self, timestamp, method, request_path, body):
        msg = timestamp + method.upper() + request_path + body
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode()

    # =====================================================
    # 🌐 CORE REQUEST WRAPPERS (SESSION ONLY)
    # =====================================================
    def _get(self, request_path, query_string=""):
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(timestamp, "GET", request_path, query_string)

        headers = {
            **self.default_headers,
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
        }

        url = self.base_url + request_path + query_string

        try:
            return self.session.get(url, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.error(f"GET request failed: {url} | {e}")
            return None

    def _post(self, request_path, body):
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_post(timestamp, "POST", request_path, body)

        headers = {
            **self.default_headers,
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
        }

        url = self.base_url + request_path

        try:
            return self.session.post(url, headers=headers, data=body, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.error(f"POST request failed: {url} | {e}")
            return None

    # =====================================================
    # 📊 MARKET DATA
    # =====================================================
    def get_candles(self, symbol: str, period: str, limit: int = 300):
        request_path = "/capi/v2/market/candles"
        query_string = f"?symbol={symbol}&granularity={period}&limit={limit}"

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"Candle JSON parse error: {e}")
            return resp.status_code, None

        # WEEX returns raw list
        if isinstance(data, list):
            return resp.status_code, data

        return resp.status_code, None

    def get_price_ticker(self, symbol: str):
        request_path = "/capi/v2/market/ticker"
        query_string = f"?symbol={symbol}"

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None

        return resp.status_code, resp.text

    # =====================================================
    # 💰 ACCOUNT / ORDERS
    # =====================================================
    def get_account_balance(self):
        request_path = "/capi/v2/account/assets"

        resp = self._get(request_path)
        if resp is None:
            return None, None

        return resp.status_code, resp.text

    def set_leverage(self, payload: dict):
        body = json.dumps(payload)
        resp = self._post("/capi/v2/account/leverage", body)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def place_order(self, payload: dict):
        body = json.dumps(payload)
        resp = self._post("/capi/v2/order/placeOrder", body)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def cancel_order(self, payload: dict):
        body = json.dumps(payload)
        resp = self._post("/capi/v2/order/cancel_order", body)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def get_order_detail(self, order_id: str):
        request_path = "/capi/v2/order/detail"
        query_string = f"?orderId={order_id}"

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def get_order_history(self, symbol: str = None, page_size: int = None, create_date: int = None):
        request_path = "/capi/v2/order/history"

        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if page_size:
            params.append(f"pageSize={page_size}")
        if create_date:
            params.append(f"createDate={create_date}")

        query_string = "?" + "&".join(params) if params else ""

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def get_current_orders(self, symbol=None, order_id=None, start_time=None, end_time=None, limit=100, page=0):
        request_path = "/capi/v2/order/current"

        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if order_id:
            params.append(f"orderId={order_id}")
        if start_time:
            params.append(f"startTime={start_time}")
        if end_time:
            params.append(f"endTime={end_time}")
        params.append(f"limit={limit}")
        params.append(f"page={page}")

        query_string = "?" + "&".join(params)

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None
        return resp.status_code, resp.text

    def get_fills(self, symbol=None, order_id=None, start_time=None, end_time=None, limit=100):
        request_path = "/capi/v2/order/fills"

        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if order_id:
            params.append(f"orderId={order_id}")
        if start_time:
            params.append(f"startTime={start_time}")
        if end_time:
            params.append(f"endTime={end_time}")
        params.append(f"limit={limit}")

        query_string = "?" + "&".join(params)

        resp = self._get(request_path, query_string)
        if resp is None:
            return None, None
        return resp.status_code, resp.text
    
    def get_positions(self):
        request_path = "/capi/v2/account/position/allPosition"

        resp = self._get(request_path)
        if resp is None:
            return None, None

        return resp.status_code, resp.text
    
    def upload_ai_log(self, payload: dict):
        body = json.dumps(payload)
        resp = self._post("/capi/v2/order/uploadAiLog", body)
        if resp is None:
            return None, None
        return resp.status_code, resp.text





if __name__ == "__main__":
    print("client.py loaded successfully")
