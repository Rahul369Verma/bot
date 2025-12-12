const fyers = require("fyers-api-v3");
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const crypto = require('crypto');

class FyersDataManager {
    constructor() {
        this.fyers = new fyers.fyersModel();
        this.app_id = process.env.FYERS_APP_ID;
        this.secret_key = process.env.FYERS_SECRET_KEY;
        this.redirect_uri = process.env.FYERS_REDIRECT_URL;
        this.token_path = path.join(__dirname, '../../fyers_token.json');
        this.access_token = null;
        
        this.fyers.setAppId(this.app_id);
        this.fyers.setRedirectUrl(this.redirect_uri);
        
        this.isRateLimited = false;
        this.rateLimitResetTime = 0;
        this.lastRequestTime = 0;
        this.minRequestInterval = 1000; // 1 second between requests

        this.marketData = {}; // Store live data
        this.dataSocket = null;
        this.isSocketConnected = false;

        this.loadToken();
    }

    async waitForRateLimit() {
        if (this.isRateLimited) {
            if (Date.now() > this.rateLimitResetTime) {
                console.log("✅ Fyers Rate Limit Cooldown Expired. Resuming requests.");
                this.isRateLimited = false;
            } else {
                // Wait until reset
                const waitTime = this.rateLimitResetTime - Date.now();
                if (waitTime > 0) {
                    console.log(`⏳ Rate Limited (Cooldown). Waiting ${Math.ceil(waitTime/1000)}s...`);
                    await new Promise(r => setTimeout(r, waitTime + 1000));
                }
                this.isRateLimited = false;
            }
        }
        
        const now = Date.now();
        const diff = now - this.lastRequestTime;
        if (diff < this.minRequestInterval) {
            const delay = this.minRequestInterval - diff;
            // console.log(`⏳ Rate Limit Throttling. Waiting ${delay}ms...`);
            await new Promise(r => setTimeout(r, delay));
        }
        this.lastRequestTime = Date.now();
    }

    // --- WebSocket Implementation ---
    async connectWebSocket(retryCount = 0) {
        if (!this.access_token) {
            console.error("❌ Cannot connect to Fyers Socket: No Access Token");
            return;
        }

        // Singleton Check
        if (this.dataSocket) {
            console.log("⚠️ Socket already initialized. Skipping.");
            return;
        }

        console.log("🔌 Connecting to Fyers Real WebSocket...");

        try {
            const socketToken = `${this.app_id}:${this.access_token}`;
            const logPath = path.join(__dirname, '../../../logs');

            // Try to get existing instance if supported
            if (fyers.fyersDataSocket && typeof fyers.fyersDataSocket.getInstance === 'function') {
                try {
                    this.dataSocket = fyers.fyersDataSocket.getInstance(socketToken, logPath);
                } catch (e) {
                    // Fallback if getInstance fails or doesn't exist as expected
                    this.dataSocket = new fyers.fyersDataSocket(socketToken, logPath);
                }
            } else {
                // Standard instantiation with error handling for singleton
                try {
                    this.dataSocket = new fyers.fyersDataSocket(socketToken, logPath);
                } catch (err) {
                    if (err.message && err.message.includes("Only one instance")) {
                        console.log("⚠️ Socket singleton active. Using existing instance.");
                        // Attempt to retrieve it from a global variable if we saved it previously
                        if (global.fyersSocketInstance) {
                            this.dataSocket = global.fyersSocketInstance;
                        } else {
                            console.error("❌ Critical: Fyers Socket Singleton locked but instance lost. Restarting process might be needed.");
                            return;
                        }
                    } else {
                        throw err;
                    }
                }
            }

            // Save to global to recover later if needed
            global.fyersSocketInstance = this.dataSocket;

            this.dataSocket.on("connect", () => {
                console.log("✅ Fyers Socket Connected");
                this.isSocketConnected = true;
                
                // Re-subscribe to cached symbols if any
                if (this.subscribedSymbols && this.subscribedSymbols.length > 0) {
                    console.log(`⏳ Waiting 5s before subscribing to ensure socket stability...`);
                    setTimeout(() => {
                        console.log(`📡 [Fyers Socket] Re-subscribing to: ${this.subscribedSymbols.join(', ')}`);
                        try {
                            this.dataSocket.subscribe(this.subscribedSymbols);
                            this.dataSocket.mode(this.subscribedSymbols, fyers.fyersDataSocket.LiteMode);
                        } catch (err) {
                            console.error("❌ Subscription Error:", err.message);
                        }
                    }, 5000);
                }
            });

            this.dataSocket.on("message", (message) => {
                // console.log("📩 Socket Message:", message);
                let data = message;
                
                // Handle 'sf' type with response wrapper
                if (message && message.type === 'sf' && message.response) {
                    data = message.response;
                }

                if (data && data.symbol) {
                    this.marketData[data.symbol] = {
                        ltp: data.ltp || data.lt,
                        vol: data.vol || data.v,
                        ch: data.ch,
                        chp: data.chp || data.cp,
                        timestamp: new Date().toISOString()
                    };
                }
            });

            this.dataSocket.on("error", (err) => {
                console.error("❌ Fyers Socket Error:", err);
                this.isSocketConnected = false;
                // Do not nullify this.dataSocket immediately to avoid losing the singleton reference
                // unless it's a fatal error that destroys the instance.
            });

            this.dataSocket.on("close", () => {
                console.log("⚠️ Fyers Socket Closed");
                this.isSocketConnected = false;
                this.dataSocket = null; // Clear reference to allow new connection attempt
                global.fyersSocketInstance = null;
                setTimeout(() => this.connectWebSocket(), 5000);
            });

            this.dataSocket.connect();

        } catch (err) {
            console.error("❌ Fyers Socket Init Failed:", err.message);
            
            // Handle Expired Token
            if (retryCount < 3 && err.message && (err.message.includes("expired token") || err.message.includes("Failed to decode JWT"))) {
                console.log("⚠️ Token expired during Socket Init. Attempting refresh...");
                const refreshed = await this.refreshAccessToken();
                if (refreshed) {
                    console.log("🔄 Token Refreshed. Retrying Socket Connection...");
                    this.dataSocket = null;
                    global.fyersSocketInstance = null;
                    await this.connectWebSocket(retryCount + 1);
                }
            }
        }
    }

