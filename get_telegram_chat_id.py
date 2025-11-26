import requests
import time
import sys

# Hardcoded token from user input for this helper script
TOKEN = "8254080804:AAGv_YQagWaM-i7aQP8FAi1xS2xcBlBdQIA"
URL = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

def get_chat_id():
    print(f"🤖 Checking for messages sent to bot (Token: {TOKEN[:10]}...)...")
    print("👉 Please open your bot in Telegram (@scalp369bot) and send a message (e.g., 'Hello').")
    
    for i in range(30):
        try:
            response = requests.get(URL)
            data = response.json()
            
            if data.get("ok"):
                results = data.get("result", [])
                if results:
                    # Get the last message
                    last_update = results[-1]
                    chat_id = last_update["message"]["chat"]["id"]
                    username = last_update["message"]["chat"].get("username", "Unknown")
                    first_name = last_update["message"]["chat"].get("first_name", "Unknown")
                    
                    print(f"\n✅ FOUND IT!")
                    print(f"👤 User: {first_name} (@{username})")
                    print(f"🆔 Chat ID: {chat_id}")
                    print("\nCopy this Chat ID and I will save it to your .env file.")
                    return chat_id
            
            print(f"⏳ Waiting for message... ({i+1}/30)", end="\r")
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(2)
            
    print("\n❌ No message received. Please try again.")
    return None

if __name__ == "__main__":
    get_chat_id()
