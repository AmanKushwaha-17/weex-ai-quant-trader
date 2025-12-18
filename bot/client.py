import os
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

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


if __name__ == "__main__":
    print("client.py loaded successfully")

