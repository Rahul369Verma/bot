const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');
const axios = require('axios');
const http = require('http');
const { Server } = require('socket.io');
require('dotenv').config({ path: '../.env' });

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: "*", // Allow all for now, lock down in prod
    methods: ["GET", "POST"]
  }
});

const PORT = process.env.PORT || 5000;
const PYTHON_API_URL = 'http://localhost:8000';

// Middleware
app.use(cors());
app.use(express.json());

// Define Trade Schema (Read-only view of what Python writes)
const TradeSchema = new mongoose.Schema({}, { strict: false, collection: 'trade_history' });
const Trade = mongoose.model('Trade', TradeSchema);

// Define Log Schema
const LogSchema = new mongoose.Schema({
    timestamp: Date,
    level: String,
    message: String,
    module: String
}, { collection: 'logs' });
const Log = mongoose.model('Log', LogSchema);


// --- Routes ---

const BacktestEngine = require('./logic/engine/backtestEngine');

// Initialize Logic Engine
// --- Fyers Client ---
// --- Fyers Client ---
const FyersDataManager = require("./logic/fetcher/fyersData");
const fyersManager = new FyersDataManager();
const { calculateIndicators } = require('./logic/utils/indicators');

// --- Global Cache ---
let globalCache = {
    status: {},
    marketData: {},
    pnl: {},
    positions: [],
    optionChain: [],
    mongoTrades: [],
    lastUpdated: 0,
    emaData: { ema_9: 0, ema_15: 0, trend: "NEUTRAL" } // Store calculated EMAs
};

// MongoDB Connection
// Reuse existing MONGO_URI from .env
// MongoDB Connection
// Construct URI from components if MONGO_URI is missing
const MONGO_URI = process.env.MONGO_URI || 
                 (process.env.MONGO_USERNAME && process.env.MONGO_PASSWORD 
                  ? `mongodb+srv://${encodeURIComponent(process.env.MONGO_USERNAME)}:${encodeURIComponent(process.env.MONGO_PASSWORD)}@cluster0.55uxt6z.mongodb.net/trading_bot?retryWrites=true&w=majority`
                  : 'mongodb://localhost:27017/trading_bot');

const connectDB = async () => {
    try {
        await mongoose.connect(MONGO_URI);
        console.log('✅ MongoDB Connected');
    } catch (err) {
        console.error('❌ MongoDB Auth Connection Error:', err.message);
        // Fallback to no-auth if auth failed
        if (process.env.MONGO_USERNAME) {
            console.log('⚠️ Retrying MongoDB connection without credentials...');
            try {
                await mongoose.connect('mongodb://localhost:27017/trading_bot');
                console.log('✅ MongoDB Connected (No Auth)');
            } catch (retryErr) {
                console.error('❌ MongoDB Fallback Error:', retryErr.message);
            }
        }
    }
};
connectDB();

// Helper: Fetch & Calculate EMAs (Runs every 5 mins)
const updateEMAs = async () => {
    if (!fyersManager.isAuthenticated()) return;
    try {
        const symbol = "NSE:NIFTYBANK-INDEX";
        const now = new Date();
        const fromDate = new Date(now.getTime() - 5 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]; // Last 5 days
        const toDate = now.toISOString().split('T')[0];

        // Fetch 5m data
        const candles = await fyersManager.getHistory(symbol, "5", fromDate, toDate);
        if (candles && candles.length > 20) {
            const processed = calculateIndicators(candles, 9, 15);
            const lastCandle = processed[processed.length - 1];
            
            // Check if last candle is completed (simple check: if current time > candle time + 5m)
            // Or just use the last available candle's EMA as the "current" trend baseline
            if (lastCandle && lastCandle.ema_short && lastCandle.ema_long) {
                const ema_9 = lastCandle.ema_short;
                const ema_15 = lastCandle.ema_long;
                const trend = ema_9 > ema_15 ? "BULLISH" : "BEARISH";
                
                globalCache.emaData = { ema_9, ema_15, trend };
                console.log(`✅ Updated EMAs: EMA9=${ema_9.toFixed(2)}, EMA15=${ema_15.toFixed(2)}, Trend=${trend}`);
            }
        }
    } catch (err) {
        console.error("❌ Error updating EMAs:", err.message);
    }
};