    async subscribe(symbols) {
        // Add to local cache of subscribed symbols
        if (!this.subscribedSymbols) this.subscribedSymbols = [];
        const newSymbols = symbols.filter(s => !this.subscribedSymbols.includes(s));
        if (newSymbols.length === 0) return; // Already subscribed
        
        this.subscribedSymbols = [...this.subscribedSymbols, ...newSymbols];

        if (!this.dataSocket || !this.isSocketConnected) {
            console.log(`⚠️ Socket not ready. Queued subscription for: ${newSymbols.join(', ')}`);
            return;
        }
        
        console.log(`📡 [Fyers Socket] Subscribing to: ${newSymbols.join(', ')}`);
        // Symbol format: "NSE:SBIN-EQ"
        // Mode: fyers.fyersDataSocket.LiteMode / FullMode
        // We use FullMode for more data
        this.dataSocket.subscribe(newSymbols);
        this.dataSocket.mode(newSymbols, fyers.fyersDataSocket.LiteMode); // Start with Lite for speed
    }

    async unsubscribe(symbols) {
        if (!this.subscribedSymbols) return;
        
        const symbolsToRemove = symbols.filter(s => this.subscribedSymbols.includes(s));
        if (symbolsToRemove.length === 0) return;

        this.subscribedSymbols = this.subscribedSymbols.filter(s => !symbolsToRemove.includes(s));

        if (!this.dataSocket || !this.isSocketConnected) {
             return;
        }

        console.log(`📡 [Fyers Socket] Unsubscribing from: ${symbolsToRemove.length} symbols`);
        try {
            this.dataSocket.unsubscribe(symbolsToRemove);
        } catch (err) {
            console.error("❌ Socket Unsubscribe Error:", err.message);
        }
    }
    
    getLiveQuote(symbol) {
        return this.marketData[symbol] || null;
    }

    async handleError(err, context) {
        const errString = JSON.stringify(err);
        if (errString.includes("Cloudflare") || errString.includes("1015") || (typeof err === 'string' && err.includes("<!DOCTYPE html>"))) {
            console.error(`❌ Fyers API Rate Limit Detected in ${context}. Pausing for 15 minutes.`);
            this.isRateLimited = true;
            this.rateLimitResetTime = Date.now() + 15 * 60 * 1000; // 15 mins
        } else if (errString.includes("Invalid Access Token") || errString.includes("-14") || (err.message && err.message.includes("Invalid Access Token"))) {
            console.error(`⚠️ Invalid Access Token in ${context}. Attempting Refresh...`);
            await this.refreshAccessToken();
        } else {
            console.error(`Fyers ${context} Error:`, err.message || err);
        }
    }

    // --- REST API Methods (With Logging) ---

    async getQuotes(symbols) {
        await this.waitForRateLimit();
        if (!this.access_token) return {};
        try {
            console.log(`📡 [API] Fetching Quotes for: ${symbols}`);
            const symArray = symbols.split(',');
            const response = await this.fyers.getQuotes(symArray);
            
            if (typeof response === 'string' && response.includes("<!DOCTYPE html>")) {
                throw new Error("Cloudflare Rate Limit (HTML Response)");
            }

            if (response.s === "ok") {
                const map = {};
                response.d.forEach(item => {
                    map[item.n] = item.v;
                });
                return map;
            }
            return {};
        } catch (err) {
            this.handleError(err, "Quotes");
            return {};
        }
    }

