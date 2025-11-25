# Modified: src/fetcher/angel_client.py
# - Removed Scalping Strategy
# - Added new state variables and logic for max_trades, start_time, end_time

import os
import time
from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict, Any, Optional
import pyotp
import pandas as pd 
from zoneinfo import ZoneInfo
import threading 

try:
    from SmartApi import SmartConnect as SmartClient
except Exception:
    SmartClient = None

from .real_market_data import RealMarketData
from .signal_storage import SignalStorage
try:
    from backtest.yfinance_data import YFinanceData
    # --- MODIFIED: Removed Scalping strategy ---
    from backtest.backtest import MultiTimeframeStrategy 
except ImportError:
    print("CRITICAL: angel_client.py failed to import from 'backtest' module.")
    raise

IST = ZoneInfo('Asia/Kolkata')

class AngelClient:
    """
    Complete Angel Client with automated signal generation
    and REALISTIC intraday trading rules.
    """
    def __init__(self, api_key=None, paper=True, index_name="BANKNIFTY", fyers_manager=None, kite_client=None):
        self.paper = paper
        self.api_key = api_key or os.getenv("ANGEL_API_KEY")
        self.client_code = os.getenv("ANGEL_CLIENT_CODE")
        
        self.index_name = index_name
        self.yfinance_ticker = YFinanceData.INDEX_TICKERS.get(index_name, "^NSEBANK")
        print(f"AngelClient initializing for: {self.index_name} ({self.yfinance_ticker})")
        
        self.market_data = RealMarketData()
        self.fyers_manager = fyers_manager # Use Fyers for Index Data
        self.kite_client = kite_client # Use Kite for Execution
        self.signal_storage = SignalStorage()
        
        # --- MODIFIED: Simplified strategy map ---
        self.strategies = {
            'mta_ema_crossover': MultiTimeframeStrategy(),
        }
        self.active_strategy_name = 'mta_ema_crossover' # Only one strategy
        
        self.api = None
        self.session_active = False
        
        if self.paper:
            print(f"✅ Angel Client initialized in PAPER TRADING mode for {self.index_name}.")

        # --- Trading State ---
        self.lot_size = 35 
        self.min_investment = 10000
        self.simulated_premium_pct = 0.008 
        self.assumed_delta = 0.5 
        
        # Get defaults from the single strategy
        default_params = self.strategies[self.active_strategy_name].parameters
        
        self.sl_mode = default_params.get('sl_mode', 'ATR')
        self.atr_sl_multiplier = default_params.get('atr_sl_multiplier', 1.0)
        self.atr_tp_multiplier = default_params.get('atr_tp_multiplier', 2.0)
        self.sl_pct = default_params.get('invested_value_sl_pct', 5.0)
        self.tp_ratio = default_params.get('tp_sl_ratio', 2.0)
        
        # --- NEW STATE VARIABLES ---
        self.max_daily_loss = default_params.get('max_daily_loss', 2000)
        self.max_trades_per_day = default_params.get('max_trades_per_day', 10)
        self.trade_start_time = default_params.get('trade_start_time', dt_time(9, 30))
        self.trade_end_time = default_params.get('trade_end_time', dt_time(15, 0))
        self.today_trades_count = 0
        
        self.skip_today = False
        self.current_day_checked = None
        self.positions_map = {}
        self.orders = []
        self.trade_history = [] 
        self.daily_pnl = 0.0 
        self.signal_check_interval = 30 
        self.trade_lock = threading.Lock()
        self.trade_lock = threading.Lock()
        self.last_signal_timestamp = None # Initialize here too
        self.last_signal_check_time = None # Track when we last checked for signals

    def check_new_day(self):
        today = datetime.now(IST).date()
        if self.current_day_checked != today:
            print(f"--- New Trading Day ({today}). Resetting daily rules. ---")
            self.current_day_checked = today
            self.daily_pnl = 0.0 
            self.skip_today = False
            self.today_trades_count = 0 # <-- NEW: Reset trade count
            self.last_signal_timestamp = None # Track the last processed candle timestamp

    # --- MODIFIED: Added new params ---
    def set_trading_parameters(self, max_daily_loss=None, max_trades=None, start_time=None, end_time=None, min_lot_cost=None):
        """
        Called by the Streamlit UI to update the bot's risk parameters live.
        """
        if max_daily_loss is not None:
            self.max_daily_loss = max_daily_loss
        if max_trades is not None:
            self.max_trades_per_day = max_trades
        if start_time is not None:
            self.trade_start_time = start_time
        if end_time is not None:
            self.trade_end_time = end_time
        if min_lot_cost is not None:
            self.min_investment = min_lot_cost
            
    def set_active_strategy(self, strategy_name: str):
        # ... (no change, but will only ever be one strategy) ...
        if strategy_name in self.strategies:
            if self.active_strategy_name != strategy_name:
                print(f"--- STRATEGY UPDATED to: {strategy_name} ---")
                self.active_strategy_name = strategy_name
        else:
            print(f"❌ Error: Tried to set unknown strategy '{strategy_name}'")

    # ----------- Market Data Methods (no change) -----------
    # ----------- Market Data Methods (no change) -----------
    def get_multi_timeframe_data(self) -> pd.DataFrame:
        """
        Fetches 5m, 15m, and 1h data from Fyers and merges them.
        This matches the logic in BacktestEngine.prepare_data.
        """
        if not self.fyers_manager:
            print("❌ Fyers Manager not initialized in AngelClient.")
            return pd.DataFrame()
            
        try:
            end_date = datetime.now(IST)
            start_date = end_date - timedelta(days=5) # Fetch last 5 days
            
            # 1. Fetch Base Data (5m)
            df_5m = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "5")
            if df_5m is None or df_5m.empty: return pd.DataFrame()
            
            # 2. Fetch 15m Data
            df_15m = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "15")
            
            # 3. Fetch 1h Data
            df_1h = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "60")
            
            # 4. Calculate Indicators on Higher Timeframes BEFORE merging
            # Get params from active strategy
            params = self.strategies[self.active_strategy_name].parameters
            ema_short = params.get('ema_short', 9)
            ema_long = params.get('ema_long', 15)
            
            if df_15m is not None and not df_15m.empty:
                df_15m['ema_short_15m'] = df_15m['close'].ewm(span=ema_short, adjust=False).mean()
                df_15m['ema_long_15m'] = df_15m['close'].ewm(span=ema_long, adjust=False).mean()
                
            if df_1h is not None and not df_1h.empty:
                df_1h['ema_short_1h'] = df_1h['close'].ewm(span=ema_short, adjust=False).mean()
                df_1h['ema_long_1h'] = df_1h['close'].ewm(span=ema_long, adjust=False).mean()
                
            # 5. Merge Higher Timeframes to Base (5m)
            df_5m['15m_timestamp'] = df_5m.index.floor('15min')
            df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], left_on='15m_timestamp', right_index=True, how='left')
            
            # Fix for 1h candles starting at 09:15
            df_5m['1h_timestamp'] = (df_5m.index - pd.Timedelta(minutes=15)).floor('1h') + pd.Timedelta(minutes=15)
            df_5m = pd.merge(df_5m, df_1h[['ema_short_1h', 'ema_long_1h']], left_on='1h_timestamp', right_index=True, how='left')
            
            # Forward fill to propagate signals
            df_5m.ffill(inplace=True)
            
            return df_5m
            
        except Exception as e:
            print(f"Error fetching multi-timeframe data: {e}")
            return pd.DataFrame()

    def get_index_ltp(self) -> float:
        """
        Fetches the latest price of the index from Fyers.
        """
        if not self.fyers_manager:
            return 0.0
        return self.fyers_manager.get_index_spot(self.index_name)

    def get_5m_historical_data(self) -> pd.DataFrame:
        """
        Fetches 5m historical data for the index (last 5 days).
        Used for calculating EMAs in the UI.
        """
        if not self.fyers_manager:
            print("❌ Fyers Manager not initialized in AngelClient.")
            return pd.DataFrame()
            
        try:
            end_date = datetime.now(IST)
            start_date = end_date - timedelta(days=5)
            
            df_5m = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "5")
            if df_5m is None or df_5m.empty:
                return pd.DataFrame()
                
            return df_5m
        except Exception as e:
            print(f"Error fetching 5m historical data: {e}")
            return pd.DataFrame()

    def get_option_chain(self, expiry: str = "") -> List[Dict[str, Any]]:
        try: return self.market_data.get_banknifty_option_chain(self.index_name, expiry_date=expiry)
        except Exception as e: raise Exception(f"Failed to get option chain for '{expiry}': {e}")

    def get_expiry_dates(self) -> List[str]:
        try: return self.market_data.get_expiry_dates(self.index_name)
        except Exception as e: raise Exception(f"Failed to get expiry dates: {e}")

    def get_option_ltp(self, tradingsymbol: str, expiry_hint: str) -> float:
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
        with self.trade_lock:
            now_ist = datetime.now(IST)
            now_time = now_ist.time()
            
            # --- MODIFIED: Added new checks ---
            if now_time >= dt_time(15, 19): return [] # Hard EOD
            if not (self.trade_start_time <= now_time <= self.trade_end_time):
                return [] # Outside of allowed new trade window
            if self.today_trades_count >= self.max_trades_per_day:
                return [] # Max trades hit
            
            # --- NEW: 5-Minute Alignment Check ---
            # User requested to only hit API after 5 min candle close.
            # We check if we are in the first minute of a 5-minute block (e.g. 9:15, 9:20).
            # Since bot_loop runs every 30s, this allows us to catch the :00 or :30 mark of the target minute.
            # FIX: Only allow execution in the first 30 seconds to prevent double runs (at :00 and :30)
            if now_time.minute % 5 != 0 or now_time.second >= 30:
                # print(f"Skipping signal check (Not a 5-min mark): {now_time.strftime('%H:%M:%S')}")
                return []
            
            print(f"[DEBUG] Starting Signal Generation at {now_time.strftime('%H:%M:%S')}")
            self.last_signal_check_time = now_ist # Update check time
            # --- END MODIFIED ---
            
            if self.skip_today: return []
            if self.daily_pnl <= -abs(self.max_daily_loss): return [] 
            if len(self.positions_map) > 0: return [] 
            
            try:
                historical_data = self.get_multi_timeframe_data()
                if historical_data.empty:
                    print("No historical data (Fyers), cannot generate signals."); return []
                
                active_strategy = self.strategies[self.active_strategy_name]
                signal = active_strategy.generate_live_signal(historical_data)
                
                if signal:
                    # --- NEW: Check if we already processed this candle ---
                    signal_ts = signal.get('timestamp')
                    if signal_ts and self.last_signal_timestamp and signal_ts <= self.last_signal_timestamp:
                        # print(f"Skipping duplicate signal for candle {signal_ts}")
                        return []
                    
                    print(f"✅ Strategy Signal Generated: {signal['reason']} (Candle: {signal_ts})")
                    result = self.execute_strategy_trade(signal)
                    
                    # Update last processed timestamp if trade was attempted (success or fail, we acted on it)
                    # Actually, only if success? No, if we fail (e.g. margin), we shouldn't retry every 30s.
                    # We should mark this candle as 'processed'.
                    if signal_ts:
                        self.last_signal_timestamp = signal_ts
                        
                    return result
                    if result.get('status'):
                        print(f"✅ Trade Executed: {result.get('message')}")
                    else:
                        print(f"❌ Trade Failed: {result.get('message')}")
                    return [signal] 
                
                return []
            except Exception as e:
                print(f"❌ Error in signal generation loop: {e}"); return []
            
    def execute_strategy_trade(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        try:
            expiry_dates = self.get_expiry_dates()
            if not expiry_dates:
                return {"status": False, "message": "No expiry dates available"}
            expiry = expiry_dates[0] 
            strike = signal.get("strike")
            option_type = signal.get("type")
            expiry_dt = datetime.strptime(expiry, "%d-%b-%Y") 
            expiry_str = expiry_dt.strftime("%d%b%y").upper()
            tradingsymbol = f"{self.index_name}{expiry_str}{strike}{option_type}"
            option_ltp = self.get_option_ltp(tradingsymbol, expiry_hint=expiry)
            cost_of_one_lot = option_ltp * self.lot_size
            if cost_of_one_lot < self.min_investment:
                self.skip_today = True 
                return {"status": False, "message": f"SKIP DAY: Lot cost ₹{cost_of_one_lot:,.0f} < ₹{self.min_investment:,.0f}"}

            quantity = self.lot_size 
            active_strategy = self.strategies[self.active_strategy_name]
            params = active_strategy.parameters
            
            if self.sl_mode == "ATR":
                current_atr = signal.get('atr')
                if not current_atr:
                    raise Exception("Signal did not contain 'atr' value. Cannot use ATR stop loss.")
                atr_sl_mult = params.get('atr_sl_multiplier', self.atr_sl_multiplier)
                atr_tp_mult = params.get('atr_tp_multiplier', self.atr_tp_multiplier)
                index_sl_points = current_atr * atr_sl_mult
                index_tp_points = current_atr * atr_tp_mult
                option_sl_points = index_sl_points * self.assumed_delta
                option_tp_points = index_tp_points * self.assumed_delta
                stop_loss_price = round(option_ltp - option_sl_points, 1)
                take_profit_price = round(option_ltp + option_tp_points, 1)
            else: # "Invested Value"
                sl_pct_val = params.get('invested_value_sl_pct', self.sl_pct) / 100.0
                tp_ratio_val = params.get('tp_sl_ratio', self.tp_ratio)
                sl_amount_total = cost_of_one_lot * sl_pct_val
                tp_amount_total = sl_amount_total * tp_ratio_val
                sl_points = sl_amount_total / quantity
                tp_points = tp_amount_total / quantity
                stop_loss_price = round(option_ltp - sl_points, 1)
                take_profit_price = round(option_ltp + tp_points, 1)

            if self.paper:
                result = self.place_order(
                    tradingsymbol=tradingsymbol, transaction_type="BUY", quantity=quantity,
                    price=option_ltp, stop_loss=stop_loss_price, take_profit=take_profit_price,
                    expiry=expiry 
                )
            else:
                # REAL TRADING with GTT OCO
                if self.kite_client:
                    print(f"🚀 Placing REAL GTT OCO Order for {tradingsymbol}...")
                    # 1. Place Market Entry Order
                    entry_result = self.kite_client.place_order(
                        tradingsymbol=tradingsymbol,
                        exchange="NFO",
                        transaction_type="BUY",
                        quantity=quantity,
                        product_type="MIS", # Intraday
                        price=None, # Market Order
                        tag="bot_entry"
                    )
                    
                    if entry_result['status'] == 'success':
                        print(f"✅ Entry Order Placed: {entry_result['order_id']}")
                        # 2. Place GTT OCO for SL/TP
                        gtt_result = self.kite_client.place_gtt_oco(
                            tradingsymbol=tradingsymbol,
                            exchange="NFO",
                            transaction_type="BUY", # Entry was BUY, so GTT handles exit (SELL) internally
                            quantity=quantity,
                            product_type="MIS",
                            price=option_ltp, # Current price for reference
                            stop_loss_price=stop_loss_price,
                            target_price=take_profit_price
                        )
                        if gtt_result['status'] == 'success':
                            print(f"✅ GTT OCO Placed: {gtt_result['trigger_id']}")
                            result = {"status": True, "message": "Real Trade & GTT Placed", "data": entry_result}
                        else:
                            print(f"❌ GTT Failed: {gtt_result.get('message')}")
                            result = {"status": True, "message": "Entry Success but GTT Failed!", "data": entry_result} # Trade is open, but no SL!
                    else:
                        print(f"❌ Entry Failed: {entry_result.get('message')}")
                        result = {"status": False, "message": f"Entry Failed: {entry_result.get('message')}"}
                else:
                    result = {"status": False, "message": "Kite Client not initialized for Real Trading."}
            
            # --- NEW: Increment trade count on success ---
            if result.get('status'):
                self.today_trades_count += 1
                
            return result
            
        except Exception as e:
            return {"status": False, "message": f"Strategy execution failed: {e}"}

    def execute_manual_test_trade(self, signal_type: str) -> Dict[str, Any]:
        print(f"--- Received Manual Test Signal: {signal_type} ---")
        
        # --- MODIFIED: Added new checks ---
        now_time = datetime.now(IST).time()
        if not (self.trade_start_time <= now_time <= self.trade_end_time):
             return {"status": False, "message": f"Cannot open manual trades outside of window ({self.trade_start_time} - {self.trade_end_time})."}
        if self.today_trades_count >= self.max_trades_per_day:
            return {"status": False, "message": f"Max trades per day ({self.max_trades_per_day}) already hit."}
        # --- END MODIFIED ---

        if len(self.positions_map) > 0:
            return {"status": False, "message": "Bot is already in a position."}
        if self.skip_today: 
            return {"status": False, "message": "SKIPPED: Lot cost was < ₹10k earlier today."}
        if self.daily_pnl <= -abs(self.max_daily_loss): 
            return {"status": False, "message": f"STOPPED: Max daily loss of ₹{self.max_daily_loss} was hit."}
        if now_time >= dt_time(15, 19):
            return {"status": False, "message": "Cannot open manual trades after 3:19 PM."}
            
        try:
            spot_price = self.get_index_ltp()
            historical_data = self.get_multi_timeframe_data()
            active_strategy = self.strategies[self.active_strategy_name]
            hist_df = active_strategy.calculate_indicators(historical_data, **active_strategy.parameters)
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
        now_ist = datetime.now(IST)
        auto_square_off_time = dt_time(15, 19)
        is_eod_square_off = now_ist.time() >= auto_square_off_time
        for symbol in open_symbols:
            try:
                pos = self.positions_map[symbol]; expiry = pos.get('expiry') 
                ltp = self.get_option_ltp(symbol, expiry_hint=expiry)
                sl_price = pos.get('stop_loss'); tp_price = pos.get('take_profit')
                sl_hit = ltp <= sl_price; tp_hit = ltp >= tp_price
                if sl_hit or tp_hit or is_eod_square_off:
                    reason = "STOP_LOSS" if sl_hit else ("TAKE_PROFIT" if tp_hit else "EOD_SQUARE_OFF")
                    print(f"🔥 {reason} HIT for {symbol} at LTP {ltp} (SL: {sl_price}, TP: {tp_price})")
                    result = self.place_order(tradingsymbol=symbol, transaction_type="SELL", quantity=pos['qty'], price=ltp, is_exit=True)
                    if (sl_hit or (is_eod_square_off and (ltp < pos['avg_price']))) and self.daily_pnl <= -abs(self.max_daily_loss):
                        print(f"--- MAX DAILY LOSS (₹{self.max_daily_loss}) HIT. STOPPING TRADING FOR THE DAY. ---")
            except Exception as e:
                print(f"❌ Error checking position {symbol} (Market may be closed): {e}")

    def close_all_live_positions(self) -> Dict[str, Any]:
        # ... (no change) ...
        print("--- MANUAL: Received request to CLOSE ALL POSITIONS ---")
        results = []; total_pnl = 0
        symbols_to_close = list(self.positions_map.keys()) 
        if not symbols_to_close:
            return {"status": "info", "message": "No open positions to close."}
        for symbol in symbols_to_close:
            try:
                pos = self.positions_map.get(symbol)
                if not pos: continue 
                expiry_hint = pos.get('expiry'); quantity = pos.get('qty')
                ltp = self.get_option_ltp(symbol, expiry_hint=expiry_hint)
                result = self.place_order(tradingsymbol=symbol, transaction_type="SELL", quantity=quantity, price=ltp, is_exit=True)
                if result.get('status'):
                    print(f"✅ Manually closed {symbol}")
                    if result.get('trade_pnl') is not None: total_pnl += result['trade_pnl']
                    results.append(result)
                else:
                    print(f"❌ Failed to manually close {symbol}: {result.get('message')}"); results.append(result)
            except Exception as e:
                print(f"❌ CRITICAL ERROR closing {symbol}: {e}"); results.append({"status": False, "message": f"Error closing {symbol}: {e}"})
        return {"status": "success", "message": f"Closed {len(symbols_to_close)} position(s).", "total_pnl": total_pnl, "results": results}

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
            # REAL TRADING
            if self.kite_client:
                return self.kite_client.place_order(
                    tradingsymbol=tradingsymbol,
                    exchange="NFO",
                    transaction_type=transaction_type,
                    quantity=quantity,
                    product_type="MIS",
                    price=price
                )
            else:
                print("--- REAL TRADING IS NOT IMPLEMENTED OR KITE CLIENT MISSING ---")
                return {"status": False, "message": "Real trading logic is not implemented or Kite Client missing."}

    def get_positions(self) -> List[Dict[str, Any]]:
        if self.paper:
            positions = []
            for symbol, pos in self.positions_map.items():
                try:
                    current_price = self.get_option_ltp(symbol, expiry_hint=pos.get('expiry'))
                    unrealized_pnl = (current_price - pos["avg_price"]) * pos["qty"]
                    positions.append({"tradingsymbol": symbol, "qty": pos["qty"], "avg_price": round(pos["avg_price"], 2), "current_price": round(current_price, 2), "unrealized_pnl": round(unrealized_pnl, 2), "sl": pos.get('stop_loss'), "tp": pos.get('take_profit')})
                except: continue
            return positions
        else:
            # REAL TRADING
            if self.kite_client:
                try:
                    kite_pos = self.kite_client.get_positions()
                    # We focus on 'net' positions which show current open positions
                    net_positions = kite_pos.get('net', [])
                    mapped_positions = []
                    for p in net_positions:
                        if p['quantity'] != 0:
                            mapped_positions.append({
                                "tradingsymbol": p['tradingsymbol'],
                                "qty": p['quantity'],
                                "avg_price": p['average_price'],
                                "current_price": p['last_price'],
                                "unrealized_pnl": p['pnl'],
                                "sl": 0, # Not available directly from Kite positions
                                "tp": 0
                            })
                    return mapped_positions
                except Exception as e:
                    print(f"Error fetching Kite positions: {e}")
                    return []
            return []
    def get_trade_history(self) -> List[Dict[str, Any]]: return self.trade_history
    def get_daily_pnl(self) -> float: return self.daily_pnl
    def get_portfolio_value(self) -> Dict[str, float]:
        # ... (no change) ...
        positions = self.get_positions()
        total_investment = sum(pos['avg_price'] * abs(pos['qty']) for pos in positions)
        total_current = sum(pos['current_price'] * abs(pos['qty']) for pos in positions)
        total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)
        return {"total_investment": round(total_investment, 2), "total_current_value": round(total_current, 2), "total_unrealized_pnl": round(total_unrealized_pnl, 2), "daily_realized_pnl": round(self.daily_pnl, 2)}