import sys
import os
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from utils.telegram_bot import TelegramBot
import time

def test_telegram():
    print("🚀 Initializing TelegramBot...")
    bot = TelegramBot()
    
    if not bot.enabled:
        print("❌ Telegram Bot is disabled. Please check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return

    print("✅ Telegram Bot initialized.")
    print("📨 Sending test message...")
    
    bot.send_message("🔔 *Test Message from BankNifty Bot* 🔔\n\nIf you see this, notifications are working! 🚀")
    
    # Wait for thread to finish (since it's daemon)
    time.sleep(2)
    print("✅ Message sent (check your Telegram).")

if __name__ == "__main__":
    test_telegram()
