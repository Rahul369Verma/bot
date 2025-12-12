const { SmartAPI } = require("smartapi-javascript");
const FyersDataManager = require("./fyersData");
const fs = require('fs');
const path = require('path');
const { authenticator } = require('otplib');

class AngelClient {
    constructor(paper = true, index_name = "BANKNIFTY") {
        this.paper = paper;
        this.index_name = index_name;
        this.fyersManager = new FyersDataManager();
        this.smartApi = new SmartAPI({
            api_key: process.env.ANGEL_API_KEY,
        });
        
        this.positions = []; // Paper positions
        this.daily_pnl = 0;
        this.trades_count = 0;
        this.max_trades = 10;
        this.max_loss = 2000;
        
        // Initialize Session
        this.initSession();
    }

    async initSession() {
        try {
            if (!process.env.ANGEL_PASSWORD) {
                console.error("❌ ANGEL_PASSWORD is missing in .env");
                return;
            }

            // Generate TOTP
            const totp = authenticator.generate(process.env.ANGEL_TOTP_SECRET);
            
            const data = await this.smartApi.generateSession(process.env.ANGEL_CLIENT_CODE, process.env.ANGEL_PASSWORD, totp);
            if (data.status) {
                console.log("✅ Angel One Session Initialized");
            } else {
                console.error("❌ Angel Session Failed:", JSON.stringify(data));
            }
        } catch (err) {
            console.error("❌ Angel Init Error:", err.message);
        }
    }

    async getLTP(symbol) {
        // Use Fyers for Data
        try {
            // Ensure symbol format
            const fyersSymbol = symbol.startsWith("NSE:") ? symbol : `NSE:${symbol}-INDEX`; // Basic assumption for BankNifty
            const quotes = await this.fyersManager.getQuotes(fyersSymbol);
            if (quotes[fyersSymbol]) {
                return quotes[fyersSymbol].lp;
            }
            return 0.0;
        } catch (err) {
            console.error("Error fetching LTP:", err);
            return 0.0;
        }
    }

    async getPositions() {
        if (this.paper) {
            return this.positions;
        } else {
            // Fetch Real Positions from Fyers
            try {
                const response = await this.fyersManager.fyers.positions();
                if (response.s === "ok") {
                    return response.netPositions.map(p => ({
                        symbol: p.symbol,
                        quantity: p.netQty,
                        price: p.avgPrice,
                        ltp: p.ltp, // Fyers usually provides LTP in positions
                        pnl: p.pl,
                        product: p.productType
                    }));
                }
                return [];
            } catch (err) {
                console.error("Error fetching real positions:", err);
                return [];
            }
        }
    }

    // ... executeTrade ...

    async getOptionChain() {
        try {
            // 1. Get Underlying LTP
            const underlyingLtp = await this.getLTP(this.index_name); // e.g., 45123
            if (!underlyingLtp) return [];

            // 2. Calculate ATM Strike
            const strikeStep = 100; // BankNifty Step
            const atmStrike = Math.round(underlyingLtp / strikeStep) * strikeStep;

            // 3. Generate Symbols (5 up, 5 down)
            // Expiry Format: YYMDD (Year, Month Code, Date)
            // Month Codes: 1-9, O(Oct), N(Nov), D(Dec)
            // Example: 11th Dec 2024 -> 24D11
            const expiry = "24D11"; 
            const symbols = [];
            
            for (let i = -5; i <= 5; i++) {
                const strike = atmStrike + (i * strikeStep);
                symbols.push(`NSE:${this.index_name}${expiry}${strike}CE`);
                symbols.push(`NSE:${this.index_name}${expiry}${strike}PE`);
            }

            // 4. Fetch Quotes from Fyers
            // Join symbols with comma
            const quotes = await this.fyersManager.getQuotes(symbols.join(','));

            // 5. Map Data
            const chain = [];
            symbols.forEach(sym => {
                const data = quotes[sym];
                if (data) {
                    // Extract details from symbol
                    // NSE:BANKNIFTY24D1145000CE
                    const type = sym.endsWith("CE") ? "CE" : "PE";
                    const strikeMatch = sym.match(/(\d{5})(CE|PE)$/);
                    const strike = strikeMatch ? parseInt(strikeMatch[1]) : 0;

                    chain.push({
                        strike: strike,
                        type: type,
                        tradingsymbol: sym,
                        ltp: data.lp || 0,
                        oi: data.oi || 0, // Open Interest might be in a different field depending on API
                        iv: 0 // Fyers Quote API might not give IV directly, mock or calc if needed.
                    });
                }
            });

            // Sort by Strike
            return chain.sort((a, b) => a.strike - b.strike);

        } catch (err) {
            console.error("❌ Error fetching Option Chain:", err.message);
            return [];
        }
    }

    async getTradeHistory() {
        // Fetch from MongoDB via Mongoose model (need to import or access via global/passed model)
        // Since AngelClient doesn't have direct access to Mongoose models defined in server.js, 
        // we might need to move this logic to server.js or import the model here.
        // For now, let's assume we can import it or use a separate DB manager.
        // Simpler: Let server.js handle the DB fetch for /api/engine/mongo-trades
        // But the interface requires this method.
        // Let's return a placeholder that server.js will override, OR import mongoose here.
        
        // Better: Import the model if possible, or return null and let server handle it.
        // server.js has: app.get('/api/engine/mongo-trades', ... angelClient.getTradeHistory())
        // Let's change server.js to query DB directly for this endpoint.
        return []; 
    }
}

module.exports = AngelClient;
