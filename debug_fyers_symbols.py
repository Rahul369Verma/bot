import sys
import os
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv

load_dotenv()

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from fetcher.fyers_data import FyersDataManager

def debug_symbols():
    print("🚀 Initializing FyersDataManager...")
    fyers = FyersDataManager()
    if not fyers.is_authenticated():
        print("❌ Fyers not authenticated.")
        return

    print("✅ Fyers Authenticated.")
    
    # 1. Get Spot Price to determine ATM
    symbol = "BANKNIFTY"
    spot = fyers.get_index_spot(symbol)
    print(f"✅ Spot Price for {symbol}: {spot}")
    
    if spot == 0:
        print("❌ Failed to get spot price. Using dummy 52000.")
        spot = 52000
        
    atm = round(spot / 100) * 100
    print(f"🎯 ATM Strike: {atm}")
    
    # 2. Test Formats for Upcoming Expiries
    # Assuming today is Nov 27, 2025
    # Next Tuesday is Dec 2, 2025
    # Next Wednesday is Dec 3, 2025
    
    # Let's try to construct symbols for a few likely dates
    dates_to_test = [
        datetime(2025, 12, 2).date(), # Next Tuesday
        datetime(2025, 12, 3).date(), # Next Wednesday
        datetime(2025, 12, 30).date(), # The one user saw
        datetime(2025, 12, 31).date(), # Last Wed of Dec
    ]
    
    test_symbols = []
    
    for d in dates_to_test:
        # Weekly Format: YY M DD
        # Month Codes: 1-9, O, N, D
        m_map = {10:'O', 11:'N', 12:'D'}
        m_code = m_map.get(d.month, str(d.month))
        yy = d.strftime('%y')
        dd = d.strftime('%d')
        
        weekly_sym = f"NSE:BANKNIFTY{yy}{m_code}{dd}{atm}CE"
        test_symbols.append(weekly_sym)
        
        # Monthly Format: YY MMM
        mmm = d.strftime('%b').upper()
        monthly_sym = f"NSE:BANKNIFTY{yy}{mmm}{atm}CE"
        test_symbols.append(monthly_sym)
        
        # New Weekly Format? (Some brokers use YY M DD, some use YY MMM DD)
        # Fyers might have changed.
        
    print(f"🔍 Testing {len(test_symbols)} symbols...")
    for s in test_symbols:
        print(f"  - {s}")
        
    quotes = fyers.get_quotes(test_symbols)
    
    print("\n📊 Results:")
    for sym, data in quotes.items():
        print(f"✅ {sym}: LTP={data.get('lp')} V={data.get('v')}")
        
    # Also check what get_expiry_dates returns if we can access RealMarketData
    try:
        from fetcher.real_market_data import RealMarketData
        rmd = RealMarketData(fyers_manager=fyers)
        print("\n🔍 Checking RealMarketData.get_expiry_dates...")
        expiries = rmd.get_expiry_dates("BANKNIFTY")
        print(f"📅 Expiries returned: {expiries[:5]}")
    except Exception as e:
        print(f"❌ Could not check expiries: {e}")

if __name__ == "__main__":
    debug_symbols()
