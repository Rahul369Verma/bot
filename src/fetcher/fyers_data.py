import pandas as pd
from fyers_apiv3 import fyersModel
from datetime import datetime, timedelta, time as dt_time, date
from typing import Dict, Optional
import os
import json
import time
import calendar

TOKEN_FILE = "fyers_token.json"

# Fyers symbol map for INDICES
FYERS_INDEX_SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX"
}

# Fyers symbol map for OPTIONS
FYERS_OPTION_SYMBOL_MAP = {
    "BANKNIFTY": "BANKNIFTY",
    "NIFTY 50": "NIFTY"
}

class FyersDataManager:
    """
    Centralized class for authenticating and fetching all
    historical data from the Fyers API.
    """
    
    def __init__(self):
        self.app_id = os.getenv("FYERS_APP_ID")
        self.secret_key = os.getenv("FYERS_SECRET_KEY")
        self.redirect_url = os.getenv("FYERS_REDIRECT_URL")
        
        if not self.app_id or not self.secret_key or not self.redirect_url:
            print("ERROR: Fyers config not found in .env file.")
            raise ValueError("FYERS_APP_ID, FYERS_SECRET_KEY, or FYERS_REDIRECT_URL not set in .env")
        
        self.app_session = None
        self.fyers = None
        
        # Cache for authentication status to avoid repeated API calls
        self._auth_cache = None
        self._auth_cache_time = 0
        self._auth_cache_ttl = 60  # Cache for 60 seconds
        
        self.access_token = self._load_token()
        if self.access_token:
            self._initialize_fyers_model()

    def _initialize_fyers_model(self):
        """Initializes the fyersModel with a valid token."""
        self.fyers = fyersModel.FyersModel(
            client_id=self.app_id, 
            token=self.access_token,
            log_path=os.path.join(os.getcwd(), "logs")
        )
        
        # Validate token immediately upon init
        if not self.is_authenticated():
            print("⚠️ Initial token validation failed (Expired or Invalid). Clearing token file.")
            self.fyers = None
            self.access_token = None
            if os.path.exists(TOKEN_FILE):
                try:
                    os.remove(TOKEN_FILE)
                    print(f"Deleted invalid token file: {TOKEN_FILE}")
                except Exception as e:
                    print(f"Error deleting token file: {e}")
        else:
            print("✅ Fyers model initialized and validated with existing token.")

    def _load_token(self) -> Optional[str]:
        """Loads the access token from the JSON file."""
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    token_data = json.load(f)
                    print("Loaded existing token from fyers_token.json")
                    return token_data.get('access_token')
            except Exception as e:
                print(f"Error loading token file: {e}")
                return None
        print("No existing token file found.")
        return None

    def _create_session_model(self):
        """Creates a SessionModel for Fyers API v3."""
        print("[DEBUG] Attempting to create SessionModel with 'client_id'...")
        return fyersModel.SessionModel(
            client_id=self.app_id, 
            secret_key=self.secret_key,
            redirect_uri=self.redirect_url,
            response_type="code",
            grant_type="authorization_code"
        )

    def get_login_url(self) -> str:
        """Generates the URL for the user to log in."""
        try:
            self.app_session = self._create_session_model()
            url = self.app_session.generate_authcode()
            print(f"[DEBUG] Successfully generated login URL: {url[:50]}...")
            return url
        except Exception as e:
            print(f"[DEBUG] CRITICAL ERROR in get_login_url: {e}")
            raise e

    def generate_and_save_token(self, auth_code: str) -> bool:
        """
        Takes the auth_code from the redirect, generates the
        access_token, and saves it to a file.
        """
        print(f"[DEBUG] Received auth_code: {auth_code[:10]}...")
        if not self.app_session:
            print("[DEBUG] No session found, creating new SessionModel...")
            try:
                self.app_session = self._create_session_model()
            except Exception as e:
                print(f"[DEBUG] CRITICAL ERROR creating SessionModel: {e}")
                return False
            
        try:
            self.app_session.set_token(auth_code)
            response = self.app_session.generate_token()
            print(f"[DEBUG] Token generation response: {response}")
            
            if response.get("access_token"):
                self.access_token = response["access_token"]
                with open(TOKEN_FILE, 'w') as f:
                    json.dump(response, f)
                self._initialize_fyers_model()
                print("Access token generated and saved successfully.")
                return True
            else:
                print(f"Failed to generate token: {response.get('message')}")
                return False
        except Exception as e:
            print(f"Exception during token generation: {e}")
            return False

    def is_authenticated(self, use_cache: bool = True) -> bool:
        """
        Checks if the fyers model is initialized AND validates the token 
        by making a lightweight API call (get_profile).
        
        Args:
            use_cache: If True, uses cached result if available and not expired.
                      If False, always makes a fresh API call.
        """
        if self.fyers is None:
            return False
        
        # Check cache first if enabled
        if use_cache:
            current_time = time.time()
            if self._auth_cache is not None and (current_time - self._auth_cache_time) < self._auth_cache_ttl:
                return self._auth_cache
        
        # Make API call to validate
        try:
            response = self.fyers.get_profile()
            if response.get("s") == "ok" or response.get("code") == 200:
                self._auth_cache = True
                self._auth_cache_time = time.time()
                return True
            else:
                print(f"Token validation failed. API Response: {response}")
                self._auth_cache = False
                self._auth_cache_time = time.time()
                return False
        except Exception as e:
            print(f"Token validation exception (Network/API error): {e}")
            self._auth_cache = False
            self._auth_cache_time = time.time()
            return False

    def reload_token(self) -> bool:
        """
        Reloads the access token from the token file and reinitializes the Fyers model.
        This allows updating the token without restarting the application.
        Returns True if token was successfully reloaded and validated, False otherwise.
        """
        print("🔄 Reloading token from file...")
        new_token = self._load_token()
        
        if not new_token:
            print("❌ No token found in file.")
            self.access_token = None
            self.fyers = None
            self._auth_cache = None  # Invalidate cache
            return False
        
        # Update the token
        self.access_token = new_token
        
        # Invalidate auth cache since we're loading a new token
        self._auth_cache = None
        self._auth_cache_time = 0
        
        # Reinitialize the Fyers model with the new token
        self._initialize_fyers_model()
        
        # Validate the new token (bypass cache for fresh validation)
        if self.is_authenticated(use_cache=False):
            print("✅ Token reloaded and validated successfully!")
            return True
        else:
            print("❌ Token reload failed - token is invalid or expired.")
            return False

    def get_historical_index_data(self, index_name: str, start_date: datetime, end_date: datetime, 
                                  interval: str = "1", is_backtest_log: bool = False) -> pd.DataFrame:
        """Fetches historical data for an INDEX."""
        if not self.is_authenticated():
            raise Exception("Fyers client is not authenticated.")
            
        fyers_symbol = FYERS_INDEX_SYMBOL_MAP.get(index_name)
        if not fyers_symbol:
            raise Exception(f"Invalid index name: {index_name}.")
            
        if is_backtest_log:
            print(f"Fetching Fyers data for {fyers_symbol} from {start_date} to {end_date}...")
        
        all_data = []
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=90), end_date)
            data = {
                "symbol": fyers_symbol,
                "resolution": interval, "date_format": "1", 
                "range_from": current_start.strftime("%Y-%m-%d"),
                "range_to": current_end.strftime("%Y-%m-%d"),
                "cont_flag": "1" 
            }
            try:
                response = self.fyers.history(data=data)
            except Exception as e:
                print(f"Fyers API error (Index): {e}. Retrying once...")
                time.sleep(1) # Wait 1 sec before retry
                try:
                    response = self.fyers.history(data=data)
                except Exception as e2:
                    print(f"Fyers API error on retry (Index): {e2}. Skipping chunk.")
                    current_start = current_end + timedelta(days=1)
                    continue
            
            if response.get("s") == "ok" and response.get("candles"):
                all_data.extend(response["candles"])
            elif response.get("s") == "no_data":
                if is_backtest_log:
                    print(f"No index data for {fyers_symbol} from {current_start} to {current_end}")
            else:
                print(f"Fyers API error (Index): {response.get('message')}")
            
            current_start = current_end + timedelta(days=1)

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df["timestamp"] = df["timestamp"].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
        df.set_index("timestamp", inplace=True)
        df = df.between_time('09:15', '15:20')
        df.index = df.index.tz_localize(None)
        
        if is_backtest_log:
            print(f"✅ Fetched and filtered {len(df)} total Index candles.")
        return df

    # --- HELPER FUNCTIONS ---
    def _get_last_wednesday_of_month(self, year: int, month: int) -> date:
        """Finds the last Wednesday of a given month and year."""
        last_day = calendar.monthrange(year, month)[1]
        last_day_date = date(year, month, last_day)
        last_day_weekday = last_day_date.weekday()
        days_to_subtract = (last_day_weekday - 2 + 7) % 7
        return last_day_date - timedelta(days=days_to_subtract)
    
    def _get_monthly_contract_symbol(self, underlying: str, expiry_date: date, strike: int, opt_type: str) -> str:
        """Generates NEW format monthly symbol: {UNDERLYING}{YY}{MMM}{STRIKE}{TYPE}"""
        yy = expiry_date.strftime('%y')
        m = expiry_date.strftime('%b').upper() # e.g., NOV
        return f"NSE:{underlying}{yy}{m}{strike}{opt_type}"

    def _get_weekly_contract_symbol(self, underlying: str, expiry_date: date, strike: int, opt_type: str) -> str:
        """Generates OLD format weekly symbol: {UNDERLYING}{YY}{M}{DD}{STRIKE}{TYPE}"""
        yy = expiry_date.strftime('%y')
        # Map for old single-char month codes
        month_map = {1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6',
                     7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'}
        m = month_map[expiry_date.month]
        dd = expiry_date.strftime('%d')
        
        # For BANKNIFTY specifically, older symbols used "BANKNIFTY" or "NIFTYBANK"?
        # Based on your working example "NSE:BANKNIFTY20NOV25000PE", it seems underlying was consistent.
        return f"NSE:{underlying}{yy}{m}{dd}{strike}{opt_type}"

    def get_historical_option_data(self, index_name: str, trade_date: datetime, 
                                   strike: int, opt_type: str, interval: str = "1") -> pd.DataFrame:
        """
        Fetches historical data for a specific OPTION contract for a SINGLE DAY.
        Handles the transition from Weekly to Monthly contracts after Nov 13, 2024.
        """
        if not self.is_authenticated():
            raise Exception("Fyers client is not authenticated.")

        underlying = FYERS_OPTION_SYMBOL_MAP.get(index_name)
        if not underlying:
            raise Exception(f"Invalid option index name: {index_name}")
        
        discontinuation_date = date(2024, 11, 14)
        trade_date_only = trade_date
        fyers_symbol = ""
        
        if trade_date_only < discontinuation_date:
            # --- OLD LOGIC (Weekly Expiry) ---
            # Expiry was on WEDNESDAY (weekday 2) usually, sometimes Thursday
            # For simplicity, let's assume Wednesday (weekday 2) as standard for BankNifty recent history
            days_to_expiry = (2 - trade_date_only.weekday() + 7) % 7
            expiry_date = trade_date_only + timedelta(days=days_to_expiry)
            
            if expiry_date == trade_date_only:
                 expiry_date = trade_date_only + timedelta(days=7)
                 
            fyers_symbol = self._get_weekly_contract_symbol(underlying, expiry_date, strike, opt_type)
        
        else:
            # --- NEW LOGIC (Monthly Expiry ONLY) ---
            expiry_date = self._get_last_wednesday_of_month(trade_date_only.year, trade_date_only.month)
            
            if trade_date_only > expiry_date:
                # Get next month's expiry
                next_month_date = trade_date_only.replace(day=28) + timedelta(days=4)
                expiry_date = self._get_last_wednesday_of_month(next_month_date.year, next_month_date.month)
                
            fyers_symbol = self._get_monthly_contract_symbol(underlying, expiry_date, strike, opt_type)
        
        # --- Fetch Data ---
        data = {
            "symbol": fyers_symbol,
            "resolution": interval, "date_format": "1", 
            "range_from": trade_date_only.strftime("%Y-%m-%d"),
            "range_to": trade_date_only.strftime("%Y-%m-%d"),
            "cont_flag": "1" 
        }
        
        try:
            response = self.fyers.history(data=data)
            
            if response.get("s") == "ok" and response.get("candles"):
                df = pd.DataFrame(response["candles"])
                df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
                df["timestamp"] = df["timestamp"].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
                df.set_index("timestamp", inplace=True)
                df = df.between_time('09:15', '15:20')
                df.index = df.index.tz_localize(None)
                return df
            else:
                print(f"No option data for {fyers_symbol} on {trade_date_only}: {response.get('message')}")
                return pd.DataFrame()
        except Exception as e:
            print(f"Fyers API error (Option): {e}")
            return pd.DataFrame()

    def get_index_spot(self, index_name: str) -> float:
        if not self.is_authenticated():
            return 0.0
        
        fyers_symbol = FYERS_INDEX_SYMBOL_MAP.get(index_name)
        data = {"symbols": fyers_symbol}
        
        try:
            response = self.fyers.quotes(data=data)
            if response.get("s") == "ok" and response.get("d"):
                return response["d"][0]["v"]["lp"]
            return 0.0
        except Exception as e:
            print(f"Error fetching spot: {e}")
            return 0.0