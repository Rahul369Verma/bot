import requests
import os
import threading

class TelegramBot:
    """
    Sends notifications via Telegram Bot API.
    """
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        if not self.bot_token or not self.chat_id:
            print("⚠️ Telegram Bot Token or Chat ID not found in .env. Notifications disabled.")
            self.enabled = False
        else:
            print("✅ Telegram Bot initialized.")
            self.enabled = True

    def send_message(self, message: str):
        """
        Sends a text message to the configured chat ID.
        Runs in a separate thread to avoid blocking the main bot loop.
        """
        if not self.enabled:
            return

        def _send():
            try:
                payload = {
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
                response = requests.post(self.base_url, json=payload, timeout=5)
                if response.status_code != 200:
                    print(f"❌ Telegram Error {response.status_code}: {response.text}")
                # else:
                #     print("✅ Telegram message sent.")
            except Exception as e:
                print(f"❌ Failed to send Telegram message: {e}")

        # Fire and forget
        threading.Thread(target=_send, daemon=True).start()

    def send_alert(self, title: str, body: str):
        """
        Sends a formatted alert message.
        """
        msg = f"*{title}*\n\n{body}"
        self.send_message(msg)
