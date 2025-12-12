// backend/logic/utils/symbols.js

const BANKNIFTY_STOCKS = [
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", 
    "INDUSINDBK", "BANKBARODA", "PNB", "IDFCFIRSTB", "AUBANK", 
    "BANDHANBNK", "FEDERALBNK"
];

const NIFTY50_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", 
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "LICI", 
    "KOTAKBANK", "LT", "AXISBANK", "HCLTECH", "ASIANPAINT", 
    "MARUTI", "TITAN", "SUNPHARMA", "BAJFINANCE", "ULTRACEMCO", 
    "TATASTEEL", "NTPC", "POWERGRID", "M&M", "ADANIENT", 
    "ADANIPORTS", "COALINDIA", "TATAMOTORS", "BAJAJFINSV", "JSWSTEEL", 
    "GRASIM", "HINDALCO", "ONGC", "NESTLEIND", "WIPRO", 
    "TECHM", "BRITANNIA", "CIPLA", "HEROMOTOCO", "EICHERMOT", 
    "DRREDDY", "DIVISLAB", "APOLLOHOSP", "SBILIFE", "BPCL", 
    "TATACONSUM", "BAJAJ-AUTO", "INDUSINDBK", "UPL", "LTIM"
];

// Combine unique stocks
const ALL_STOCKS = [...new Set([...BANKNIFTY_STOCKS, ...NIFTY50_STOCKS])].sort();

// Fyers Symbol Map
const FYERS_INDEX_SYMBOL_MAP = {
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX", // Alias
    "FINNIFTY": "NSE:FINNIFTY-INDEX"
};

// Helper to get Fyers Symbol
const getFyersSymbol = (symbol) => {
    // Check if it's an index
    if (FYERS_INDEX_SYMBOL_MAP[symbol]) {
        return FYERS_INDEX_SYMBOL_MAP[symbol];
    }
    // Check if it's already in Fyers format
    if (symbol.startsWith("NSE:") || symbol.startsWith("MCX:")) {
        return symbol;
    }
    // Default to NSE Equity
    return `NSE:${symbol}-EQ`;
};

module.exports = {
    BANKNIFTY_STOCKS,
    NIFTY50_STOCKS,
    ALL_STOCKS,
    FYERS_INDEX_SYMBOL_MAP,
    getFyersSymbol
};
