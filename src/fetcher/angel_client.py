import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pyotp
import pandas as pd 

try:
    from SmartApi import SmartConnect as SmartClient
except Exception:
    SmartClient = None

from src.fetcher.real_market_data import RealMarketData
from src.fetcher.market_analyzer import MarketAnalyzer
from src.fetcher.signal_storage import SignalStorage


class AngelClient:
    """
    Complete Angel Client with automated signal generation
    and REALISTIC intraday trading rules.
    """
    def __init__(self, api_key=None, paper=True):
        # ... (init logic is the same) ...
        self.paper = paper
        self.api_key = api_key or os.getenv("ANGEL_API_KEY")
        self.client_code = os.getenv("ANGEL_CLIENT_CODE")
        self.market_data = RealMarketData()
        self.market_analyzer = MarketAnalyzer()
        self.signal_storage = SignalStorage()
        self.api = None
        self.session_active = False
        if self.paper:
            print("✅ Angel Client initialized in PAPER TRADING mode.")
        self.lot_size = 35 
        self.min_investment = 10000
        self.simulated_premium_pct = 0.008 
        self.assumed_delta = 0.5 
        self.sl_mode = "ATR"
        self.atr_sl_multiplier = 1.0  
        self.atr_tp_multiplier = 2.0  
        self.sl_pct = 0.05 
        self.tp_ratio = 2.0  
        self.max_daily_loss = 2000 
        self.skip_today = False
        self.current_day_checked = None
        self.positions_map = {}
        self.orders = []
        self.trade_history = [] 
        self.daily_pnl = 0.0 
        self.signal_check_interval = 30 

    def check_new_day(self):
        # ... (no change) ...
        today = datetime.now().date()
        if self.current_day_checked != today:
            print(f"--- New Trading Day ({today}). Resetting daily rules. ---")
            self.current_day_checked = today
            self.daily_pnl = 0.0 
            self.skip_today = False

    def set_trading_parameters(self, max_daily_loss=None):
        # ... (no change) ...
        if max_daily_loss is not None:
            self.max_daily_loss = max_daily_loss

    # ----------- Market Data Methods -----------
    
    def get_5m_historical_data(self) -> pd.DataFrame:
        # ... (no change) ...
        try:
            return self.market_data.get_banknifty_historical(days=7)
        except Exception as e:
            print(f"Error getting 5m data: {e}"); return pd.DataFrame()

    def get_index_ltp(self, symbol: str = "BANKNIFTY") -> float:
        # ... (no change) ...
        try: return self.market_data.get_banknifty_spot()
        except Exception as e: raise Exception(f"Failed to get BankNifty LTP: {e}")

    def get_option_chain(self, expiry: str = "") -> List[Dict[str, Any]]:
        # ... (no change) ...
        try:
            chain = self.market_data.get_banknifty_option_chain(expiry_date=expiry)
            return chain
        except Exception as e:
            raise Exception(f"Failed to get option chain for '{expiry}': {e}")

    def get_expiry_dates(self) -> List[str]:
        # ... (no change) ...
        try:
            return self.market_data.get_expiry_dates()
        except Exception as e:
            raise Exception(f"Failed to get expiry dates: {e}")

    def get_option_ltp(self, tradingsymbol: str, expiry_hint: str) -> float:
        # ... (no change) ...
        try:
            chain = self.get_option_chain(expiry=expiry_hint)
            for item in chain:
                if item['tradingsymbol'] == tradingsymbol: return float(item['ltp'])
            chain = self.get_option_chain(expiry="")
            for item in chain:
                if item['tradingsymbol'] == tradingsymbol: return float(item['ltp'])
            raise Exception(f"Option {tradingsymbol} not found in any chain")
        except Exception as e:
            raise Exception(f"Failed to get option LTP: {e}")

    # ----------- Live Trading Logic -----------

    def generate_continuous_signals(self) -> List[Dict[str, Any]]:
        # ... (no change) ...
        if self.skip_today: return []
        if self.daily_pnl <= -abs(self.max_daily_loss): 
            return [] 
        if len(self.positions_map) > 0: return []
        try:
            historical_data = self.get_5m_historical_data()
            if historical_data.empty:
                print("No historical data, cannot generate signals.")
                return []
            signal = self.market_analyzer.generate_trading_signal(historical_data)
            if signal:
                print(f"✅ Strategy Signal Generated: {signal['reason']}")
                result = self.execute_strategy_trade(signal)
                if result.get('status'):
                    print(f"✅ Trade Executed: {result.get('message')}")
                else:
                    print(f"❌ Trade Failed: {result.get('message')}")
                return [signal] 
            return []
        except Exception as e:
            print(f"❌ Error in signal generation loop: {e}")
            return []
            
    def execute_strategy_trade(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        # ... (no change) ...
        try:
            expiry_dates = self.get_expiry_dates()
            if not expiry_dates:
                return {"status": False, "message": "No expiry dates available"}
            expiry = expiry_dates[0] 
            strike = signal.get("strike"); option_type = signal.get("type")
            expiry_dt = datetime.strptime(expiry, "%d-%b-%Y") 
            expiry_str = expiry_dt.strftime("%d%b%y").upper()
            tradingsymbol = f"BANKNIFTY{expiry_str}{strike}{option_type}"
            option_ltp = self.get_option_ltp(tradingsymbol, expiry_hint=expiry)
            cost_of_one_lot = option_ltp * self.lot_size
            if cost_of_one_lot < self.min_investment:
                self.skip_today = True 
                return {"status": False, "message": f"SKIP DAY: Lot cost ₹{cost_of_one_lot:,.0f} < ₹{self.min_investment:,.0f}"}
            quantity = self.lot_size 
            if self.sl_mode == "ATR":
                current_atr = signal.get('atr')
                if not current_atr: raise Exception("Signal did not contain 'atr' value.")
                index_sl_points = current_atr * self.atr_sl_multiplier; index_tp_points = current_atr * self.atr_tp_multiplier
                option_sl_points = index_sl_points * self.assumed_delta; option_tp_points = index_tp_points * self.assumed_delta
                stop_loss_price = round(option_ltp - option_sl_points, 1); take_profit_price = round(option_ltp + option_tp_points, 1)
            else: 
                sl_amount_total = cost_of_one_lot * self.sl_pct; tp_amount_total = sl_amount_total * self.tp_ratio
                sl_points = sl_amount_total / quantity; tp_points = tp_amount_total / quantity
                stop_loss_price = round(option_ltp - sl_points, 1); take_profit_price = round(option_ltp + tp_points, 1)
            result = self.place_order(
                tradingsymbol=tradingsymbol, transaction_type="BUY", quantity=quantity,
                price=option_ltp, stop_loss=stop_loss_price, take_profit=take_profit_price,
                expiry=expiry 
            )
            return result
        except Exception as e:
            return {"status": False, "message": f"Strategy execution failed: {e}"}

    def execute_manual_test_trade(self, signal_type: str) -> Dict[str, Any]:
        # ... (no change) ...
        print(f"--- Received Manual Test Signal: {signal_type} ---")
        if len(self.positions_map) > 0:
            return {"status": False, "message": "Bot is already in a position."}
        if self.skip_today: 
            return {"status": False, "message": "SKIPPED: Lot cost was < ₹10k earlier today."}
        if self.daily_pnl <= -abs(self.max_daily_loss): 
            return {"status": False, "message": f"STOPPED: Max daily loss of ₹{self.max_daily_loss} was hit."}
        try:
            spot_price = self.get_index_ltp()
            historical_data = self.get_5m_historical_data()
            hist_df = self.market_analyzer.calculate_indicators(historical_data)
            if hist_df is None or hist_df.empty:
                return {"status": False, "message": "Could not calculate indicators for ATR."}
            current_atr = hist_df.iloc[-1]['atr']
            strike = int(round(spot_price / 100.0) * 100)
            fake_signal = {
                "signal": "BUY", "type": signal_type, "price": spot_price,
                "strike": strike, "reason": f"MANUAL TEST SIGNAL ({signal_type})",
                "atr": current_atr
            }
            return self.execute_strategy_trade(fake_signal)
        except Exception as e:
            return {"status": False, "message": f"Manual trade failed: {e}"}
    
            
    def check_and_close_positions(self):
        # ... (no change) ...
        open_symbols = list(self.positions_map.keys())
        if not open_symbols: return
        for symbol in open_symbols:
            try:
                pos = self.positions_map[symbol]; expiry = pos.get('expiry') 
                ltp = self.get_option_ltp(symbol, expiry_hint=expiry)
                sl_price = pos.get('stop_loss'); tp_price = pos.get('take_profit')
                sl_hit = ltp <= sl_price; tp_hit = ltp >= tp_price
                if sl_hit or tp_hit:
                    reason = "STOP_LOSS" if sl_hit else "TAKE_PROFIT"
                    print(f"🔥 {reason} HIT for {symbol} at LTP {ltp} (SL: {sl_price}, TP: {tp_price})")
                    result = self.place_order(tradingsymbol=symbol, transaction_type="SELL", quantity=pos['qty'], price=ltp, is_exit=True)
                    if sl_hit and self.daily_pnl <= -abs(self.max_daily_loss):
                        print(f"--- MAX DAILY LOSS (₹{self.max_daily_loss}) HIT. STOPPING TRADING FOR THE DAY. ---")
            except Exception as e:
                print(f"❌ Error checking position {symbol} (Market may be closed): {e}")

    # --- NEW: Close All Positions Function ---
    def close_all_live_positions(self) -> Dict[str, Any]:
        """
        Manually closes all open paper positions at their current live price.
        """
        print("--- MANUAL: Received request to CLOSE ALL POSITIONS ---")
        results = []
        total_pnl = 0
        
        symbols_to_close = list(self.positions_map.keys()) 
        
        if not symbols_to_close:
            return {"status": "info", "message": "No open positions to close."}

        for symbol in symbols_to_close:
            try:
                pos = self.positions_map.get(symbol)
                if not pos:
                    continue # Already closed
                
                expiry_hint = pos.get('expiry')
                quantity = pos.get('qty')
                
                # 1. Get live price
                ltp = self.get_option_ltp(symbol, expiry_hint=expiry_hint)
                
                # 2. Call place_order to handle closing logic
                result = self.place_order(
                    tradingsymbol=symbol,
                    transaction_type="SELL",
                    quantity=quantity,
                    price=ltp,
                    is_exit=True
                )
                
                if result.get('status'):
                    print(f"✅ Manually closed {symbol}")
                    if result.get('trade_pnl') is not None:
                        total_pnl += result['trade_pnl']
                    results.append(result)
                else:
                    print(f"❌ Failed to manually close {symbol}: {result.get('message')}")
                    results.append(result)
                    
            except Exception as e:
                print(f"❌ CRITICAL ERROR closing {symbol}: {e}")
                results.append({"status": False, "message": f"Error closing {symbol}: {e}"})

        return {
            "status": "success",
            "message": f"Closed {len(symbols_to_close)} position(s).",
            "total_pnl": total_pnl,
            "results": results
        }
    # --- END NEW FUNCTION ---

    # ----------- Paper/Real Trading Methods -----------
    def place_order(self, tradingsymbol: str, transaction_type: str, quantity: int, 
                    price: Optional[float] = None, 
                    stop_loss: Optional[float] = None, 
                    take_profit: Optional[float] = None,
                    expiry: Optional[str] = None, 
                    is_exit: bool = False) -> Dict[str, Any]:
        # ... (no change) ...
        transaction_type = transaction_type.upper()
        if self.paper:
            try:
                if price is None:
                    price = self.get_option_ltp(tradingsymbol, expiry_hint=expiry if expiry else "")
                order_id = f"PAPER-{int(time.time()*1000)}"; order_status = "COMPLETED"
                if is_exit or transaction_type == "SELL":
                    if tradingsymbol not in self.positions_map:
                        return {"status": False, "message": "Position not found"}
                    entry_pos = self.positions_map.pop(tradingsymbol) 
                    pnl = (price - entry_pos['avg_price']) * quantity
                    self.daily_pnl += pnl 
                    trade_record = {"timestamp": time.time(), "tradingsymbol": tradingsymbol, "transaction_type": "SELL", "quantity": quantity, "price": price, "pnl": pnl, "order_id": order_id}
                    self.trade_history.append(trade_record)
                    return {"status": True, "message": f"PAPER SELL {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": trade_record, "trade_pnl": pnl}
                else: 
                    self.positions_map[tradingsymbol] = {
                        "qty": quantity, "avg_price": price,
                        "stop_loss": stop_loss, "take_profit": take_profit,
                        "expiry": expiry 
                    }
                    order_record = {"timestamp": time.time(), "tradingsymbol": tradingsymbol, "transaction_type": "BUY", "quantity": quantity, "price": price, "status": order_status, "order_id": order_id}
                    self.orders.append(order_record)
                    return {"status": True, "message": f"PAPER BUY {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": order_record}
            except Exception as e:
                return {"status": False, "message": f"Paper order failed: {e}"}
        else:
            print("--- REAL TRADING IS NOT IMPLEMENTED ---")
            return {"status": False, "message": "Real trading logic is not implemented."}

    # ... (rest of helper functions: get_positions, get_trade_history, etc.) ...
    def get_positions(self) -> List[Dict[str, Any]]:
        # ... (no change) ...
        positions = []
        for symbol, pos in self.positions_map.items():
            try:
                current_price = self.get_option_ltp(symbol, expiry_hint=pos.get('expiry'))
                unrealized_pnl = (current_price - pos["avg_price"]) * pos["qty"]
                positions.append({"tradingsymbol": symbol, "qty": pos["qty"], "avg_price": round(pos["avg_price"], 2), "current_price": round(current_price, 2), "unrealized_pnl": round(unrealized_pnl, 2), "sl": pos.get('stop_loss'), "tp": pos.get('take_profit')})
            except: continue
        return positions
    def get_trade_history(self) -> List[Dict[str, Any]]: return self.trade_history
    def get_daily_pnl(self) -> float: return self.daily_pnl
    def get_portfolio_value(self) -> Dict[str, float]:
        # ... (no change) ...
        positions = self.get_positions()
        total_investment = sum(pos['avg_price'] * abs(pos['qty']) for pos in positions)
        total_current = sum(pos['current_price'] * abs(pos['qty']) for pos in positions)
        total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)
        return {"total_investment": round(total_investment, 2), "total_current_value": round(total_current, 2), "total_unrealized_pnl": round(total_unrealized_pnl, 2), "daily_realized_pnl": round(self.daily_pnl, 2)}