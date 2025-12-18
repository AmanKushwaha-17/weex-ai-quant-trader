import time

class OrderManager:
    def __init__(self, client):
        self.client = client

    def place_market_order(
        self,
        symbol: str,
        size: str,
        side: str = "1"  # 1 = open long
    ):
        payload = {
            "symbol": symbol,
            "client_oid": f"weex_test_{int(time.time())}",
            "size": size,
            "type": side,
            "order_type": "0",
            "match_price": "1",
            "price": "0"
        }

        return self.client.place_order(payload)

    def cancel_order(self, order_id: str = None, client_oid: str = None):
        """
        Cancel an order by order_id or client_oid.
        At least one must be provided.
        """
        if not order_id and not client_oid:
            raise ValueError("Either order_id or client_oid must be provided")

        payload = {}
        if order_id:
            payload["orderId"] = order_id
        if client_oid:
            payload["clientOid"] = client_oid

        return self.client.cancel_order(payload)


    def get_order_info(self, order_id: str):
        """
        Fetch detailed information about an order using order_id.
        """
        return self.client.get_order_detail(order_id)


    def get_order_history(self,symbol: str = None,page_size: int = 10,create_date: int = None):
        """
        Fetch historical orders.
        """
        return self.client.get_order_history(
            symbol=symbol,
            page_size=page_size,
            create_date=create_date
        )

    
    def get_current_orders(self,symbol: str = None,order_id: int = None,start_time: int = None,end_time: int = None,limit: int = 100,page: int = 0):

        """
        Fetch currently open or pending orders.
        """
        return self.client.get_current_orders(
            symbol=symbol,
            order_id=order_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            page=page
        )

    def get_fills(self,symbol: str = None,order_id: int = None,start_time: int = None,end_time: int = None,limit: int = 100):
        """
        Fetch execution fills for orders.
        """
        return self.client.get_fills(
            symbol=symbol,
            order_id=order_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
