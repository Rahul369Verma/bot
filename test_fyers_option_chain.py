import sys
import os
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from fetcher.fyers_data import FyersDataManager
from fetcher.real_market_data import RealMarketData

def test_option_chain():
    print("🚀 Initializing FyersDataManager...")
    fyers = FyersDataManager()
    if not fyers.is_authenticated():
        print("❌ Fyers not authenticated. Please login via the app first.")
        return

    print("✅ Fyers Authenticated.")
    
    print("🚀 Initializing RealMarketData...")
    rmd = RealMarketData(fyers_manager=fyers)
    
    symbol = "BANKNIFTY"
    print(f"🔍 Fetching Spot Price for {symbol}...")
    spot = rmd.get_index_spot(symbol)
    print(f"✅ Spot Price: {spot}")
    
    print("🔍 Fetching Expiry Dates...")
    expiries = rmd.get_expiry_dates(symbol)
    print(f"✅ Expiries: {expiries[:3]}...")
    
    if not expiries:
        print("❌ No expiries found.")
        return

    selected_expiry = expiries[0]
    print(f"🔍 Fetching Option Chain for {selected_expiry}...")
    
    try:
        chain = rmd.get_banknifty_option_chain(symbol, selected_expiry)
        print(f"✅ Fetched {len(chain)} options.")
        
        if chain:
            print("\nSample Data (First 3):")
            for item in chain[:3]:
                print(item)
                
            print("\nSample Data (ATM):")
            # Find ATM
            atm_strike = round(spot / 100) * 100
            atm_opts = [x for x in chain if x['strike'] == atm_strike]
            for item in atm_opts:
                print(item)
                
    except Exception as e:
        print(f"❌ Failed to fetch chain: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_option_chain()
