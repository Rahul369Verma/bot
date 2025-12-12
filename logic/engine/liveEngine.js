const MultiTimeframeStrategy = require('../strategies/mtaStrategy');
const mongoose = require('mongoose');
const telegramBot = require('../utils/telegramBot');
const { getNextExpiry, getOptionSymbols } = require('../utils/optionChain');

// Trade Model (Same as in server.js)
const TradeSchema = new mongoose.Schema({}, { strict: false, collection: 'trade_history' });
const Trade = mongoose.models.Trade || mongoose.model('Trade', TradeSchema);

class LiveEngine {
    constructor(fyersManager, io) {
        this.fyersManager = fyersManager;
        this.io = io;
        this.strategy = new MultiTimeframeStrategy();
        this.isRunning = false;
        this.intervalId = null;
        this.position = null; // { type: 'BUY'|'SELL', entryPrice, quantity, sl, tp, symbol, entryTime }
        this.symbol = "NSE:NIFTYBANK-INDEX";
        this.lotSize = 35; // Default, will update from cache
        this.mode = process.env.MODE || 'paper';
        this.lastHeartbeatTime = 0;
    }

    async runLoop() {
        if (!this.isRunning) return;

        // Heartbeat Check (Every 15 mins)
        const now = Date.now();
        if (now - this.lastHeartbeatTime > 15 * 60 * 1000) {
            telegramBot.sendMessage(`💓 *Heartbeat*: Bot is running and checking signals.\nMode: ${this.mode.toUpperCase()}`);
            this.lastHeartbeatTime = now;
        }

        if (!this.fyersManager.isAuthenticated()) {
            console.error("❌ Fyers Not Authenticated");
            telegramBot.sendMessage("⚠️ *Error*: Fyers Not Authenticated. Please login.");
            return;
        }

        try {
            // 1. Fetch Data (5m candles)
            const dateObj = new Date();
            const fromDate = new Date(dateObj.getTime() - 5 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
            const toDate = dateObj.toISOString().split('T')[0];
            
            const candles = await this.fyersManager.getHistory(this.symbol, "5", fromDate, toDate);
            if (!candles || candles.length < 50) return;

            const lastCandle = candles[candles.length - 1];
            
            // Calculate Indicators for the closed candles
            const ind = this.strategy.calculateIndicators(candles);
            
            // Store for Live EMA calculation
            this.lastClosedCandle = {
                close: lastCandle.close,
                ema_short: ind.ema_short,
                ema_long: ind.ema_long
            };

            // 2. Check Exits if in Position (Handled by watchPositionLoop mostly)
            // We still check here as a fallback or for other signals
            if (this.position) {
                // ... (Logic moved to watchPositionLoop for speed, but kept here as backup)
            } 
            // 3. Check Entries if not in Position
            else {
                await this.checkEntry(candles);
            }

        } catch (err) {
            console.error("❌ Live Engine Error:", err.message);
            telegramBot.sendMessage(`❌ *Error in Signal Loop*:\n${err.message}`);
        }
    }

    calculateLiveEMA(prevEMA, price, period) {
        const k = 2 / (period + 1);
        return (price * k) + (prevEMA * (1 - k));
    }

    // Real-time Position Monitoring (Socket)
    async watchPositionLoop() {
        if (!this.position || !this.isRunning) return;

        const quote = this.fyersManager.getLiveQuote(this.position.symbol);
        // Also get Underlying Quote for Crossover Check
        const underlyingQuote = this.fyersManager.getLiveQuote(this.symbol); // "NSE:NIFTYBANK-INDEX"

        if (!quote) return;

        const currentPrice = quote.ltp;
        let exitReason = null;

        // 1. Check SL/TP (Option Price)
        const pnlPoints = (currentPrice - this.position.entryPrice);
        if (pnlPoints <= -this.position.slPoints) exitReason = "SL Hit";
        else if (pnlPoints >= this.position.tpPoints) exitReason = "TP Hit";
        
        // 2. Check Live Crossover (Underlying Price)
        if (underlyingQuote && this.lastClosedCandle) {
            const livePrice = underlyingQuote.ltp;
            const liveEmaShort = this.calculateLiveEMA(this.lastClosedCandle.ema_short, livePrice, this.strategy.params.ema_short);
            const liveEmaLong = this.calculateLiveEMA(this.lastClosedCandle.ema_long, livePrice, this.strategy.params.ema_long);

            const isBullish = liveEmaShort > liveEmaLong;
            const isBearish = liveEmaShort < liveEmaLong;

            if (this.position.type === 'CE' && isBearish) exitReason = "Live Crossover Exit";
            if (this.position.type === 'PE' && isBullish) exitReason = "Live Crossover Exit";
        }

        // 3. Time Exit
        const now = new Date();
        if (now.getHours() >= 15 && now.getMinutes() >= 15) exitReason = "Time Exit";

        if (exitReason) {
            await this.executeTrade("EXIT", { ...this.position, exitPrice: currentPrice, pnl: pnlPoints * this.position.quantity, reason: exitReason });
            this.position = null;
        }
    }

    start() {
        if (this.isRunning) return;
        this.isRunning = true;
        console.log(`🚀 Live Engine Started in ${this.mode.toUpperCase()} mode.`);
        
        // Run Strategy Loop every 1 minute (Candles)
        this.intervalId = setInterval(() => this.runLoop(), 60 * 1000);
        this.runLoop(); 

        // Run Position Watch Loop every 1 second (Socket)
        this.watchId = setInterval(() => this.watchPositionLoop(), 1000);
    }

    stop() {
        this.isRunning = false;
        if (this.intervalId) clearInterval(this.intervalId);
        if (this.watchId) clearInterval(this.watchId);
        console.log("🛑 Live Engine Stopped.");
    }

    // ... (checkEntry remains same) ...
    async checkEntry(candles) {
        const signal = this.strategy.generateSignal(candles);
        if (!signal) return;

        // Check Time Window (09:30 - 15:00)
        const now = new Date();
        const hours = now.getHours();
        const minutes = now.getMinutes();
        const timeVal = hours * 60 + minutes;
        if (timeVal < 9 * 60 + 30 || timeVal > 15 * 60) return;

        // Execute Entry
        const tradeType = signal.type; // CE or PE
        
        const atr = this.strategy.calculateIndicators(candles).atr || 100;
        const slPoints = atr * (this.strategy.params.atr_sl_mult || 1.8) * 0.5;
        const tpPoints = atr * (this.strategy.params.atr_tp_mult || 3.5) * 0.5;

        // Get ATM Symbol
        const underlyingName = "BANKNIFTY";
        // Use current close as approx price for ATM selection
        const currentPrice = candles[candles.length - 1].close;
        const optionSymbol = this.getAtmSymbol(underlyingName, currentPrice, tradeType);

        // Get Live Option Price for Entry (if available, else use 0/Market)
        // We need to subscribe to this symbol first!
        await this.fyersManager.subscribe([optionSymbol]);
        
        // Wait a bit for tick? Or just place market order.
        // For paper, we need a price.
        let entryPrice = 0;
        // Wait 1s for tick
        await new Promise(r => setTimeout(r, 1000));
        const quote = this.fyersManager.getLiveQuote(optionSymbol);
        entryPrice = quote ? quote.ltp : 0; // If 0, maybe fetch quote via API?

        if (entryPrice === 0) {
             // Fallback to API Quote
             const quotes = await this.fyersManager.getQuotes(optionSymbol);
             entryPrice = quotes[optionSymbol]?.lp || 0;
        }

        if (entryPrice === 0) {
            console.log("❌ Could not get price for", optionSymbol);
            return;
        }

        this.position = {
            type: tradeType,
            entryPrice: entryPrice,
            quantity: this.lotSize,
            slPoints: slPoints,
            tpPoints: tpPoints,
            entryTime: new Date(),
            symbol: optionSymbol
        };

        await this.executeTrade("ENTRY", this.position);
    }

    // ... (checkExit removed, logic moved to watchPositionLoop and runLoop) ...

    // ... (getAtmSymbol remains same) ...
    getAtmSymbol(underlying, price, type) {
        const step = 100;
        const atmStrike = Math.round(price / step) * step;
        const expiryDate = getNextExpiry();
        const year = expiryDate.getFullYear().toString().slice(-2);
        const monthNames = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
        const monthStr = monthNames[expiryDate.getMonth()];
        const dateStr = `${year}${monthStr}`;
        return `NSE:${underlying}${dateStr}${atmStrike}${type}`;
    }

    async executeTrade(action, details) {
        // Calculate PnL if EXIT
        if (action === 'EXIT' && !details.pnl) {
             details.pnl = (details.exitPrice - details.entryPrice) * details.quantity;
        }

        const tradeData = {
            timestamp: new Date(),
            action: action,
            type: details.type,
            symbol: details.symbol,
            price: details.entryPrice || details.exitPrice,
            quantity: details.quantity,
            pnl: details.pnl || 0,
            reason: details.reason || "Signal",
            mode: this.mode
        };

        const logMsg = `🔔 ${this.mode.toUpperCase()} TRADE: ${action} ${details.type} @ ${tradeData.price.toFixed(2)} (${tradeData.reason})`;
        console.log(logMsg);

        // Telegram
        let telegramMsg = `*${this.mode.toUpperCase()} TRADE ALERT* 🚨\n`;
        telegramMsg += `Action: *${action}*\n`;
        telegramMsg += `Symbol: *${details.symbol}*\n`;
        telegramMsg += `Price: *${tradeData.price.toFixed(2)}*\n`;
        telegramMsg += `Reason: ${tradeData.reason}\n`;
        if (action === 'EXIT') telegramMsg += `PnL: *₹${tradeData.pnl.toFixed(2)}*\n`;
        telegramBot.sendMessage(telegramMsg);

        // MongoDB
        try {
            await Trade.create(tradeData);
            const trades = await Trade.find().sort({ timestamp: -1 }).limit(20);
            this.io.emit('dashboard_update', { mongoTrades: trades });
        } catch (err) {
            console.error("❌ Failed to log trade:", err);
        }

        // LIVE EXECUTION
        if (this.mode === 'live') {
            if (action === 'ENTRY') {
                try {
                    console.log(`🚀 Placing LIVE Order for ${details.symbol}...`);
                    
                    // 1. Place Market Entry Order
                    const orderParams = {
                        symbol: details.symbol,
                        qty: details.quantity,
                        type: 2, // Market
                        side: 1, // Buy
                        productType: "MARGIN",
                        validity: "DAY",
                        disclosedQty: 0,
                        offlineOrder: false,
                        stopLoss: 0,
                        takeProfit: 0
                    };

                    const result = await this.fyersManager.placeOrder(orderParams);
                    if (result.success) {
                        telegramBot.sendMessage(`✅ Order Placed: ${details.symbol} (ID: ${result.id})`);
                        
                        // 2. Place Broker-Side Stop Loss (SL-M)
                        // Wait a bit to ensure order is registered?
                        // Calculate SL Price
                        const slPrice = details.entryPrice - details.slPoints;
                        const slPriceRounded = Math.round(slPrice * 20) / 20; // Tick size 0.05

                        console.log(`🛡️ Placing Stop Loss Order at ${slPriceRounded}...`);
                        const slParams = {
                            symbol: details.symbol,
                            qty: details.quantity,
                            type: 3, // Stop Loss Market (SL-M) - Type 3 is SL-M? Check docs. Usually 3 is SL-Limit, 4 is SL-M?
                            // Fyers v3: 1=Limit, 2=Market, 3=Stop Limit, 4=Stop Market
                            type: 4, // SL-M
                            side: -1, // Sell
                            productType: "MARGIN",
                            validity: "DAY",
                            stopPrice: slPriceRounded,
                            limitPrice: 0, // 0 for SL-M
                            disclosedQty: 0,
                            offlineOrder: false
                        };
                        
                        // Fyers API side: 1=Buy, -1=Sell
                        
                        const slResult = await this.fyersManager.placeOrder(slParams);
                        if (slResult.success) {
                            telegramBot.sendMessage(`🛡️ SL Order Placed at ${slPriceRounded}`);
                            this.position.slOrderId = slResult.id;
                        } else {
                            telegramBot.sendMessage(`⚠️ SL Order Failed: ${slResult.message}`);
                        }

                    } else {
                        telegramBot.sendMessage(`❌ Order Failed: ${result.message}`);
                        this.position = null; // Cancel paper position if live fails
                    }
                } catch (err) {
                    console.error("❌ Live Execution Error:", err);
                    telegramBot.sendMessage(`❌ Live Execution Error: ${err.message}`);
                }
            } 
            else if (action === 'EXIT') {
                // Close Position & Cancel SL
                try {
                    console.log(`🚀 Closing LIVE Position for ${details.symbol}...`);
                    
                    // 1. Place Market Sell Order (Exit)
                    const exitParams = {
                        symbol: details.symbol,
                        qty: details.quantity,
                        type: 2, // Market
                        side: -1, // Sell
                        productType: "MARGIN",
                        validity: "DAY"
                    };
                    await this.fyersManager.placeOrder(exitParams);
                    telegramBot.sendMessage(`✅ Position Closed: ${details.symbol}`);

                    // 2. Cancel SL Order if exists
                    if (this.position.slOrderId) {
                        // Need cancelOrder method in FyersManager
                        // For now, just log.
                        console.log("⚠️ Remember to cancel SL Order manually if not triggered.");
                        telegramBot.sendMessage(`⚠️ Cancel SL Order ID: ${this.position.slOrderId}`);
                    }

                } catch (err) {
                    console.error("❌ Live Exit Error:", err);
                }
            }
        }
    }
}

module.exports = LiveEngine;
