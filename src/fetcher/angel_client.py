import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pyotp
import pandas as pd # Import pandas

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
        self.paper = paper
        self.api_key = api_key or os.getenv("ANGEL_API_KEY")
        self.client_code = os.getenv("ANGEL_CLIENT_CODE")
        
        self.market_data = RealMarketData()
        self.market_analyzer = MarketAnalyzer()
        self.signal_storage = SignalStorage()
        
        self.api = None
        self.session_active = False
        
        # ... (real login code remains commented out) ...

        if self.paper:
            print("✅ Angel Client initialized in PAPER TRADING mode.")

        # --- UPDATED: Realistic Trading State ---
        self.lot_size = 35 # BankNifty Lot Size
        self.min_investment = 10000
        self.simulated_premium_pct = 0.008 # 0.8% of index
        self.assumed_delta = 0.5 # Assumed option delta for ATM
        
        # --- NEW: Set ATR as default SL/TP logic ---
        self.sl_mode = "ATR"
        self.atr_sl_multiplier = 0.5
        self.atr_tp_multiplier = 2.0
        
        # Fallback values for "Invested Value" mode
        self.sl_pct = 0.05 # 5% Stop Loss
        self.tp_ratio = 2.0  # 2x TP
        # --- END NEW ---
        
        self.daily_sl_count = 0
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
            self.daily_sl_count = 0
            self.skip_today = False

    # ----------- Market Data Methods -----------
    
    def get_5m_historical_data(self) -> pd.DataFrame:
        # ... (no change) ...
        try:
            return self.market_data.get_banknifty_historical(days=7)
        except Exception as e:
            print(f"Error getting 5m data: {e}")
            return pd.DataFrame()

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
                if item['tradingsymbol'] == tradingsymbol:
                    return float(item['ltp'])
            chain = self.get_option_chain(expiry="")
            for item in chain:
                if item['tradingsymbol'] == tradingsymbol:
                    return float(item['ltp'])
            raise Exception(f"Option {tradingsymbol} not found in any chain")
        except Exception as e:
            raise Exception(f"Failed to get option LTP: {e}")

    # ----------- Live Trading Logic -----------

    def generate_continuous_signals(self) -> List[Dict[str, Any]]:
        # ... (no change) ...
        if self.skip_today: return []
        if self.daily_sl_count >= 2: return []
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
            
    # --- UPDATED execute_strategy_trade ---
    def execute_strategy_trade(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a trade based on the new rules (1 Lot, >10k, etc.)
        and uses the default SL/TP logic (ATR).
        """
        try:
            expiry_dates = self.get_expiry_dates()
            if not expiry_dates:
                return {"status": False, "message": "No expiry dates available"}
            
            expiry = expiry_dates[0] 
            strike = signal.get("strike")
            option_type = signal.get("type")
            
            # Use the correct date format from NSE (e.g., 04-Nov-2025 -> 04NOV25)
            expiry_dt = datetime.strptime(expiry, "%d-%b-%Y") # NSE format is dd-MMM-YYYY
            expiry_str = expiry_dt.strftime("%d%b%y").upper()
            
            tradingsymbol = f"BANKNIFTY{expiry_str}{strike}{option_type}"
            
            # --- 1 Lot > 10k Rule ---
            option_ltp = self.get_option_ltp(tradingsymbol, expiry_hint=expiry)
            
            cost_of_one_lot = option_ltp * self.lot_size
            
            if cost_of_one_lot < self.min_investment:
                self.skip_today = True 
                return {"status": False, "message": f"SKIP DAY: Lot cost ₹{cost_of_one_lot:,.0f} < ₹{self.min_investment:,.0f}"}

            quantity = self.lot_size # Always 1 lot
            
            # --- NEW: SL/TP Calculation (ATR Mode) ---
            if self.sl_mode == "ATR":
                current_atr = signal.get('atr')
                if not current_atr:
                    raise Exception("Signal did not contain 'atr' value. Cannot use ATR stop loss.")
                
                # 1. Calculate Index SL/TP in points
                index_sl_points = current_atr * self.atr_sl_multiplier
                index_tp_points = current_atr * self.atr_tp_multiplier
                
                # 2. Convert to Option SL/TP using Delta
                option_sl_points = index_sl_points * self.assumed_delta
                option_tp_points = index_tp_points * self.assumed_delta
                
                # 3. Calculate final prices
                stop_loss_price = round(option_ltp - option_sl_points, 1)
                take_profit_price = round(option_ltp + option_tp_points, 1)
                
            else: # Fallback to "Invested Value"
                sl_amount_total = cost_of_one_lot * self.sl_pct
                tp_amount_total = sl_amount_total * self.tp_ratio
                sl_points = sl_amount_total / quantity
                tp_points = tp_amount_total / quantity
                
                stop_loss_price = round(option_ltp - sl_points, 1)
                take_profit_price = round(option_ltp + tp_points, 1)
            # --- END SL/TP CALC ---

            # --- Place the real/paper order ---
            result = self.place_order(
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=quantity,
                price=option_ltp,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price,
                expiry=expiry # Pass expiry for storage
            )
            
            return result
            
        except Exception as e:
            return {"status": False, "message": f"Strategy execution failed: {e}"}
            
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
                    if sl_hit:
                        self.daily_sl_count += 1
                        print(f"🛑 Daily SL Count: {self.daily_sl_count}")
                        if self.daily_sl_count >= 2:
                            print("--- 2 STOP LOSSES HIT. STOPPING TRADING FOR THE DAY. ---")
            except Exception as e:
                print(f"❌ Error checking position {symbol} (Market may be closed): {e}")

    # ----------- Paper/Real Trading Methods -----------
    def place_order(self, tradingsymbol: str, transaction_type: str, quantity: int, 
                    price: Optional[float] = None, 
                    stop_loss: Optional[float] = None, 
                    take_profit: Optional[float] = None,
                    expiry: Optional[str] = None, # Added expiry
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
                    entry_pos = self.positions_map.pop(tradingsymbol) # Close position
                    pnl = (price - entry_pos['avg_price']) * quantity
                    self.daily_pnl += pnl
                    trade_record = {"timestamp": time.time(), "tradingsymbol": tradingsymbol, "transaction_type": "SELL", "quantity": quantity, "price": price, "pnl": pnl, "order_id": order_id}
                    self.trade_history.append(trade_record)
                    return {"status": True, "message": f"PAPER SELL {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": trade_record, "trade_pnl": pnl}
                else: # This is a BUY (entry) order
                    self.positions_map[tradingsymbol] = {
                        "qty": quantity, "avg_price": price,
                        "stop_loss": stop_loss, "take_profit": take_profit,
                        "expiry": expiry # Store the expiry
                    }
                    order_record = {"timestamp": time.time(), "tradingsymbol": tradingsymbol, "transaction_type": "BUY", "quantity": quantity, "price": price, "status": order_status, "order_id": order_id}
                    self.orders.append(order_record)
                    return {"status": True, "message": f"PAPER BUY {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": order_record}
            except Exception as e:
                return {"status": False, "message": f"Paper order failed: {e}"}
        else:
            # --- REAL ANGEL ONE TRADING LOGIC ---
            pass

    # ... (rest of helper functions: get_positions, get_trade_history, etc.) ...
    def get_positions(self) -> List[Dict[str, Any]]:
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
        positions = self.get_positions()
        total_investment = sum(pos['avg_price'] * abs(pos['qty']) for pos in positions)
        total_current = sum(pos['current_price'] * abs(pos['qty']) for pos in positions)
        total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)
        return {"total_investment": round(total_investment, 2), "total_current_value": round(total_current, 2), "total_unrealized_pnl": round(total_unrealized_pnl, 2), "daily_realized_pnl": round(self.daily_pnl, 2)}