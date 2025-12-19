import os
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv
import json


load_dotenv()

class WeexClient:
    def __init__(self):
        self.api_key = os.getenv("WEEX_API_KEY")
        self.api_secret = os.getenv("WEEX_API_SECRET")
        self.api_passphrase = os.getenv("WEEX_API_PASSPHRASE")
        self.base_url =os.getenv("WEEX_BASE_URL")

        if not all([self.api_key,self.api_passphrase,self.api_secret]):
            raise  ValueError("All Api Credentials is not loaded yet")
        
        print("API credential loaded successfully")

        # ---------- SIGNATURE (GET) ----------
    def _generate_signature_get(self, timestamp, method, request_path, query_string):
        message = timestamp + method.upper() + request_path + query_string
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode()

    def _generate_signature_post(self, timestamp, method, request_path, body):
        message = timestamp + method.upper() + request_path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode()

    
    def get_account_balance(self):

        request_path ="/capi/v2/account/assets"
        query_string =""

        timestamp =str(int(time.time()*1000))
        signature=self._generate_signature_get(timestamp,"GET",request_path,query_string)


        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url= self.base_url+request_path
        response = requests.get(url,headers=headers,timeout=10)

        return response.status_code,response.text

    def get_price_ticker(self,symbol :str):

        request_path ="/capi/v2/market/ticker"
        query_string =f"?symbol={symbol}"

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get( timestamp, "GET", request_path, query_string )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE":self.api_passphrase, 
            "Content-Type": "application/json",
            "locale": "en-US",
             }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        return response.status_code, response.text


    def get_candles(self, symbol: str, period: str, limit: int = 300):
        """
        Fetch OHLCV candles from WEEX
        
        Args:
            symbol: Trading pair (e.g., "cmt_btcusdt")
            period: Timeframe (e.g., "15m", "1h", "4h")
            limit: Number of candles to fetch (default: 300)
        
        Returns:
            (status_code, response_dict)
        """
        request_path = "/capi/v2/market/candles"
        query_string = f"?symbol={symbol}&period={period}&limit={limit}"

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(timestamp, "GET", request_path, query_string)

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        # Return status and parsed JSON
        try:
            return response.status_code, response.json()
        except:
            return response.status_code, None



    def set_leverage(self, payload: dict):
        request_path = "/capi/v2/account/leverage"

        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload)

        signature = self._generate_signature_post(
            timestamp,
            "POST",
            request_path,
            body
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path
        response = requests.post(url, headers=headers, data=body, timeout=10)

        return response.status_code, response.text


    def place_order(self, payload: dict):

        request_path = "/capi/v2/order/placeOrder"

        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload)

        signature = self._generate_signature_post(
            timestamp,
            "POST",
            request_path,
            body
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path
        response = requests.post(url, headers=headers, data=body, timeout=10)

        return response.status_code, response.text

    def cancel_order(self, payload: dict):

        request_path = "/capi/v2/order/cancel_order"

        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload)

        signature = self._generate_signature_post(
            timestamp,
            "POST",
            request_path,
            body
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path
        response = requests.post(url, headers=headers, data=body, timeout=10)

        return response.status_code, response.text

    def get_order_detail(self, order_id: str):

        request_path = "/capi/v2/order/detail"
        query_string = f"?orderId={order_id}"

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(
            timestamp,
            "GET",
            request_path,
            query_string
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        return response.status_code, response.text


    def get_order_history(self,symbol: str = None,page_size: int = None,create_date: int = None):

        request_path = "/capi/v2/order/history"

        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if page_size:
            params.append(f"pageSize={page_size}")
        if create_date:
            params.append(f"createDate={create_date}")

        query_string = ""
        if params:
            query_string = "?" + "&".join(params)

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(
            timestamp,
            "GET",
            request_path,
            query_string
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        return response.status_code, response.text

    def get_current_orders(self,symbol: str = None,order_id: int = None,start_time: int = None,end_time: int = None,limit: int = 100,page: int = 0):

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
        if limit is not None:
            params.append(f"limit={limit}")
        if page is not None:
            params.append(f"page={page}")

        query_string = ""
        if params:
            query_string = "?" + "&".join(params)

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(
            timestamp,
            "GET",
            request_path,
            query_string
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        return response.status_code, response.text



    def get_fills(self,symbol: str = None,order_id: int = None,start_time: int = None,end_time: int = None,limit: int = 100):

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
        if limit:
            params.append(f"limit={limit}")

        query_string = ""
        if params:
            query_string = "?" + "&".join(params)

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature_get(
            timestamp,
            "GET",
            request_path,
            query_string
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        url = self.base_url + request_path + query_string
        response = requests.get(url, headers=headers, timeout=10)

        return response.status_code, response.text



if __name__ == "__main__":
    print("client.py loaded successfully")




