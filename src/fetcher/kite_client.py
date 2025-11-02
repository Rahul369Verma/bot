# fetcher/kite_client.py
from kiteconnect import KiteConnect

class KiteClient:
    def __init__(self, api_key, api_secret, access_token, paper=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.paper = paper

        if not paper:
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(self.access_token)
        else:
            self.orders = []
            self.positions = {}

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, price=None):
        if self.paper:
            print(f"[PAPER] {transaction_type} {tradingsymbol} x {quantity} @ {price or 'MARKET'}")
            self.orders.append({
                "tradingsymbol": tradingsymbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "price": price
            })
            self.positions[tradingsymbol] = self.positions.get(tradingsymbol, 0)
            self.positions[tradingsymbol] += quantity if transaction_type.upper() == "BUY" else -quantity
            return {"status": "simulated", "tradingsymbol": tradingsymbol}

        return self.kite.place_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type="MARKET" if price is None else "LIMIT",
            price=price
        )

    def get_positions(self):
        if self.paper:
            return self.positions
        return self.kite.positions()

    def get_holdings(self):
        if self.paper:
            return {symbol: qty for symbol, qty in self.positions.items() if qty != 0}
        return self.kite.holdings()

    def get_option_chain(self, symbol="BANKNIFTY", expiry=None, batch_size=100):
        if self.paper:
            return [
                {"tradingsymbol": "BANKNIFTY25OCT45000CE", "strike": 45000, "type": "CE", "ltp": 120, "volume": 1000},
                {"tradingsymbol": "BANKNIFTY25OCT45000PE", "strike": 45000, "type": "PE", "ltp": 95, "volume": 800},
            ]

        instruments = self.kite.instruments("NFO")
        chain = [
            inst for inst in instruments 
            if inst["name"] == symbol 
            and inst["instrument_type"] in ["CE", "PE"]
            and (expiry is None or str(inst["expiry"]) == str(expiry))
        ]

        if not chain:
            return []

        tradingsymbols = [inst["tradingsymbol"] for inst in chain]
        quotes = {}

        for i in range(0, len(tradingsymbols), batch_size):
            batch = tradingsymbols[i : i + batch_size]
            try:
                part = self.kite.quote(batch)
                quotes.update(part)
            except Exception as e:
                print("Batch failed:", e)

        result = []
        for inst in chain:
            q = quotes.get(inst["tradingsymbol"], {})
            depth = q.get("depth", {})

            result.append({
                "tradingsymbol": inst["tradingsymbol"],
                "strike": inst["strike"],
                "type": inst["instrument_type"],
                "expiry": inst["expiry"],
                "lot_size": inst["lot_size"],
                "ltp": q.get("last_price"),
                "bid": depth.get("buy", [{}])[0].get("price"),
                "ask": depth.get("sell", [{}])[0].get("price"),
                "oi": q.get("oi"),
            })

        result.sort(key=lambda x: x["strike"])
        return result
