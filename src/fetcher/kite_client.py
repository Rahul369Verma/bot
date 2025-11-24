# fetcher/kite_client.py
from kiteconnect import KiteConnect
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KiteClient:
    def __init__(self, api_key, api_secret, access_token, paper=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.paper = paper
        self.kite = None

        if not paper:
            try:
                self.kite = KiteConnect(api_key=self.api_key)
                self.kite.set_access_token(self.access_token)
                logger.info("KiteClient initialized in REAL mode.")
            except Exception as e:
                logger.error(f"Failed to initialize KiteConnect: {e}")
                raise e
        else:
            self.orders = []
            self.positions = {}
            logger.info("KiteClient initialized in PAPER mode.")

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, product_type="MIS", price=None, tag="bot_trade"):
        """
        Places a regular order (Market or Limit).
        """
        if self.paper:
            logger.info(f"[PAPER] {transaction_type} {tradingsymbol} x {quantity} @ {price or 'MARKET'}")
            self.orders.append({
                "tradingsymbol": tradingsymbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "price": price,
                "product": product_type,
                "tag": tag
            })
            # Simulate position update
            current_qty = self.positions.get(tradingsymbol, 0)
            if transaction_type.upper() == "BUY":
                self.positions[tradingsymbol] = current_qty + quantity
            elif transaction_type.upper() == "SELL":
                self.positions[tradingsymbol] = current_qty - quantity
            
            return {"status": "success", "order_id": "simulated_order_id", "tradingsymbol": tradingsymbol}

        try:
            order_id = self.kite.place_order(
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                transaction_type=transaction_type,
                quantity=quantity,
                variety=self.kite.VARIETY_REGULAR,
                order_type=self.kite.ORDER_TYPE_MARKET if price is None else self.kite.ORDER_TYPE_LIMIT,
                product=product_type,
                price=price,
                tag=tag
            )
            logger.info(f"Order placed successfully. Order ID: {order_id}")
            return {"status": "success", "order_id": order_id, "tradingsymbol": tradingsymbol}
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"status": "error", "message": str(e)}

    def place_gtt_oco(self, tradingsymbol, exchange, transaction_type, quantity, product_type, price, stop_loss_price, target_price):
        """
        Places a GTT OCO (One Cancels Other) order for Stop Loss and Target.
        This is used to protect the position immediately after entry.
        
        Note: GTT is typically used for CNC/NRML positions. For MIS, it might be tricky or require manual management.
        However, using GTT is the safest way to ensure SL/TP persists.
        """
        if self.paper:
            logger.info(f"[PAPER] GTT OCO for {tradingsymbol}: SL {stop_loss_price}, Target {target_price}")
            return {"status": "success", "trigger_id": "simulated_gtt_id"}

        try:
            # GTT OCO requires two legs: one for SL, one for Target
            # If we BOUGHT, we need to SELL.
            
            trigger_type = self.kite.GTT_TYPE_OCO
            
            # Determine transaction type for exit (opposite of entry)
            exit_transaction_type = self.kite.TRANSACTION_TYPE_SELL if transaction_type == self.kite.TRANSACTION_TYPE_BUY else self.kite.TRANSACTION_TYPE_BUY
            
            # Construct the two legs
            # Leg 1: Stop Loss
            sl_order = {
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": exit_transaction_type,
                "quantity": quantity,
                "order_type": self.kite.ORDER_TYPE_LIMIT,
                "product": product_type,
                "price": stop_loss_price, # Limit price for execution
            }
            
            # Leg 2: Target
            target_order = {
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": exit_transaction_type,
                "quantity": quantity,
                "order_type": self.kite.ORDER_TYPE_LIMIT,
                "product": product_type,
                "price": target_price, # Limit price for execution
            }

            trigger_id = self.kite.place_gtt(
                trigger_type=trigger_type,
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                trigger_values=[stop_loss_price, target_price], # [SL Trigger, Target Trigger]
                last_price=price, # Current market price (approx)
                orders=[sl_order, target_order]
            )
            
            logger.info(f"GTT OCO placed successfully. Trigger ID: {trigger_id}")
            return {"status": "success", "trigger_id": trigger_id}

        except Exception as e:
            logger.error(f"Error placing GTT: {e}")
            return {"status": "error", "message": str(e)}

    def get_positions(self):
        if self.paper:
            return {"net": [{"tradingsymbol": k, "quantity": v, "pnl": 0} for k, v in self.positions.items() if v != 0]}
        
        try:
            return self.kite.positions()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {"net": [], "day": []}

    def get_holdings(self):
        if self.paper:
            return []
        try:
            return self.kite.holdings()
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return []

    def get_option_chain(self, symbol="BANKNIFTY", expiry=None, batch_size=100):
        # ... (Existing implementation or improved one) ...
        # For brevity, keeping the existing structure but ensuring it works in real mode
        if self.paper:
             return [
                {"tradingsymbol": "BANKNIFTY25OCT45000CE", "strike": 45000, "type": "CE", "ltp": 120, "volume": 1000},
                {"tradingsymbol": "BANKNIFTY25OCT45000PE", "strike": 45000, "type": "PE", "ltp": 95, "volume": 800},
            ]
        
        try:
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
                    logger.error(f"Batch quote fetch failed: {e}")

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
                    "ltp": q.get("last_price", 0),
                    "bid": depth.get("buy", [{}])[0].get("price", 0),
                    "ask": depth.get("sell", [{}])[0].get("price", 0),
                    "oi": q.get("oi", 0),
                })

            result.sort(key=lambda x: x["strike"])
            return result
        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return []
