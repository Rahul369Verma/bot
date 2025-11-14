#
# FILENAME: yfinance_data.py
#
# (This is a new file, but it's based on the old 'data_fetcher.py')
#

import yfinance as yf
import pandas as pd
from typing import Dict

class YFinanceData:
    """
    Centralized class for fetching all historical and spot
    data from yfinance.
    Used by both the live bot (RealMarketData) and the BacktestEngine.
    """
    
    INDEX_TICKERS: Dict[str, str] = {
        "BANKNIFTY": "^NSEBANK",
        "NIFTY 50": "^NSEI"
    }

    def __init__(self):
        self.symbol_mapping = self.INDEX_TICKERS

    def get_ticker_for_index(self, index_name: str) -> str:
        """Gets the yfinance ticker (e.g., '^NSEI') for an index name (e.g., 'NIFTY 50')"""
        return self.symbol_mapping.get(index_name, index_name)

    def get_historical_data(self, index_name: str, period: str, interval: str, 
                            is_backtest_log: bool = False) -> pd.DataFrame:
        """
        Get REAL historical data from yfinance,
        localized to IST and filtered to market hours.
        """
        ticker_symbol = self.get_ticker_for_index(index_name)

        if is_backtest_log:
            print(f"🔄 Fetching REAL historical data for {ticker_symbol} ({period}, {interval})...")

        if interval != '1d' and period not in ['1d', '5d', '1mo', '60d']:
             if is_backtest_log:
                 print(f"Warning: yfinance Limitation: Intraday data is only available for the last 60 days. Your '{period}' request may be limited.")
        
        try:
            ticker = yf.Ticker(ticker_symbol)
            
            if period == "2mo":
                period = "60d" 
                if is_backtest_log:
                    print("Changed '2mo' to '60d' to respect yfinance limit.")
            
            data = ticker.history(period=period, interval=interval)
            
            if data.empty:
                print(f"No data returned from yfinance for {ticker_symbol} with period={period}, interval={interval}.")
                raise Exception("No data returned from yfinance. Cannot proceed.")

            # --- TIMEZONE AND MARKET HOURS FIX ---
            if data.index.tz is None:
                try: data.index = data.index.tz_localize('UTC')
                except Exception: pass
            try: data.index = data.index.tz_convert('Asia/Kolkata')
            except Exception: pass
            
            data = data.between_time('09:15', '15:20') # 15:20 to include 15:15 candle
            data.index = data.index.tz_localize(None)
            # --- END OF FIX ---
            
            data.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
            }, inplace=True)

            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                raise Exception(f"Fetched data is missing required columns: {required_cols}")

            data.dropna(subset=required_cols, inplace=True)
            
            if is_backtest_log:
                print(f"✅ Fetched and filtered {len(data)} real market candles (09:15-15:20 IST).")
            return data
        
        except Exception as e:
            print(f"❌ Failed to fetch REAL historical data: {e}")
            raise e

    def get_index_spot(self, index_name: str) -> float:
        """Get REAL Index spot price from yfinance"""
        try:
            ticker_symbol = self.get_ticker_for_index(index_name)
            ticker = yf.Ticker(ticker_symbol)
            
            data = ticker.history(period="1d", interval="1m") # Try 1m first
            if not data.empty:
                return float(data['Close'].iloc[-1])
            
            # Fallback for market close: get last day's close
            data = ticker.history(period="5d", interval="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
                
            raise Exception("Yahoo Finance data unavailable")
        except Exception as e:
            raise Exception(f"Failed to fetch {index_name} spot: {e}")