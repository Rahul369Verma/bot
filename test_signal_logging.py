import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

load_dotenv()

from utils.database_manager import DatabaseManager, IST

def test_signal_logging():
    print("Testing Signal Logging & Cleanup...")
    db = DatabaseManager()
    
    if not db.connected:
        print("❌ MongoDB not connected.")
        return

    # 1. Test Logging
    print("\n--- 1. Testing Log Insertion ---")
    db.log_signal_check("TEST_STATUS", "Test message from script", {"foo": "bar"})
    
    # Verify insertion
    latest = db.signal_collection.find_one({"status": "TEST_STATUS"}, sort=[("timestamp", -1)])
    if latest:
        print(f"✅ Logged successfully: {latest['message']} at {latest['timestamp']}")
    else:
        print("❌ Failed to find inserted log.")

    # 2. Test Cleanup
    print("\n--- 2. Testing Cleanup ---")
    # Insert old log (3 days ago)
    old_date = datetime.now(IST) - timedelta(days=3)
    db.signal_collection.insert_one({
        "timestamp": old_date,
        "status": "OLD_LOG",
        "message": "This should be deleted"
    })
    print(f"Inserted old log with timestamp: {old_date}")
    
    # Verify it exists
    count_before = db.signal_collection.count_documents({"status": "OLD_LOG"})
    print(f"Old logs count before cleanup: {count_before}")
    
    # Run cleanup (older than 2 days)
    db.cleanup_signal_logs(days=2)
    
    # Verify deletion
    count_after = db.signal_collection.count_documents({"status": "OLD_LOG"})
    print(f"Old logs count after cleanup: {count_after}")
    
    if count_before > 0 and count_after == 0:
        print("✅ Cleanup successful: Old logs deleted.")
    else:
        print("❌ Cleanup failed.")

if __name__ == "__main__":
    test_signal_logging()
