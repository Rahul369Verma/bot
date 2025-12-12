const axios = require('axios');

class TelegramBot {
    constructor() {
        this.token = process.env.TELEGRAM_BOT_TOKEN;
        this.chatId = process.env.TELEGRAM_CHAT_ID;
        this.baseUrl = `https://api.telegram.org/bot${this.token}`;
    }

    async sendMessage(text) {
        if (!this.token || !this.chatId) {
            console.log("⚠️ Telegram credentials missing. Skipping notification.");
            return;
        }

        try {
            await axios.post(`${this.baseUrl}/sendMessage`, {
                chat_id: this.chatId,
                text: text,
                parse_mode: 'Markdown'
            });
            console.log("✅ Telegram notification sent.");
        } catch (err) {
            console.error("❌ Failed to send Telegram message:", err.message);
        }
    }
}

module.exports = new TelegramBot();
