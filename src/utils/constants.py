# src/utils/constants.py

BANKNIFTY_STOCKS = [
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", 
    "INDUSINDBK", "BANKBARODA", "PNB", "IDFCFIRSTB", "AUBANK", 
    "BANDHANBNK", "FEDERALBNK"
]

NIFTY50_STOCKS = [
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
]

# Combine all unique stocks
ALL_STOCKS = sorted(list(set(BANKNIFTY_STOCKS + NIFTY50_STOCKS)))

# Lot Size Mapping
LOT_SIZE_MAP = {
    "BANKNIFTY": 35, # User specified
    "NIFTY 50": 75,  # User specified
}
# Default for stocks (can be updated as needed)
for stock in ALL_STOCKS:
    LOT_SIZE_MAP[stock] = 1 # Default to 1 for stocks as options vary widely
