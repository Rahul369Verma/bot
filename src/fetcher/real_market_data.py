# Modified: src/fetcher/real_market_data.py
# Fixed import statement to be absolute from src

import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import time
import json

# --- MODIFIED: Fixed import to be absolute from src ---
try:
    from backtest.yfinance_data import YFinanceData
except ImportError:
    print("CRITICAL: real_market_data.py failed to import 'from backtest.yfinance_data import YFinanceData'")
    print("Make sure 'src' is in sys.path and yfinance_data.py is in 'src/backtest/'")
    # Re-raise to stop execution
    raise

class RealMarketData:
    """
    Fetches REAL market data.
    - YFinanceData for Spot/Historical Index data. (CHANGED)
    - Direct NSE API for Option Chain data.
    """
    def __init__(self, fyers_manager=None):
        self.fyers_manager = fyers_manager
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.nseindia.com/',
            'Origin': 'https://www.nseindia.com',
        })
        # self._setup_session() # NSE Session no longer needed immediately, but kept for fallback if needed
        
        self.hist_data_manager = YFinanceData()
        
    def _setup_session(self):
        # ... (no change) ...
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.session.get("https://www.nseindia.com/option-chain", timeout=30)
                print("✅ NSE session initialized.")
                return
            except Exception as e:
                print(f"⚠️ NSE session init attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        print("❌ Failed to initialize NSE session after multiple attempts.")

    def get_index_spot(self, index_name: str) -> float:
        # ... (no change) ...
        try:
            return self.hist_data_manager.get_index_spot(index_name)
        except Exception as e:
            raise Exception(f"Failed to fetch {index_name} spot: {e}")

    def get_index_historical(self, index_name: str, days: int = 7) -> pd.DataFrame:
        # ... (no change) ...
        try:
            data = self.hist_data_manager.get_historical_data(
                index_name=index_name, 
                period=f"{days}d", 
                interval="5m",
                is_backtest_log=False
            )
            if data.empty:
                raise Exception("No historical data available from YFinanceData")
            return data
        except Exception as e:
            raise Exception(f"Failed to fetch historical data via data_manager: {e}")

    def calculate_emas(self, data: pd.DataFrame) -> Dict[str, float]:
        # ... (no change) ...
        try:
            if data.empty or len(data) < 15:
                return {'ema_9': 0, 'ema_15': 0, 'current_price': 0}
            df_ema = data.copy()
            if df_ema.empty: 
                 return {'ema_9': 0, 'ema_15': 0, 'current_price': 0}
            df_ema['ema_9'] = df_ema['close'].ewm(span=9, adjust=False).mean()
            df_ema['ema_15'] = df_ema['close'].ewm(span=15, adjust=False).mean()
            return {
                'ema_9': float(df_ema['ema_9'].iloc[-1]),
                'ema_15': float(df_ema['ema_15'].iloc[-1]),
                'current_price': float(df_ema['close'].iloc[-1])
            }
        except Exception as e:
            if 'close' not in data.columns:
                 raise Exception(f"Failed to calculate EMAs: 'close' column missing. Columns are: {data.columns}")
            raise Exception(f"Failed to calculate EMAs: {e}")

    def _fetch_nse_option_data(self, symbol: str) -> Dict[str, Any]:
        # ... (no change) ...
        # Map "NIFTY 50" to "NIFTY" for NSE API
        is_index = False
        if symbol == "NIFTY 50": 
            symbol = "NIFTY"
            is_index = True
        elif symbol == "BANKNIFTY": 
            symbol = "BANKNIFTY"
            is_index = True
        elif symbol == "NIFTY": # Handle if passed directly
            is_index = True
        
        # --- NEW: Caching Logic ---
        # Check if we have a valid cached response (less than 60 seconds old)
        current_time = time.time()
        if hasattr(self, '_nse_cache') and symbol in self._nse_cache:
            cache_entry = self._nse_cache[symbol]
            if current_time - cache_entry['timestamp'] < 60:
                # print(f"Using cached NSE data for {symbol}")
                return cache_entry['data']
        
        # Construct URL based on type (Index vs Equity)
        if is_index:
            api_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        else:
            # For stocks, use the equities endpoint
            # Symbol needs to be URL encoded if it contains special chars, but NSE symbols usually don't
            api_url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"
            
        try:
            print(f"Fetching NSE Option Chain for {symbol} (Index={is_index})...")
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Update Cache
            if not hasattr(self, '_nse_cache'): self._nse_cache = {}
            self._nse_cache[symbol] = {'timestamp': current_time, 'data': data}
            
            return data
        except Exception as e:
            print(f"❌ Failed to fetch from NSE API for {symbol}: {e}")
            self._setup_session()
            try:
                response = self.session.get(api_url, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # Update Cache
                if not hasattr(self, '_nse_cache'): self._nse_cache = {}
                self._nse_cache[symbol] = {'timestamp': current_time, 'data': data}
                
                return data
            except Exception as e2:
                print(f"❌ Retry failed: {e2}")
                # Return cached data if available (even if expired) as fallback
                if hasattr(self, '_nse_cache') and symbol in self._nse_cache:
                    print("⚠️ Returning expired cache as fallback.")
                    return self._nse_cache[symbol]['data']
                raise e

    def _analyze_expiry_type(self, expiry_dates: List[str]) -> Dict[str, Any]:
        """
        Analyzes expiry dates to determine if they are weekly or monthly.
        Returns metadata about expiry pattern.
        """
        if len(expiry_dates) < 2:
            return {"type": "unknown", "dates": expiry_dates, "avg_gap_days": 0}
        
        # Parse dates and calculate gaps (check first 3 expiries)
        dates = [datetime.strptime(d, "%d-%b-%Y") for d in expiry_dates[:min(3, len(expiry_dates))]]
        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_gap = sum(gaps) / len(gaps)
        
        # Determine type based on average gap
        if avg_gap <= 10:  # Weekly expiries (~7 days)
            return {"type": "weekly", "dates": expiry_dates, "avg_gap_days": avg_gap}
        else:  # Monthly expiries (~28-35 days)
            return {"type": "monthly", "dates": expiry_dates, "avg_gap_days": avg_gap}
    
    def _filter_weekly_expiries(self, expiry_dates: List[str]) -> List[str]:
        """
        Filters weekly expiries from a list that may contain both weekly and monthly.
        Weekly expiries are typically ~7 days apart.
        """
        if len(expiry_dates) < 2:
            return expiry_dates
        
        weekly = [expiry_dates[0]]  # Always include first
        
        for i in range(1, len(expiry_dates)):
            prev_date = datetime.strptime(weekly[-1], "%d-%b-%Y")
            curr_date = datetime.strptime(expiry_dates[i], "%d-%b-%Y")
            gap = (curr_date - prev_date).days
            
            # If gap is ~7 days, it's weekly
            if 5 <= gap <= 10:
                weekly.append(expiry_dates[i])
        
        return weekly if len(weekly) > 1 else expiry_dates
    
    def get_expiry_dates(self, symbol: str) -> List[str]:
        """Get expiry dates with automatic weekly filtering for NIFTY"""
        try:
            data = self._fetch_nse_option_data(symbol)
            expirations = data.get('records', {}).get('expiryDates', [])
            if not expirations:
                raise Exception("No expiry dates found in NSE API response.")
            
            # Analyze expiry pattern
            expiry_info = self._analyze_expiry_type(expirations)
            
            # For NIFTY, prefer weekly expiries if available
            if symbol == "NIFTY":
                if expiry_info["type"] == "monthly" or expiry_info["avg_gap_days"] > 10:
                    # Try to filter weekly expiries from the list
                    weekly_expiries = self._filter_weekly_expiries(expirations)
                    if len(weekly_expiries) > 1:
                        print(f"✅ NIFTY: Filtered {len(weekly_expiries)} weekly expiries from {len(expirations)} total expiries")
                        return weekly_expiries
                else:
                    print(f"✅ NIFTY: Using weekly expiries (avg gap: {expiry_info['avg_gap_days']:.1f} days)")
            
            return expirations
        except Exception as e:
            print(f"Warning: Failed to fetch expiries from NSE ({e}). Generating fallback dates.")
            expirations = []
            today = datetime.now()
            days_ahead = (3 - today.weekday() + 7) % 7
            if days_ahead == 0: days_ahead = 7
            next_expiry = today + timedelta(days=days_ahead)
            for i in range(4):
                expirations.append((next_expiry + timedelta(days=7*i)).strftime("%d-%b-%Y"))
            return expirations

    def get_banknifty_option_chain(self, symbol: str, expiry_date: str) -> List[Dict[str, Any]]:
        """
        Fetches Option Chain using Fyers API (via FyersDataManager).
        Generates strikes around ATM and fetches quotes.
        """
        if not self.fyers_manager:
            print("⚠️ Fyers Manager not available in RealMarketData. Falling back to NSE Scraping (Deprecated).")
            return self._get_nse_option_chain_fallback(symbol, expiry_date)

        try:
            # 1. Get Spot Price
            spot_price = self.fyers_manager.get_index_spot(symbol)
            if spot_price == 0:
                raise Exception(f"Failed to fetch spot price for {symbol}")
            
            # 2. Calculate ATM Strike
            atm_strike = round(spot_price / 100) * 100
            
            # 3. Generate Strikes (ATM +/- 10)
            strikes = []
            for i in range(-10, 11):
                strikes.append(atm_strike + (i * 100))
                
            # 4. Generate Symbols
            # Parse expiry date
            expiry_dt = datetime.strptime(expiry_date, "%d-%b-%Y").date()
            
            # Determine if Weekly or Monthly logic needed
            fyers_symbols = []
            strike_map = {} # Map symbol -> (strike, type)
            
            underlying = "BANKNIFTY" if symbol == "BANKNIFTY" else "NIFTY"
            
            # --- IMPROVED MONTHLY CHECK ---
            # BankNifty expires on Last Tuesday (usually)
            # Nifty expires on Last Thursday (usually)
            # To be safe, we check if the date is in the last week of the month.
            # If (total_days_in_month - expiry_day) < 7, it is the last occurrence of that weekday.
            # And usually, the Monthly contract is the last expiry of the month.
            
            import calendar
            last_day_of_month = calendar.monthrange(expiry_dt.year, expiry_dt.month)[1]
            is_last_week = (last_day_of_month - expiry_dt.day) < 7
            
            # If it's the last week, we assume it's the Monthly contract.
            # Exception: If there's a holiday and expiry moves, it's still the "Monthly" contract.
            # Fyers uses 'MMM' (e.g. DEC) for Monthly, and 'M'+'DD' (e.g. D30) for Weekly.
            # However, Fyers treats the "Monthly" contract as the one expiring at the end of the month.
            
            is_monthly = is_last_week
            
            for strike in strikes:
                # CE
                if is_monthly:
                    ce_sym = self.fyers_manager._get_monthly_contract_symbol(underlying, expiry_dt, strike, "CE")
                    pe_sym = self.fyers_manager._get_monthly_contract_symbol(underlying, expiry_dt, strike, "PE")
                else:
                    ce_sym = self.fyers_manager._get_weekly_contract_symbol(underlying, expiry_dt, strike, "CE")
                    pe_sym = self.fyers_manager._get_weekly_contract_symbol(underlying, expiry_dt, strike, "PE")
                
                fyers_symbols.append(ce_sym)
                fyers_symbols.append(pe_sym)
                strike_map[ce_sym] = {"strike": strike, "type": "CE"}
                strike_map[pe_sym] = {"strike": strike, "type": "PE"}
                
            # 5. Fetch Quotes
            quotes = self.fyers_manager.get_quotes(fyers_symbols)
            
            # --- RETRY LOGIC FOR SYMBOL FORMAT ---
            # If quotes are empty (all 0), it might be that we guessed the format wrong.
            # E.g., maybe it IS the last week but Fyers treats it as Weekly (unlikely) or vice versa.
            # Or maybe we calculated 'is_monthly' wrong.
            # Let's check if we got valid data.
            
            valid_data_count = sum(1 for d in quotes.values() if d.get('lp', 0) > 0)
            
            if valid_data_count == 0 and len(quotes) > 0:
                print(f"⚠️ No data found for generated symbols (is_monthly={is_monthly}). Retrying with opposite format...")
                # Flip is_monthly and try again
                is_monthly = not is_monthly
                fyers_symbols = []
                strike_map = {}
                
                for strike in strikes:
                    if is_monthly:
                        ce_sym = self.fyers_manager._get_monthly_contract_symbol(underlying, expiry_dt, strike, "CE")
                        pe_sym = self.fyers_manager._get_monthly_contract_symbol(underlying, expiry_dt, strike, "PE")
                    else:
                        ce_sym = self.fyers_manager._get_weekly_contract_symbol(underlying, expiry_dt, strike, "CE")
                        pe_sym = self.fyers_manager._get_weekly_contract_symbol(underlying, expiry_dt, strike, "PE")
                    
                    fyers_symbols.append(ce_sym)
                    fyers_symbols.append(pe_sym)
                    strike_map[ce_sym] = {"strike": strike, "type": "CE"}
                    strike_map[pe_sym] = {"strike": strike, "type": "PE"}
                
                quotes = self.fyers_manager.get_quotes(fyers_symbols)
            
            # 6. Format Data
            option_chain = []
            for sym, data in quotes.items():
                meta = strike_map.get(sym)
                if not meta: continue
                
                option_chain.append({
                    "tradingsymbol": sym, # Use Fyers Symbol
                    "strike": float(meta['strike']),
                    "type": meta['type'],
                    "expiry": expiry_date,
                    "ltp": float(data.get('lp', 0)),
                    "oi": float(data.get('oi', 0)),
                    "volume": float(data.get('volume', 0)),
                    "iv": 0.0, # Fyers Quote might not have IV directly? 'cmd' might have it? 'lp' is LTP.
                    # Fyers Quote keys: 'lp'=LTP, 'oi'=OpenInterest, 'v'=Volume, 'bp'=Bid, 'ap'=Ask
                    # IV is not usually in standard quote. We might have to live without IV or calculate it?
                    # For now, set IV to 0.
                    "bid": float(data.get('bp', 0)),
                    "ask": float(data.get('ap', 0))
                })
                
            return option_chain

        except Exception as e:
            print(f"❌ Fyers Option Chain failed: {e}. Trying fallback...")
            return self._get_nse_option_chain_fallback(symbol, expiry_date)

    def _get_nse_option_chain_fallback(self, symbol: str, expiry_date: str) -> List[Dict[str, Any]]:
        """Original NSE Scraping Logic (Moved here as fallback)"""
        try:
            data = self._fetch_nse_option_data(symbol)
            option_chain = []
            for item in data.get('records', {}).get('data', []):
                if item['expiryDate'] != expiry_date:
                    continue
                expiry_dt = datetime.strptime(item['expiryDate'], "%d-%b-%Y")
                expiry_str = expiry_dt.strftime("%d%b%y").upper()
                if 'CE' in item:
                    ce = item['CE']
                    option_chain.append({
                        "tradingsymbol": f"{symbol}{expiry_str}{int(ce['strikePrice'])}CE",
                        "strike": float(ce['strikePrice']), "type": "CE", "expiry": ce['expiryDate'],
                        "ltp": float(ce.get('lastPrice', 0)), "oi": float(ce.get('openInterest', 0)),
                        "volume": float(ce.get('totalTradedVolume', 0)), "iv": float(ce.get('impliedVolatility', 0)),
                        "bid": float(ce.get('bidprice', 0)), "ask": float(ce.get('askPrice', 0))
                    })
                    pe = item['PE']
                    option_chain.append({
                        "tradingsymbol": f"{symbol}{expiry_str}{int(pe['strikePrice'])}PE",
                        "strike": float(pe['strikePrice']), "type": "PE", "expiry": pe['expiryDate'],
                        "ltp": float(pe.get('lastPrice', 0)), "oi": float(pe.get('openInterest', 0)),
                        "volume": float(pe.get('totalTradedVolume', 0)), "iv": float(pe.get('impliedVolatility', 0)),
                        "bid": float(pe.get('bidprice', 0)), "ask": float(pe.get('askPrice', 0))
                    })
            if not option_chain:
                raise Exception(f"No option data found for expiry {expiry_date}.")
            return option_chain
        except Exception as e:
            print(f"Fallback NSE failed: {e}")
            return []

    def get_candle_data(self, symbol: str = "^NSEBANK") -> Dict[str, Any]:
        # ... (no change) ...
        try:
            # Use the provided symbol (YFinance format)
            ticker = yf.Ticker(symbol); data_5min = ticker.history(period="2d", interval="5m"); data_15min = ticker.history(period="2d", interval="15m")
            if data_5min.empty or data_15min.empty: raise Exception("No candle data available from Yahoo Finance")
            five_min_candles = []
            for idx, row in data_5min.tail(24).iterrows():
                five_min_candles.append({'time': idx.to_pydatetime(), 'open': float(row['Open']), 'high': float(row['High']), 'low': float(row['Low']), 'close': float(row['Close']), 'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0})
            fifteen_min_candles = []
            for idx, row in data_15min.tail(16).iterrows():
                fifteen_min_candles.append({'time': idx.to_pydatetime(), 'open': float(row['Open']), 'high': float(row['High']), 'low': float(row['Low']), 'close': float(row['Close']), 'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0})
            return {'five_min': five_min_candles, 'fifteen_min': fifteen_min_candles}
        except Exception as e:
            raise Exception(f"Failed to fetch candle data: {e}")