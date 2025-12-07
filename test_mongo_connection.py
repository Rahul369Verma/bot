import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

load_dotenv()

from utils.database_manager import DatabaseManager

def test_mongo():
    print("Testing MongoDB Connection...")
    db = DatabaseManager()
    
    if db.connected:
        print("✅ Connection Successful!")
        
        # Test Insert
        test_data = {
            "tradingsymbol": "TEST-SYMBOL",
            "action": "TEST-BUY",
            "quantity": 1,
            "price": 100.0,
            "is_paper": True,
            "reason": "CONNECTION_TEST"
        }
        db.log_trade(test_data)
        
        # Test Read
        trades = db.get_trades(limit=5)
        print(f"✅ Fetched {len(trades)} trades.")
        for t in trades:
            print(f" - {t.get('tradingsymbol')} ({t.get('action')}) at {t.get('timestamp')}")
            
    else:
        print("❌ Connection Failed.")

if __name__ == "__main__":
    test_mongo()
