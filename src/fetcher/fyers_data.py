# Modified: src/fetcher/fyers_data.py
# - FIXED: Reverted symbols in FYERS_SYMBOL_MAP to include the
#   '-INDEX' suffix, which is the correct format for the history API.

import pandas as pd
from fyers_apiv3 import fyersModel
from datetime import datetime, timedelta
from typing import Dict, Optional
import os
import json

TOKEN_FILE = "fyers_token.json"

# --- THIS IS THE FIX ---
# The Fyers History API requires the '-INDEX' suffix for cash indices.
FYERS_SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX"
}
# --- END OF FIX ---

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
        print("Fyers model initialized with existing token.")

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
        """
        Creates a SessionModel for Fyers API v3.
        """
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
            print("[DEBUG] No session found, creating new SessionModel for token generation...")
            try:
                self.app_session = self._create_session_model()
            except Exception as e:
                print(f"[DEBUG] CRITICAL ERROR creating SessionModel in generate_and_save_token: {e}")
                return False
            
        try:
            print("[DEBUG] Setting auth_code to session...")
            self.app_session.set_token(auth_code)
            print("[DEBUG] Generating token...")
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

    def is_authenticated(self) -> bool:
        """Checks if the fyers model is initialized."""
        return self.fyers is not None

    def get_historical_data(self, index_name: str, start_date: datetime, end_date: datetime, 
                            interval: str = "5", is_backtest_log: bool = False) -> pd.DataFrame:
        if not self.is_authenticated():
            raise Exception("Fyers client is not authenticated. Please generate a token.")
            
        fyers_symbol = FYERS_SYMBOL_MAP.get(index_name)
        
        if not fyers_symbol:
            raise Exception(f"Invalid index name: {index_name}. Not found in FYERS_SYMBOL_MAP.")
            
        if is_backtest_log:
            print(f"Fetching Fyers data for {fyers_symbol} from {start_date} to {end_date}...") # This will now print the correct symbol
            
        all_data = []
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=90), end_date)
            
            data = {
                "symbol": fyers_symbol,
                "resolution": interval, 
                "date_format": "1", 
                "range_from": current_start.strftime("%Y-%m-%d"),
                "range_to": current_end.strftime("%Y-%m-%d"),
                "cont_flag": "1" 
            }

            try:
                response = self.fyers.history(data=data)
            except Exception as e:
                print(f"Fyers API error: {e}. Retrying once...")
                try:
                    response = self.fyers.history(data=data)
                except Exception as e2:
                    print(f"Fyers API error on retry: {e2}. Skipping this chunk.")
                    current_start = current_end + timedelta(days=1)
                    continue

            if response.get("s") == "ok" and response.get("candles"):
                all_data.extend(response["candles"])
            elif response.get("s") == "no_data":
                if is_backtest_log:
                    print(f"No data for {fyers_symbol} from {current_start} to {current_end}")
            else:
                print(f"Fyers API error: {response.get('message')}")
            
            current_start = current_end + timedelta(days=1)

        if not all_data:
            print("No data fetched. Returning empty DataFrame.")
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df["timestamp"] = df["timestamp"].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
        df.set_index("timestamp", inplace=True)
        
        df = df.between_time('09:15', '15:20')
        df.index = df.index.tz_localize(None)
        
        if is_backtest_log:
            print(f"✅ Fetched and filtered {len(df)} total Fyers candles.")
            
        return df

    def get_index_spot(self, index_name: str) -> float:
        if not self.is_authenticated():
            return 0.0
        
        fyers_symbol = FYERS_SYMBOL_MAP.get(index_name)
        data = {"symbols": fyers_symbol}
        
        try:
            response = self.fyers.quotes(data=data)
            if response.get("s") == "ok" and response.get("d"):
                return response["d"][0]["v"]["lp"]
            return 0.0
        except Exception as e:
            print(f"Error fetching spot: {e}")
            return 0.0