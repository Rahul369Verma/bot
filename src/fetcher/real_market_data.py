import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import time
import json


class RealMarketData:
    """
    Fetches REAL market data.
    - yfinance for Spot/Historical Index data.
    - Direct NSE API for Option Chain data.
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.nseindia.com/',
            'Origin': 'https://www.nseindia.com',
        })
        self._setup_session()
        
    def _setup_session(self):
        """
        Sets up the session with NSE by fetching initial cookies.
        This is required to make API calls to NSE.
        """
        try:
            self.session.get("https://www.nseindia.com/option-chain", timeout=10)
            print("✅ NSE session initialized.")
        except Exception as e:
            print(f"❌ Failed to initialize NSE session: {e}")

    def get_banknifty_spot(self) -> float:
        """Get REAL BankNifty spot price from yfinance"""
        try:
            ticker = yf.Ticker("^NSEBANK")
            data = ticker.history(period="1d", interval="1m") # Try 1m first
            if not data.empty:
                return float(data['Close'].iloc[-1])
            
            # Fallback for market close: get last day's close
            data = ticker.history(period="5d", interval="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
                
            raise Exception("Yahoo Finance data unavailable")
        except Exception as e:
            raise Exception(f"Failed to fetch BankNifty spot: {e}")

    def get_banknifty_historical(self, days: int = 7) -> pd.DataFrame:
        """Get REAL BankNifty historical data for EMA calculation from yfinance"""
        try:
            ticker = yf.Ticker("^NSEBANK")
            data = ticker.history(period=f"{days}d", interval="5m")
            if data.empty:
                raise Exception("No historical data available from Yahoo Finance")
            return data
        except Exception as e:
            raise Exception(f"Failed to fetch historical data: {e}")

    def calculate_emas(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calculate REAL EMAs from historical data"""
        try:
            if data.empty or len(data) < 15:
                return {'ema_9': 0, 'ema_15': 0, 'current_price': 0}
                
            df_ema = data.copy()
            # --- FIX: Apply timezone logic before calculating ---
            if df_ema.index.tz is None:
                try: df_ema.index = df_ema.index.tz_localize('Asia/Kolkata') # yfinance data is naive but represents IST
                except Exception: pass # Already localized
            else:
                try: df_ema.index = df_ema.index.tz_convert('Asia/Kolkata')
                except Exception: pass # Already IST
            
            df_ema = df_ema.between_time('09:15', '15:30')
            df_ema.index = df_ema.index.tz_localize(None) # Make naive IST
            # --- END FIX ---
            
            if df_ema.empty: 
                 return {'ema_9': 0, 'ema_15': 0, 'current_price': 0}

            df_ema['ema_9'] = df_ema['Close'].ewm(span=9, adjust=False).mean()
            df_ema['ema_15'] = df_ema['Close'].ewm(span=15, adjust=False).mean()
                 
            return {
                'ema_9': float(df_ema['ema_9'].iloc[-1]),
                'ema_15': float(df_ema['ema_15'].iloc[-1]),
                'current_price': float(df_ema['Close'].iloc[-1])
            }
        except Exception as e:
            raise Exception(f"Failed to calculate EMAs: {e}")

    def _fetch_nse_option_data(self) -> Dict[str, Any]:
        """Fetches the full option chain JSON from the NSE API."""
        api_url = "https://www.nseindia.com/api/option-chain-indices?symbol=BANKNIFTY"
        try:
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status() # Raise error for 4xx/5xx status
            return response.json()
        except Exception as e:
            print(f"❌ Failed to fetch from NSE API: {e}")
            self._setup_session() # Re-init session
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()
            return response.json()

    def get_expiry_dates(self) -> List[str]:
        """Get expiry dates directly from NSE API."""
        try:
            data = self._fetch_nse_option_data()
            expirations = data.get('records', {}).get('expiryDates', [])
            if not expirations:
                raise Exception("No expiry dates found in NSE API response.")
            return expirations
            
        except Exception as e:
            # --- Fallback for when market is closed (Generates TUESDAYS) ---
            print(f"Warning: Failed to fetch expiries from yfinance ({e}). Generating fallback dates.")
            expirations = []
            today = datetime.now()
            # Find the next Tuesday (weekday 1)
            days_ahead = (1 - today.weekday() + 7) % 7
            if days_ahead == 0 and today.weekday() == 1:
                days_ahead = 7 # If today is Tue, get next Tue
            
            next_expiry = today + timedelta(days=days_ahead)
            
            # Add the next 4 expiries
            for i in range(4):
                # Format as dd-MMM-YYYY (e.g., 04-Nov-2025) to match NSE
                expirations.append((next_expiry + timedelta(days=7*i)).strftime("%d-%b-%Y"))
            
            return expirations

    def get_banknifty_option_chain(self, expiry_date: str) -> List[Dict[str, Any]]:
        """
        Get REAL BankNifty option chain for a SPECIFIC expiry from NSE API.
        """
        try:
            data = self._fetch_nse_option_data()
            option_chain = []
            
            for item in data.get('records', {}).get('data', []):
                # Filter for the specific expiry date
                if item['expiryDate'] != expiry_date:
                    continue
                
                # --- FIX: Create tradingsymbol in ddMMMyy format ---
                expiry_dt = datetime.strptime(item['expiryDate'], "%d-%b-%Y")
                expiry_str = expiry_dt.strftime("%d%b%y").upper() # e.g., 04NOV25
                
                # Process CALL options
                if 'CE' in item:
                    ce = item['CE']
                    option_chain.append({
                        "tradingsymbol": f"BANKNIFTY{expiry_str}{int(ce['strikePrice'])}CE",
                        "strike": float(ce['strikePrice']), "type": "CE", "expiry": ce['expiryDate'],
                        "ltp": float(ce.get('lastPrice', 0)), "oi": float(ce.get('openInterest', 0)),
                        "volume": float(ce.get('totalTradedVolume', 0)), "iv": float(ce.get('impliedVolatility', 0)),
                        "bid": float(ce.get('bidprice', 0)), "ask": float(ce.get('askPrice', 0))
                    })
                
                # Process PUT options
                if 'PE' in item:
                    pe = item['PE']
                    option_chain.append({
                        "tradingsymbol": f"BANKNIFTY{expiry_str}{int(pe['strikePrice'])}PE",
                        "strike": float(pe['strikePrice']), "type": "PE", "expiry": pe['expiryDate'],
                        "ltp": float(pe.get('lastPrice', 0)), "oi": float(pe.get('openInterest', 0)),
                        "volume": float(pe.get('totalTradedVolume', 0)), "iv": float(pe.get('impliedVolatility', 0)),
                        "bid": float(pe.get('bidprice', 0)), "ask": float(pe.get('askPrice', 0))
                    })
            
            if not option_chain:
                raise Exception(f"No option data found for expiry {expiry_date}.")
                
            return option_chain
            
        except Exception as e:
            raise Exception(f"Failed to parse NSE option chain: {e}")

    def get_candle_data(self) -> Dict[str, Any]:
        """Get REAL candle data with volume from yfinance"""
        try:
            ticker = yf.Ticker("^NSEBANK"); data_5min = ticker.history(period="2d", interval="5m"); data_15min = ticker.history(period="2d", interval="15m")
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