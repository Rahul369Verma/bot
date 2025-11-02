# src/executor/executor.py
import time
from typing import Dict, Any, List, Optional

class PaperExecutor:
    def __init__(self, client, lot_size: int = 35):
        self.client = client
        self.lot_size = lot_size
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trade_log: List[Dict[str, Any]] = []

    def _make_tradingsymbol(self, underlying: str, expiry: str, strike: int, side: str) -> str:
        cepe = "CE" if "CALL" in side else "PE"
        expiry_fmt = expiry.replace("-", "").upper() if expiry else "MONTH"
        return f"{underlying}{expiry_fmt}{strike}{cepe}"

    def place_paper_order(self, side: str, underlying: str, strike: int, expiry: str, qty_lots: int = 1) -> Dict[str, Any]:
        tradingsymbol = self._make_tradingsymbol(underlying, expiry, strike, side)
        quantity = self.lot_size * qty_lots
        price = self.client.get_option_ltp(tradingsymbol)

        order = self.client.place_order(tradingsymbol, "BUY", quantity, price)
        order_id = order["data"]["order_id"]

        trade = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "order_id": order_id,
            "tradingsymbol": tradingsymbol,
            "side": side,
            "qty": quantity,
            "price": price,
            "status": "OPEN",
        }
        self.trade_log.append(trade)

        self.positions[tradingsymbol] = {"qty": quantity, "avg_price": price, "side": side}
        return trade

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        return self.positions

    def close_position(self, tradingsymbol: str) -> Optional[Dict[str, Any]]:
        if tradingsymbol not in self.positions:
            return {"status": "error", "message": "Position not found"}

        pos = self.positions[tradingsymbol]
        sell_price = self.client.get_option_ltp(tradingsymbol)
        qty = pos["qty"]
        del self.positions[tradingsymbol]

        trade = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tradingsymbol": tradingsymbol,
            "side": "SELL",
            "qty": qty,
            "price": sell_price,
            "status": "CLOSED",
            "pnl": round((sell_price - pos["avg_price"]) * qty, 2)
        }
        self.trade_log.append(trade)
        return trade

    def compute_unrealized(self) -> List[Dict[str, Any]]:
        results = []
        for ts, pos in self.positions.items():
            ltp = self.client.get_option_ltp(ts)
            pnl = round((ltp - pos["avg_price"]) * pos["qty"], 2)
            results.append({
                "tradingsymbol": ts,
                "qty": pos["qty"],
                "avg_price": pos["avg_price"],
                "ltp": ltp,
                "unrealized_pnl": pnl
            })
        return results

    def reset(self):
        self.positions.clear()
        self.trade_log.clear()