    loadToken() {
        try {
            if (fs.existsSync(this.token_path)) {
                const data = fs.readFileSync(this.token_path, 'utf8');
                const tokenData = JSON.parse(data);
                this.access_token = tokenData.access_token;
                this.refresh_token = tokenData.refresh_token; // Load Refresh Token
                this.fyers.setAccessToken(this.access_token);
                console.log("✅ Fyers Token Loaded");
            }
        } catch (err) {
            console.error("❌ Failed to load Fyers token:", err.message);
        }
    }

    isAuthenticated() {
        return !!this.access_token;
    }

    async getHistory(symbol, resolution, range_from, range_to) {
        await this.waitForRateLimit();
        if (!this.access_token) throw new Error("Fyers not authenticated");
        
        console.log(`📡 [API] Fetching History for: ${symbol} (${resolution}) from ${range_from} to ${range_to}`);

        let res = resolution;
        if (resolution === "1D") res = "D";

        const startDate = new Date(range_from);
        const endDate = new Date(range_to);
        const allCandles = [];
        
        let currentStart = new Date(startDate);

        while (currentStart < endDate) {
            // Fyers limit is usually 100 days for 1m, let's stick to 60 days to be safe for all resolutions
            let currentEnd = new Date(currentStart);
            currentEnd.setDate(currentEnd.getDate() + 60);
            
            if (currentEnd > endDate) currentEnd = endDate;

            const fromStr = currentStart.toISOString().split('T')[0];
            const toStr = currentEnd.toISOString().split('T')[0];

            // console.log(`   Fetching chunk: ${fromStr} to ${toStr}`);

            const input = {
                symbol: symbol,
                resolution: res,
                date_format: "1",
                range_from: fromStr,
                range_to: toStr,
                cont_flag: "1"
            };

            let retries = 3;
            let success = false;

            while (retries > 0 && !success) {
                try {
                    const response = await this.fyers.getHistory(input);
                    
                    if (typeof response === 'string' && response.includes("<!DOCTYPE html>")) {
                        throw new Error("Cloudflare Rate Limit (HTML Response)");
                    }

                    if (response.s === "ok" && response.candles) {
                        const chunk = response.candles.map(c => ({
                            date: new Date(c[0] * 1000), // Fyers returns epoch seconds
                            open: c[1],
                            high: c[2],
                            low: c[3],
                            close: c[4],
                            volume: c[5]
                        }));
                        allCandles.push(...chunk);
                        success = true;
                    } else if (response.s === "error") {
                         console.error(`   ❌ Fyers History Error (Chunk ${fromStr}):`, response.message);
                         // Don't retry if it's a logic error, only network
                         if (response.message.includes("limit") || response.message.includes("timeout")) {
                             throw new Error(response.message);
                         } else {
                             break; // Break retry loop for non-recoverable errors
                         }
                    } else {
                        // No candles or unknown status
                        success = true; // Treat as empty chunk if no error
                    }
                } catch (err) {
                    console.error(`   ⚠️ History Chunk Failed (${fromStr}): ${err.message}. Retrying (${retries-1} left)...`);
                    
                    // Check for Token Expiry
                    if (err.message.includes("Invalid Access Token") || err.message.includes("-14") || err.message.includes("401")) {
                        console.log("🔄 Token Expired during History Fetch. Refreshing...");
                        const refreshed = await this.refreshAccessToken();
                        if (refreshed) {
                            console.log("✅ Token Refreshed. Retrying request...");
                            // Don't decrement retries if it was just a token issue?
                            // Or maybe just continue loop
                            continue; 
                        } else {
                            console.error("❌ Token Refresh Failed.");
                            throw new Error("Token Expired and Refresh Failed");
                        }
                    }

                    retries--;
                    if (retries > 0) {
                        await new Promise(r => setTimeout(r, 2000)); // Wait 2s before retry
                    }
                }
            }

            // Move to next chunk
            currentStart = new Date(currentEnd);
            currentStart.setDate(currentStart.getDate() + 1); // Start next day
            
            // Increased delay to 500ms to avoid rate limits
            await new Promise(r => setTimeout(r, 500));
        }

        // Remove duplicates if any (based on timestamp)
        const uniqueCandles = [];
        const seenTimes = new Set();
        for (const c of allCandles) {
            const time = c.date.getTime();
            if (!seenTimes.has(time)) {
                seenTimes.add(time);
                uniqueCandles.push(c);
            }
        }
        
        // Sort by time
        uniqueCandles.sort((a, b) => a.date - b.date);

        console.log(`✅ Fetched ${uniqueCandles.length} total candles.`);
        return uniqueCandles;
    }
    getLoginUrl() {
        return `https://api-t1.fyers.in/api/v3/generate-authcode?client_id=${this.app_id}&redirect_uri=${this.redirect_uri}&response_type=code&state=sample_state`;
    }

