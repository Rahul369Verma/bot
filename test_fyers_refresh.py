import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

load_dotenv()

from fetcher.fyers_data import FyersDataManager

def test_refresh():
    print("Testing Fyers Token Refresh...")
    try:
        fyers = FyersDataManager()
        
        if not fyers.refresh_token:
            print("❌ No refresh token found. Please login manually first to generate one.")
            return

        print(f"Current Access Token (First 10 chars): {fyers.access_token[:10] if fyers.access_token else 'None'}")
        
        # Force refresh
        success = fyers.refresh_access_token()
        
        if success:
            print("✅ Refresh call returned True.")
            print(f"New Access Token (First 10 chars): {fyers.access_token[:10] if fyers.access_token else 'None'}")
            
            # Verify with a profile call
            if fyers.is_authenticated(use_cache=False):
                 print("✅ New token validated successfully via API.")
            else:
                 print("❌ New token validation failed.")
        else:
            print("❌ Refresh call failed.")
            
    except Exception as e:
        print(f"❌ Exception in test: {e}")

if __name__ == "__main__":
    test_refresh()
