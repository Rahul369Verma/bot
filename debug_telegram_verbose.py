import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"🔹 Token: {TOKEN}")
print(f"🔹 Chat ID: {CHAT_ID}")

if not TOKEN or not CHAT_ID:
    print("❌ Missing credentials in .env")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "🔔 *Debug Message* \n\nTesting credentials directly.",
    "parse_mode": "Markdown"
}

print(f"🚀 Sending request to {url}...")
try:
    response = requests.post(url, json=payload, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        print("✅ Success! Message should be delivered.")
    else:
        print("❌ Failed to send.")
except Exception as e:
    print(f"❌ Exception: {e}")
