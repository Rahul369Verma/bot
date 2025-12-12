const mongoose = require('mongoose');
const AngelClient = require('../logic/fetcher/angelClient');
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

async function verifyConnections() {
    console.log("🔍 Starting Backend Verification...");

    // 1. MongoDB Connection
    const MONGO_URI = process.env.MONGO_URI || 
                 (process.env.MONGO_USERNAME && process.env.MONGO_PASSWORD 
                  ? `mongodb://${process.env.MONGO_USERNAME}:${process.env.MONGO_PASSWORD}@localhost:27017/trading_bot?authSource=admin`
                  : 'mongodb://localhost:27017/trading_bot');
    
    try {
        await mongoose.connect(MONGO_URI);
        console.log("✅ MongoDB: Connected");
    } catch (err) {
        console.error("❌ MongoDB: Connection Failed", err.message);
    }

    // 2. Initialize AngelClient
    const angelClient = new AngelClient(true, "BANKNIFTY");
    
    // 3. Check Angel One Session
    // Note: initSession is async but called in constructor without await. 
    // We should wait a bit or call it explicitly if we want to verify.
    // Let's call it again to be sure.
    console.log("⏳ Verifying Angel One...");
    await angelClient.initSession();

    // 4. Check Fyers Authentication
    console.log("⏳ Verifying Fyers...");
    if (angelClient.fyersManager.isAuthenticated()) {
        console.log("✅ Fyers: Authenticated (Token Loaded)");
        
        // 5. Fetch Real Data (LTP)
        const symbols = ["NSE:NIFTYBANK-INDEX", "NSE:SBIN-EQ"];
        console.log(`Attempting to fetch quotes for: ${symbols.join(',')}`);
        
        try {
            const quotes = await angelClient.fyersManager.getQuotes(symbols.join(','));
            console.log("Quotes Response:", JSON.stringify(quotes, null, 2));
            
            const ltp = quotes["NSE:NIFTYBANK-INDEX"]?.lp || quotes["NSE:SBIN-EQ"]?.lp || 0;
            console.log(`📈 LTP: ${ltp}`);
        } catch (e) {
            console.error("❌ Quote Fetch Failed:", e);
        }

        // 6. Fetch Positions
        const positions = await angelClient.getPositions();
        console.log(`📊 Positions: ${positions.length} found`);

    } else {
        console.log("⚠️ Fyers: Not Authenticated (Login required via Frontend)");
        console.log("   Login URL:", angelClient.fyersManager.getLoginUrl());
    }

    // 7. Check Trade History (MongoDB)
    // We need to define the model here as it's not exported from server.js
    const TradeSchema = new mongoose.Schema({}, { strict: false, collection: 'trades' });
    const Trade = mongoose.models.Trade || mongoose.model('Trade', TradeSchema);
    
    const trades = await Trade.find().limit(5);
    console.log(`📜 Trade History: ${trades.length} trades found in DB`);

    console.log("✅ Verification Complete.");
    process.exit(0);
}

verifyConnections();
