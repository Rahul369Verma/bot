import os
import pymongo
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import urllib.parse

IST = ZoneInfo('Asia/Kolkata')

class DatabaseManager:
    """
    Manages MongoDB connection and operations for trade logging.
    """
    def __init__(self):
        self.username = os.getenv("MONGO_USERNAME")
        self.password = os.getenv("MONGO_PASSWORD")
        self.cluster_url = "cluster0.55uxt6z.mongodb.net" # From user request
        self.app_name = "Cluster0"
        self.db_name = "trading_bot"
        self.collection_name = "trade_history"
        self.signal_collection_name = "signal_check_logs"
        
        self.client = None
        self.db = None
        self.collection = None
        self.signal_collection = None
        self.connected = False
        
        self.connect()

    def connect(self):
        if not self.username or not self.password:
            print("⚠️ MongoDB Credentials (MONGO_USERNAME, MONGO_PASSWORD) not found in .env")
            return

        try:
            # URL Encode username and password to handle special characters
            username = urllib.parse.quote_plus(self.username)
            password = urllib.parse.quote_plus(self.password)
            
            uri = f"mongodb+srv://{username}:{password}@{self.cluster_url}/?retryWrites=true&w=majority&appName={self.app_name}"
            
            self.client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            
            # Verify connection
            self.client.admin.command('ping')
            
            self.db = self.client[self.db_name]
            self.collection = self.db[self.collection_name]
            self.signal_collection = self.db[self.signal_collection_name]
            self.connected = True
            print("✅ Connected to MongoDB Atlas successfully.")
            
        except Exception as e:
            print(f"❌ Failed to connect to MongoDB: {e}")
            self.connected = False

    def log_trade(self, trade_data: dict):
        """
        Logs a trade to MongoDB.
        """
        if not self.connected or self.collection is None:
            return
            
        try:
            # Ensure timestamp is present
            if 'timestamp' not in trade_data:
                trade_data['timestamp'] = datetime.now(IST)
            
            # Insert
            self.collection.insert_one(trade_data)
            print(f"✅ Trade logged to MongoDB: {trade_data.get('tradingsymbol')}")
            
        except Exception as e:
            print(f"❌ Failed to log trade to MongoDB: {e}")

    def get_trades(self, limit: int = 50):
        """
        Fetches recent trades from MongoDB.
        """
        if not self.connected or self.collection is None:
            return []
            
        try:
            trades = list(self.collection.find().sort("timestamp", -1).limit(limit))
            # Convert ObjectId to string for UI display if needed, or just return
            return trades
        except Exception as e:
            print(f"❌ Failed to fetch trades from MongoDB: {e}")
            return []

    def log_signal_check(self, status: str, message: str, details: dict = None):
        """
        Logs a signal check event to MongoDB.
        """
        if not self.connected or self.signal_collection is None:
            return

        try:
            log_entry = {
                "timestamp": datetime.now(IST),
                "status": status,
                "message": message,
                "details": details or {}
            }
            self.signal_collection.insert_one(log_entry)
            # print(f"✅ Signal check logged: {status}") 
        except Exception as e:
            print(f"❌ Failed to log signal check: {e}")

    def cleanup_signal_logs(self, days: int = 2):
        """
        Deletes signal logs older than 'days'.
        """
        if not self.connected or self.signal_collection is None:
            return

        try:
            cutoff_date = datetime.now(IST) - timedelta(days=days)
            result = self.signal_collection.delete_many({"timestamp": {"$lt": cutoff_date}})
            print(f"🧹 Cleaned up {result.deleted_count} old signal logs (older than {days} days).")
        except Exception as e:
            print(f"❌ Failed to cleanup signal logs: {e}")