    async generateToken(authCode) {
        try {
            console.log("🔐 [API] Generating Access Token...");
            const reqBody = {
                grant_type: "authorization_code",
                secret_key: this.secret_key,
                auth_code: authCode
            };

            const response = await this.fyers.generate_access_token(reqBody);
            if (response.s === "ok") {
                this.access_token = response.access_token;
                this.refresh_token = response.refresh_token; // Save Refresh Token
                this.fyers.setAccessToken(this.access_token);
                
                const tokenData = {
                    access_token: this.access_token,
                    refresh_token: this.refresh_token,
                    timestamp: new Date().toISOString()
                };
                fs.writeFileSync(this.token_path, JSON.stringify(tokenData, null, 2));
                console.log("✅ Fyers Token Generated & Saved");
                return true;
            } else {
                console.error("❌ Fyers Token Generation Failed:", response);
                return false;
            }
        } catch (err) {
            console.error("❌ Fyers Token Error:", err);
            return false;
        }
    }

    async refreshAccessToken() {
        if (!this.refresh_token) {
            console.error("❌ No Refresh Token available to refresh access token.");
            return false;
        }

        try {
            console.log("🔄 [API] Refreshing Access Token...");
            
            const appIdHash = crypto.createHash('sha256').update(`${this.app_id}:${this.secret_key}`).digest('hex');
            
            const reqBody = {
                grant_type: "refresh_token",
                app_id: this.app_id,
                refresh_token: this.refresh_token,
                pin: process.env.FYERS_PIN,
                appIdHash: appIdHash
            };

            // Direct Axios call because library doesn't support refresh flow correctly
            const response = await axios.post("https://api-t1.fyers.in/api/v3/validate-refresh-token", reqBody);
            
            if (response.data && response.data.s === "ok") {
                this.access_token = response.data.access_token;
                // Refresh token might rotate, so update it if provided
                // Fyers v3 usually keeps the same refresh token but let's check
                if (response.data.refresh_token) {
                    this.refresh_token = response.data.refresh_token;
                }
                
                this.fyers.setAccessToken(this.access_token);
                
                const tokenData = {
                    access_token: this.access_token,
                    refresh_token: this.refresh_token,
                    timestamp: new Date().toISOString()
                };
                fs.writeFileSync(this.token_path, JSON.stringify(tokenData, null, 2));
                console.log("✅ Fyers Token Refreshed & Saved");
                return true;
            } else {
                console.error("❌ Fyers Token Refresh Failed:", response.data);
                return false;
            }
        } catch (err) {
            console.error("❌ Fyers Token Refresh Error:", err.response ? err.response.data : err.message);
            return false;
        }
    }

    corruptToken() {
        console.log("⚠️ Corrupting Access Token for Testing...");
        this.access_token = "invalid_token_string";
        this.fyers.setAccessToken(this.access_token);
        // Also update file to persist corruption across restarts if needed, 
        // but for runtime test, memory corruption is enough if we trigger a request.
        // Let's corrupt the file too to be sure.
        const tokenData = {
            access_token: "invalid_token_string",
            refresh_token: this.refresh_token, // Keep refresh token valid
            timestamp: new Date().toISOString()
        };
        fs.writeFileSync(this.token_path, JSON.stringify(tokenData, null, 2));
    }

    async getMarketDepth(symbol) {
        await this.waitForRateLimit();
        if (!this.access_token) return null;
        try {
            console.log(`📡 [API] Fetching Market Depth for: ${symbol}`);
            const response = await this.fyers.getMarketDepth({ symbol: symbol, ohlcv_flag: 1 });
            if (response.s === "ok") {
                return response.d[symbol];
            }
            return null;
        } catch (err) {
            this.handleError(err, "Depth");
            return null;
        }
    }
    async placeOrder(orderParams) {
        await this.waitForRateLimit();
        if (!this.access_token) throw new Error("Fyers not authenticated");
        
        try {
            console.log(`🚀 [API] Placing Order:`, orderParams);
            const response = await this.fyers.place_order(orderParams);
            
            if (response.s === "ok") {
                console.log(`✅ Order Placed Successfully. ID: ${response.id}`);
                return { success: true, id: response.id, message: response.message };
            } else {
                console.error("❌ Order Placement Failed:", response);
                return { success: false, message: response.message };
            }
        } catch (err) {
            this.handleError(err, "Place Order");
            return { success: false, message: err.message };
        }
    }
}

module.exports = FyersDataManager;
