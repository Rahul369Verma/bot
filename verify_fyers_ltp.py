import sys
import os
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.abspath("src"))

# Mock dependencies
sys.modules["pyotp"] = MagicMock()
sys.modules["SmartApi"] = MagicMock()
sys.modules["fyers_apiv3"] = MagicMock()
sys.modules["kiteconnect"] = MagicMock()
sys.modules["streamlit"] = MagicMock()
sys.modules["streamlit_autorefresh"] = MagicMock()
sys.modules["ui"] = MagicMock()
sys.modules["ui.ui_utils"] = MagicMock()
sys.modules["pandas"] = MagicMock()

# Mock os.getenv BEFORE importing FyersDataManager
original_getenv = os.getenv
def mock_getenv(key, default=None):
    if key in ["FYERS_APP_ID", "FYERS_SECRET_KEY", "FYERS_REDIRECT_URL"]:
        return "dummy_value"
    return original_getenv(key, default)

os.getenv = mock_getenv

from fetcher.angel_client import AngelClient
from fetcher.fyers_data import FyersDataManager

def test_fyers_ltp():
    print("--- Testing Fyers LTP Fetching ---")
    
    # 1. Test FyersDataManager.get_ltp directly
    print("\n1. Testing FyersDataManager.get_ltp...")
    fyers_manager = FyersDataManager()
    fyers_manager.is_authenticated = MagicMock(return_value=True)
    fyers_manager.fyers = MagicMock()
    
    # Mock Fyers quotes response
    mock_response = {
        "s": "ok",
        "d": [{"v": {"lp": 123.45}}]
    }
    fyers_manager.fyers.quotes.return_value = mock_response
    
    ltp = fyers_manager.get_ltp("NSE:BANKNIFTY25NOV12345CE")
    if ltp == 123.45:
        print("✅ Success: FyersDataManager fetched correct LTP.")
    else:
        print(f"❌ Failed: Expected 123.45, got {ltp}")
        
    # 2. Test AngelClient.get_option_ltp
    print("\n2. Testing AngelClient.get_option_ltp...")
    client = AngelClient(paper=True, fyers_manager=fyers_manager)
    
    # Ensure Kite client is NOT used (mock it as None or paper=True)
    client.kite_client = None 
    
    ltp = client.get_option_ltp("BANKNIFTY25NOV12345CE", "")
    if ltp == 123.45:
        print("✅ Success: AngelClient used Fyers for LTP.")
    else:
        print(f"❌ Failed: AngelClient returned {ltp}")

if __name__ == "__main__":
    try:
        test_fyers_ltp()
    except Exception as e:
        print(f"❌ Test Crashed: {e}")
