import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

load_dotenv()

from fetcher.fyers_data import FyersDataManager

def test_auto_refresh():
    print("Testing Fyers Auto-Refresh Logic...")
    try:
        fyers = FyersDataManager()
        
        if not fyers.is_authenticated():
            print("❌ Initial authentication failed. Please login manually first.")
            return

        print("✅ Initially authenticated.")
        
        # 1. Delete Access Token (but keep Refresh Token)
        print("\n--- Simulating Token Expiry (Deleting Access Token) ---")
        if fyers.delete_token():
            print("✅ Access token deleted (Refresh token preserved).")
        else:
            print("❌ Failed to delete token.")
            return
            
        # 2. Trigger API Call (should auto-refresh)
        print("\n--- Triggering API Call (Get LTP) ---")
        # Note: delete_token sets self.fyers to None, so the next call will trigger 
        # the "if not self.is_authenticated()" block which calls refresh_access_token()
        
        ltp = fyers.get_ltp("NSE:NIFTYBANK-INDEX")
        
        if ltp > 0:
            print(f"✅ Auto-Refresh Successful! LTP fetched: {ltp}")
            print(f"New Access Token: {fyers.access_token[:10]}...")
        else:
            print("❌ Auto-Refresh Failed. LTP is 0.")

    except Exception as e:
        print(f"❌ Exception in test: {e}")

if __name__ == "__main__":
    test_auto_refresh()