// Run EMA update every 5 minutes
setInterval(updateEMAs, 5 * 60 * 1000);
// Also run once on startup (after a small delay to allow auth)
setTimeout(updateEMAs, 5000);

// Background Data Fetcher (Runs every 2 seconds)
// Background Data Fetcher (Recursive setTimeout to avoid overlap)
const runBackgroundLoop = async () => {
    try {
        // 1. Status
        globalCache.status = {
            is_running: true,
            fyers_connected: fyersManager.isAuthenticated(),
            fyers_app_id: process.env.FYERS_APP_ID,
            fyers_redirect_url: process.env.FYERS_REDIRECT_URL,
            active_strategy: "MTA Crossover (Fyers Only)",
            max_daily_loss: 2000,
            max_trades: 10,
            trades_today: 0, // Need to implement trade tracking in FyersManager
            lot_size: 35,
            strategy_params: {
                ema_short: 5,
                ema_long: 7,
                use_adx: true,
                adx_threshold: 26,
                use_rsi: true,
                rsi_overbought: 85,
                rsi_oversold: 24,
                atr_tp_mult: 3.5,
                atr_sl_mult: 1.8,
                lot_size: 35,
                trade_start_time: "09:30",
                trade_end_time: "15:00",
                max_daily_loss: 2000,
                max_trades_per_day: 10
            }
        };

        // 2. Market Data (From Fyers Socket Cache)
        // Ensure we are subscribed
        if (fyersManager.isAuthenticated() && !fyersManager.isSocketConnected) {
             await fyersManager.connectWebSocket();
             await fyersManager.subscribe(["NSE:NIFTYBANK-INDEX"]); // Subscribe to Index
        }

        const ltpData = fyersManager.getLiveQuote("NSE:NIFTYBANK-INDEX");
        let ltp = ltpData ? ltpData.ltp : 0;

        // Fallback: If Socket LTP is 0, try fetching via API (throttled)
        if (ltp === 0 && fyersManager.isAuthenticated()) {
             const now = Date.now();
             // Use last valid LTP if available to avoid 0 flickering
             if (globalCache.lastValidLtp) {
                 ltp = globalCache.lastValidLtp;
             }

             if (!globalCache.lastLtpFetch || now - globalCache.lastLtpFetch > 5000) {
                 console.log("⚠️ Socket LTP missing. Fetching via API...");
                 globalCache.lastLtpFetch = now; // Update timestamp BEFORE fetch to prevent overlap
                 
                 const quotes = await fyersManager.getQuotes("NSE:NIFTYBANK-INDEX");
                 // console.log("🔍 Fallback Quote Response:", quotes ? Object.keys(quotes) : "null");
                 if (quotes && quotes["NSE:NIFTYBANK-INDEX"]) {
                     ltp = quotes["NSE:NIFTYBANK-INDEX"].lp;
                     globalCache.lastValidLtp = ltp; // Persist valid LTP
                 }
             }
        } else if (ltp > 0) {
            globalCache.lastValidLtp = ltp; // Update valid LTP from socket
        }

        // Use calculated EMAs
        globalCache.marketData = {
            symbol: "BANKNIFTY",
            ltp: ltp,
            ema_9: globalCache.emaData.ema_9,
            ema_15: globalCache.emaData.ema_15,
            trend: globalCache.emaData.trend,
            timestamp: new Date().toISOString()
        };

        // 3. P&L (Mock for now, implement real P&L later)
        globalCache.pnl = {
            daily_pnl: 0,
            trades_count: 0,
            total_investment: 0,
            current_value: 0,
            unrealized_pnl: 0
        };

        // 4. Positions (Fetch from Fyers API - Rate Limited, so maybe cache this longer?)
        // For now, let's just return empty or fetch every 10s
        // globalCache.positions = await fyersManager.getPositions(); 

        // 5. Option Chain (Real Data via Socket)
        if (ltp > 0) {
            const { getOptionSymbols } = require('./logic/utils/optionChain');
            const optionSymbols = getOptionSymbols("BANKNIFTY", ltp, 8, 100); // 8 strikes up/down
            
            // Manage Subscriptions
            if (!globalCache.currentOptionSymbols) globalCache.currentOptionSymbols = [];
            
            // Identify symbols to subscribe (new ones)
            const toSubscribe = optionSymbols.filter(s => !globalCache.currentOptionSymbols.includes(s));
            
            // Identify symbols to unsubscribe (old ones no longer needed)
            const toUnsubscribe = globalCache.currentOptionSymbols.filter(s => !optionSymbols.includes(s));
            
            if (toSubscribe.length > 0) {
                // console.log(`➕ Subscribing to ${toSubscribe.length} new option symbols...`);
                fyersManager.subscribe(toSubscribe);
            }
            
            if (toUnsubscribe.length > 0) {
                // console.log(`➖ Unsubscribing from ${toUnsubscribe.length} old option symbols...`);
                fyersManager.unsubscribe(toUnsubscribe);
            }
            
            // Update current list
            globalCache.currentOptionSymbols = optionSymbols;

            // Build Chain from Socket Cache
            const chain = [];
            optionSymbols.forEach(sym => {
                const q = fyersManager.getLiveQuote(sym);
                // Parse symbol details
                const type = sym.endsWith('CE') ? 'CE' : 'PE';
                const match = sym.match(/(\d{5})(CE|PE)$/);
                const strike = match ? parseInt(match[1]) : 0;

                if (q) {
                    chain.push({
                        strike: strike,
                        type: type,
                        tradingsymbol: sym,
                        ltp: q.ltp || 0,
                        oi: 0, // Socket might not have OI, need to check 'vol' or 'oi' if available in 'ch'
                        iv: 0
                    });
                } else {
                    // Placeholder if no data yet
                    chain.push({
                        strike: strike,
                        type: type,
                        tradingsymbol: sym,
                        ltp: 0,
                        oi: 0,
                        iv: 0
                    });
                }
            });
            // Sort by strike
            globalCache.optionChain = chain.sort((a, b) => a.strike - b.strike);
            
        } else {
             globalCache.optionChain = []; 
             if (globalCache.currentOptionSymbols && globalCache.currentOptionSymbols.length > 0) {
                 fyersManager.unsubscribe(globalCache.currentOptionSymbols);
                 globalCache.currentOptionSymbols = [];
             }
        } 
        
        // 6. Mongo Trades (Mock or Real)
        globalCache.mongoTrades = await Trade.find().sort({ timestamp: -1 }).limit(20);

        globalCache.lastUpdated = Date.now();
        
        // Emit Update via Socket.IO
        io.emit('dashboard_update', globalCache);

    } catch (err) {
        console.error("❌ Cache Update Error:", err.message);
    } finally {
        // Schedule next run
        setTimeout(runBackgroundLoop, 2000);
    }
};

