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

# Imports moved to __init__ to avoid circular dependency

IST = ZoneInfo('Asia/Kolkata')

class AngelClient:
    """
    Complete Angel Client with automated signal generation
    and REALISTIC intraday trading rules.
    """
    def __init__(self, api_key=None, paper=True, index_name="BANKNIFTY", fyers_manager=None, kite_client=None):
        # --- Imports to avoid circular dependency ---
        from .real_market_data import RealMarketData
        from .signal_storage import SignalStorage
        from backtest.yfinance_data import YFinanceData
        from utils.constants import LOT_SIZE_MAP
        from backtest.backtest import MultiTimeframeStrategy
        from .fyers_socket import FyersSocketManager # --- NEW ---
        from utils.telegram_bot import TelegramBot # --- NEW ---

        self.paper = paper
        self.api_key = api_key or os.getenv("ANGEL_API_KEY")
        self.client_code = os.getenv("ANGEL_CLIENT_CODE")
        
        self.index_name = index_name
        self.yfinance_ticker = YFinanceData.INDEX_TICKERS.get(index_name, "^NSEBANK")
        print(f"AngelClient initializing for: {self.index_name} ({self.yfinance_ticker})")
        
        self.fyers_manager = fyers_manager # Use Fyers for Index Data AND Execution
        self.market_data = RealMarketData(self.fyers_manager)
        self.kite_client = kite_client # Optional: Keep for reference or specific data if needed, but primary is Fyers

        self.signal_storage = SignalStorage()
        self.telegram_bot = TelegramBot() # Initialize Telegram Bot
        
        # --- NEW: Socket Manager ---
        self.socket_manager = None
        if self.fyers_manager and self.fyers_manager.access_token:
            self.socket_manager = FyersSocketManager(self.fyers_manager.access_token)
            # Subscribe to Index immediately
            index_symbol = self.fyers_manager.FYERS_INDEX_SYMBOL_MAP.get(self.index_name)
            if index_symbol:
                self.socket_manager.subscribe([index_symbol])
            
            # Start Fast Monitor Thread
            self.fast_monitor_thread = threading.Thread(target=self.start_fast_monitor, daemon=True)
            self.fast_monitor_thread.start()
        
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
        # Dynamic Lot Size
        self.lot_size = LOT_SIZE_MAP.get(self.index_name, 1) # Default to 1 if not found
        print(f"AngelClient: Lot Size set to {self.lot_size} for {self.index_name}")
        
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
        self.last_signal_timestamp = None # Initialize here too
        self.last_signal_check_time = None # Track when we last checked for signals
        
        # --- NEW: Sync Open Positions (Enforce Single Trade Limit) ---
        self.sync_positions()

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
    def sync_positions(self):
        """
        Fetches open positions from Fyers (if Real Trading) on startup.
        Populates positions_map to ensure we don't open new trades if one exists.
        """
        if self.paper: return
        
        if self.fyers_manager:
            try:
                print("🔄 Syncing open positions from Fyers...")
                fyers_pos = self.fyers_manager.get_positions()
                net_positions = fyers_pos.get('netPositions', [])
                
                found_open = False
                for p in net_positions:
                    qty = p.get('netQty', 0)
                    if qty != 0:
                        symbol = p.get('symbol')
                        print(f"⚠️ Found EXISTING Open Position: {symbol} (Qty: {qty})")
                        
                        # Add to positions_map to BLOCK new trades
                        # We don't know original SL/TP, so we set them to safe values to prevent auto-close
                        # unless EOD or manual.
                        self.positions_map[symbol] = {
                            "qty": qty,
                            "avg_price": p.get('avgPrice', 0),
                            "stop_loss": 0,       # 0 SL means it won't trigger (unless price goes to 0)
                            "take_profit": 999999, # High TP means it won't trigger
                            "expiry": "",         # Unknown expiry
                            "entry_time": datetime.now(IST), # Unknown entry time
                            "is_existing": True   # Flag to indicate this was synced
                        }
                        found_open = True
                        
                        # Subscribe to socket for this symbol
                        if self.socket_manager:
                            self.socket_manager.subscribe([symbol])
                
                if found_open:
                    print("🚫 New trades are BLOCKED because an open position exists.")
                else:
                    print("✅ No existing open positions found.")
                    
            except Exception as e:
                print(f"❌ Failed to sync positions: {e}")

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
            # Get params from active strategy FIRST
            params = self.strategies[self.active_strategy_name].parameters
            
            end_date = datetime.now(IST)
            start_date = end_date - timedelta(days=5) # Fetch last 5 days
            
            # 1. Fetch Base Data (5m)
            df_5m = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "5")
            if df_5m is None or df_5m.empty: return pd.DataFrame()
            
            # 2. Fetch 15m Data
            df_15m = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "15")
            
            # 3. Fetch 1h Data (Optional)
            use_1h = params.get('use_1h_filter', True)
            df_1h = None
            if use_1h:
                df_1h = self.fyers_manager.get_historical_index_data(self.index_name, start_date, end_date, "60")
            
            # 4. Calculate Indicators on Higher Timeframes BEFORE merging
            # params already fetched above
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
            if df_15m is not None and not df_15m.empty and 'ema_short_15m' in df_15m.columns:
                df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], left_on='15m_timestamp', right_index=True, how='left')
            
            # Fix for 1h candles starting at 09:15
            if df_1h is not None and not df_1h.empty and 'ema_short_1h' in df_1h.columns:
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
        Prioritizes WebSocket cache for real-time updates.
        """
        if not self.fyers_manager:
            return 0.0
            
        # 1. Try Socket First
        if self.socket_manager:
            index_symbol = self.fyers_manager.FYERS_INDEX_SYMBOL_MAP.get(self.index_name)
            if index_symbol:
                socket_ltp = self.socket_manager.get_ltp(index_symbol)
                if socket_ltp:
                    return socket_ltp
        
        # 2. Fallback to API (with 5s Cache to prevent spam)
        # Check cache
        current_time = time.time()
        if hasattr(self, '_index_ltp_cache'):
            if current_time - self._index_ltp_cache['timestamp'] < 5:
                return self._index_ltp_cache['price']
        
        # Fetch from API
        price = self.fyers_manager.get_index_spot(self.index_name)
        
        # Update Cache
        self._index_ltp_cache = {'timestamp': current_time, 'price': price}
        
        return price

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
        # --- MODIFIED: Use Fyers for LTP (Kite Free Account Fix) ---
        if self.fyers_manager:
            try:
                # 1. Try Socket First
                if self.socket_manager:
                    socket_ltp = self.socket_manager.get_ltp(tradingsymbol)
                    if socket_ltp:
                        return socket_ltp
                
                # 2. Fallback to API
                ltp = self.fyers_manager.get_ltp(tradingsymbol)
                if ltp > 0:
                    return ltp
            except Exception as e:
                print(f"⚠️ Fyers LTP fetch failed for {tradingsymbol}: {e}")
        
        # Fallback to Kite if Fyers fails (or not init) - though likely to fail if permission issue
        if self.kite_client and not self.kite_client.paper:
            try:
                quote = self.kite_client.get_quote(tradingsymbol, "NFO")
                if quote and 'last_price' in quote:
                    return float(quote['last_price'])
            except Exception as e:
                print(f"⚠️ Kite LTP fetch failed for {tradingsymbol}: {e}")
        
        # Fallback to NSE Scraper (RealMarketData)
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

    def start_fast_monitor(self):
        """
        Runs every 1 second to check SL/TP using WebSocket data.
        This provides "Scalping" speed exits.
        """
        print("🚀 Fast Monitor Thread Started (1s interval)")
        while True:
            try:
                time.sleep(1) # Check every second
                if self.positions_map:
                    self.check_and_close_positions(use_socket=True)
            except Exception as e:
                print(f"❌ Error in Fast Monitor: {e}")
                time.sleep(5)

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
                # REAL TRADING with Fyers
                if self.fyers_manager:
                    print(f"🚀 Placing REAL Order via Fyers for {tradingsymbol}...")
                    
                    # Fyers Order Dict
                    # 1 = Limit, 2 = Market, 3 = Stop, 4 = StopLimit
                    # Side: 1 = Buy, -1 = Sell
                    
                    # 1. Place Entry Order (Market)
                    entry_data = {
                        "symbol": tradingsymbol,
                        "qty": quantity,
                        "type": 2, # Market Order
                        "side": 1, # Buy
                        "productType": "INTRADAY", # MIS equivalent
                        "limitPrice": 0,
                        "stopPrice": 0,
                        "validity": "DAY",
                        "disclosedQty": 0,
                        "offlineOrder": False,
                    }
                    
                    entry_result = self.fyers_manager.place_order(entry_data)
                    
                    if entry_result.get("s") == "ok":
                        order_id = entry_result.get("id")
                        print(f"✅ Entry Order Placed: {order_id}")
                        
                        # 2. Place Stop Loss Order (Stop Limit or Stop Market)
                        # Fyers doesn't have GTT OCO in API v3 easily accessible like Kite's GTT.
                        # We will place a separate SL Limit Order.
                        # Note: For OCO-like behavior, we might need to manage it manually or use 'CO'/'BO' if supported.
                        # For now, placing a standard Stop Loss Market/Limit order.
                        
                        # SL Order (Sell)
                        sl_data = {
                            "symbol": tradingsymbol,
                            "qty": quantity,
                            "type": 3, # Stop Loss Market (or 4 for SL Limit) - Using SL Market for safety
                            "side": -1, # Sell
                            "productType": "INTRADAY",
                            "limitPrice": 0, # Market
                            "stopPrice": stop_loss_price,
                            "validity": "DAY",
                            "disclosedQty": 0,
                            "offlineOrder": False,
                        }
                        
                        # Target Order (Limit Sell)
                        tp_data = {
                            "symbol": tradingsymbol,
                            "qty": quantity,
                            "type": 1, # Limit
                            "side": -1, # Sell
                            "productType": "INTRADAY",
                            "limitPrice": take_profit_price,
                            "stopPrice": 0,
                            "validity": "DAY",
                            "disclosedQty": 0,
                            "offlineOrder": False,
                        }
                        
                        # Place SL
                        sl_result = self.fyers_manager.place_order(sl_data)
                        if sl_result.get("s") == "ok":
                             print(f"✅ SL Order Placed: {sl_result.get('id')}")
                        else:
                             print(f"❌ SL Order Failed: {sl_result.get('message')}")

                        # Place TP
                        tp_result = self.fyers_manager.place_order(tp_data)
                        if tp_result.get("s") == "ok":
                             print(f"✅ TP Order Placed: {tp_result.get('id')}")
                        else:
                             print(f"❌ TP Order Failed: {tp_result.get('message')}")
                             
                        # --- NEW: Track Real Position in Bot Memory ---
                        self.positions_map[tradingsymbol] = {
                            "qty": quantity, 
                            "avg_price": option_ltp, # Approximate until we fetch order book
                            "stop_loss": stop_loss_price, 
                            "take_profit": take_profit_price,
                            "expiry": expiry,
                            "entry_time": datetime.now(IST)
                        }
                             
                        result = {"status": True, "message": "Real Trade Placed (Entry + SL + TP)", "data": entry_result}
                        
                    else:
                        print(f"❌ Entry Failed: {entry_result.get('message')}")
                        result = {"status": False, "message": f"Entry Failed: {entry_result.get('message')}"}
                else:
                    result = {"status": False, "message": "Fyers Manager not initialized for Real Trading."}

            
            # --- NEW: Increment trade count on success ---
            if result.get('status'):
                self.today_trades_count += 1
                # --- NOTIFICATION ---
                if self.telegram_bot.enabled:
                    msg = f"🚀 *REAL TRADE EXECUTED*\n\nSymbol: `{tradingsymbol}`\nAction: BUY\nQty: {quantity}\nPrice: {option_ltp}\nSL: {stop_loss_price}\nTP: {take_profit_price}\nExpiry: {expiry}"
                    self.telegram_bot.send_message(msg)
                
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
        if now_time >= dt_time(15, 15):
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
    
    def check_and_close_positions(self, use_socket: bool = False):
        """
        Checks open positions for Stop Loss or Take Profit hits.
        Uses Socket Data if available (Fast), else API (Slow).
        """
        open_symbols = list(self.positions_map.keys())
        if not open_symbols: return

        now_ist = datetime.now(IST)
        auto_square_off_time = dt_time(15, 15)
        is_eod_square_off = now_ist.time() >= auto_square_off_time
        
        for symbol in open_symbols:
            try:
                pos = self.positions_map[symbol]
                expiry = pos.get('expiry')
                sl_price = pos.get('stop_loss')
                tp_price = pos.get('take_profit')
                entry_time = pos.get('entry_time')
                
                # --- NEW: Max Duration Check (Only in Slow Loop) ---
                if not use_socket:
                    active_strategy = self.strategies.get(self.active_strategy_name)
                    max_duration = 30 # Default
                    if active_strategy:
                        max_duration = active_strategy.parameters.get('max_trade_duration_minutes', 30)
                    
                    if entry_time:
                        duration_mins = (now_ist - entry_time).total_seconds() / 60
                        if duration_mins > max_duration:
                            print(f"⏰ Max Duration ({max_duration}m) Exceeded for {symbol}. Closing...")
                            self.place_order(tradingsymbol=symbol, transaction_type="SELL", quantity=pos['qty'], price=0, is_exit=True)
                            continue

                # --- PRICE CHECK ---
                current_ltp = 0.0
                source = "API"
                
                # 1. Try Socket First
                if self.socket_manager:
                    socket_ltp = self.socket_manager.get_ltp(symbol)
                    if socket_ltp:
                        current_ltp = socket_ltp
                        source = "SOCKET"
                
                # 2. Fallback to API (Only if not using socket-only mode or socket failed)
                if current_ltp == 0.0:
                    if use_socket: continue # Don't block fast thread with API calls
                    current_ltp = self.get_option_ltp(symbol, expiry_hint=expiry)
                
                if current_ltp == 0.0: continue

                triggered = False
                reason = ""
                exit_price = current_ltp
                
                sl_hit = current_ltp <= sl_price
                tp_hit = current_ltp >= tp_price
                
                if sl_hit:
                    triggered = True
                    reason = f"STOP_LOSS ({source})"
                elif tp_hit:
                    triggered = True
                    reason = f"TAKE_PROFIT ({source})"
                elif is_eod_square_off and not use_socket:
                    triggered = True
                    reason = "EOD_SQUARE_OFF"

                if triggered:
                    print(f"🔥 {reason} HIT for {symbol} at {current_ltp} (SL: {sl_price}, TP: {tp_price})")
                    # Unsubscribe from socket on exit
                    if self.socket_manager:
                        self.socket_manager.unsubscribe([symbol])
                        
                    result = self.place_order(tradingsymbol=symbol, transaction_type="SELL", quantity=pos['qty'], price=current_ltp, is_exit=True)
                    
                    # Check Max Daily Loss (Only in slow loop or if critical)
                    if not use_socket and (reason.startswith("STOP_LOSS") or (reason == "EOD_SQUARE_OFF" and current_ltp < pos['avg_price'])) and self.daily_pnl <= -abs(self.max_daily_loss):
                        print(f"--- MAX DAILY LOSS (₹{self.max_daily_loss}) HIT. STOPPING TRADING FOR THE DAY. ---")
                        
            except Exception as e:
                print(f"❌ Error checking position {symbol}: {e}")

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
                    
                    # --- NOTIFICATION ---
                    if self.telegram_bot.enabled:
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                        msg = f"{pnl_emoji} *PAPER TRADE EXIT*\n\nSymbol: `{tradingsymbol}`\nAction: SELL\nQty: {quantity}\nPrice: {price}\nPnL: ₹{pnl:.2f}"
                        self.telegram_bot.send_message(msg)

                    return {"status": True, "message": f"PAPER SELL {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": trade_record, "trade_pnl": pnl}
                else: 
                    self.positions_map[tradingsymbol] = {
                        "qty": quantity, "avg_price": price,
                        "stop_loss": stop_loss, "take_profit": take_profit,
                        "expiry": expiry,
                        "entry_time": datetime.now(IST) # Track entry time
                    }
                    order_record = {"timestamp": time.time(), "tradingsymbol": tradingsymbol, "transaction_type": "BUY", "quantity": quantity, "price": price, "status": order_status, "order_id": order_id}
                    self.orders.append(order_record)
                    
                    if self.socket_manager:
                        self.socket_manager.subscribe([tradingsymbol])
                        
                    # --- NOTIFICATION ---
                    if self.telegram_bot.enabled:
                        msg = f"📝 *PAPER TRADE ENTRY*\n\nSymbol: `{tradingsymbol}`\nAction: BUY\nQty: {quantity}\nPrice: {price}\nSL: {stop_loss}\nTP: {take_profit}"
                        self.telegram_bot.send_message(msg)

                    return {"status": True, "message": f"PAPER BUY {quantity} {tradingsymbol} @ {price}", "orderId": order_id, "data": order_record}
            except Exception as e:
                return {"status": False, "message": f"Paper order failed: {e}"}
        else:
            # REAL TRADING
            if self.fyers_manager:
                # Side: 1 = Buy, -1 = Sell
                side = 1 if transaction_type == "BUY" else -1
                
                data = {
                    "symbol": tradingsymbol if tradingsymbol.startswith("NSE:") else f"NSE:{tradingsymbol}",
                    "qty": quantity,
                    "type": 2, # Market
                    "side": side,
                    "productType": "INTRADAY",
                    "limitPrice": 0,
                    "stopPrice": 0,
                    "validity": "DAY",
                    "disclosedQty": 0,
                    "offlineOrder": False,
                }
                if price is not None:
                    data["type"] = 1 # Limit
                    data["limitPrice"] = price
                    
                return self.fyers_manager.place_order(data)
            else:
                print("--- REAL TRADING IS NOT IMPLEMENTED OR FYERS MANAGER MISSING ---")
                return {"status": False, "message": "Real trading logic is not implemented or Fyers Manager missing."}

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
            if self.fyers_manager:
                try:
                    fyers_pos = self.fyers_manager.get_positions()
                    # Fyers positions structure: {'s': 'ok', 'netPositions': [...], 'overall': {...}}
                    net_positions = fyers_pos.get('netPositions', [])
                    mapped_positions = []
                    for p in net_positions:
                        if p['netQty'] != 0:
                            current_price = p['ltp']
                            
                            # Override with Socket Price if available
                            if self.socket_manager:
                                socket_ltp = self.socket_manager.get_ltp(p['symbol'])
                                if socket_ltp:
                                    current_price = socket_ltp
                                    
                            mapped_positions.append({
                                "tradingsymbol": p['symbol'],
                                "qty": p['netQty'],
                                "avg_price": p['avgPrice'],
                                "current_price": current_price, # Updated with Socket
                                "unrealized_pnl": (current_price - p['avgPrice']) * p['netQty'], # Recalculate P&L
                                "sl": 0, 
                                "tp": 0
                            })
                    return mapped_positions
                except Exception as e:
                    print(f"Error fetching Fyers positions: {e}")
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