// Start the loop
runBackgroundLoop();

// --- Routes ---

// 1. Consolidated Dashboard Endpoint
app.get('/api/engine/dashboard', (req, res) => {
    res.json(globalCache);
});

// 1. Authentication
app.get('/api/auth/fyers/url', (req, res) => {
    const url = fyersManager.getLoginUrl();
    res.json({ url });
});

app.post('/api/auth/fyers/callback', async (req, res) => {
    const { auth_code } = req.body;
    if (!auth_code) return res.status(400).json({ error: "Missing auth_code" });
    
    const success = await fyersManager.generateToken(auth_code);
    if (success) {
        res.json({ message: "Authenticated successfully" });
    } else {
        res.status(500).json({ error: "Authentication failed" });
    }
});

app.post('/api/auth/fyers/delete-token', (req, res) => {
    fyersManager.corruptToken();
    res.json({ message: "Token corrupted for testing refresh flow" });
});

// Initialize Logic Engine
const LiveEngine = require('./logic/engine/liveEngine');
const liveEngine = new LiveEngine(fyersManager, io);

// 2. Bot Control & Status
app.get('/api/engine/status', (req, res) => {
    // Update status with running state
    globalCache.status.is_running = liveEngine.isRunning;
    res.json(globalCache.status);
});

app.post('/api/engine/bot/start', (req, res) => { 
    // Sync Strategy Params
    if (globalCache.status.strategy_params) {
        Object.assign(liveEngine.strategy.params, globalCache.status.strategy_params);
        console.log("🔄 Synced Strategy Params:", liveEngine.strategy.params);
    }
    
    liveEngine.start();
    globalCache.status.is_running = true;
    res.json({ message: "Bot started" }); 
});

app.post('/api/engine/bot/stop', (req, res) => { 
    liveEngine.stop();
    globalCache.status.is_running = false;
    res.json({ message: "Bot stopped" }); 
});

// 3. Market Data & Dashboard
app.get('/api/engine/market-data/:symbol', async (req, res) => {
    res.json(globalCache.marketData);
});

app.get('/api/engine/option-chain/:symbol', async (req, res) => {
    res.json(globalCache.optionChain);
});

app.get('/api/engine/mongo-trades', async (req, res) => {
    res.json(globalCache.mongoTrades);
});

app.get('/api/engine/positions', (req, res) => {
    res.json(globalCache.positions);
});

app.get('/api/engine/trades', (req, res) => {
    // Return closed trades
    res.json(globalCache.positions.filter(p => p.status === 'CLOSED')); // Mock
});

app.post('/api/engine/manual-trade', (req, res) => {
    const { type } = req.body; // CE or PE
    // angelClient.executeTrade({ signal: "BUY", type: type, price: 45000 });
    res.json({ message: `Manual ${type} trade executed (Mock)` });
});

// 4. P&L
app.get('/api/engine/pnl', (req, res) => {
    res.json(globalCache.pnl);
});

// 5. Backtest

// 5. Backtest
// 5. Backtest
app.post('/api/engine/backtest/run', async (req, res) => {
    try {
        const { symbol, start_date, end_date, interval, capital, strategy } = req.body;
        
        // Instantiate Engine
        const backtestEngine = new BacktestEngine();
        
        // Run Backtest
        // Note: interval param is ignored in current logic as it enforces MTA (5m, 15m, 60m), 
        // but we can pass it if we want to make it dynamic later.
        const result = await backtestEngine.run(symbol, start_date, end_date, capital, strategy, req.body);
        
        res.json(result);
    } catch (err) {
        console.error("❌ Backtest Error:", err);
        res.status(500).json({ error: err.message });
    }
});

// 6. Market Optimizer
const MarketOptimizer = require('./logic/engine/marketOptimizer');
app.post('/api/engine/optimizer/analyze', async (req, res) => {
    try {
        const { symbol } = req.body; // e.g., "NSE:NIFTYBANK-INDEX"
        if (!symbol) return res.status(400).json({ error: "Symbol is required" });

        const optimizer = new MarketOptimizer();
        const result = await optimizer.analyze(symbol, req.body);
        
        res.json(result);
    } catch (err) {
        console.error("❌ Optimizer Error:", err);
        res.status(500).json({ error: err.message });
    }
});

// 2. Direct Database Access (Logs/Trades)
// Schemas moved to top

app.get('/api/logs', async (req, res) => {
    try {
        const limit = parseInt(req.query.limit) || 50;
        const logs = await Log.find().sort({ timestamp: -1 }).limit(limit);
        res.json(logs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/api/trades', async (req, res) => {
    res.json(globalCache.mongoTrades);
});

// Socket.IO for Real-time updates (Optional: Polling is easier for now)
io.on('connection', (socket) => {
  console.log('Client connected');
  socket.on('disconnect', () => console.log('Client disconnected'));
});

// Start Server
server.listen(PORT, () => {
  console.log(`🚀 Node.js Backend running on port ${PORT}`);
});
