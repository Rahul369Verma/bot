import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import streamlit as st
from typing import Dict, List, Optional


class BacktestDataManager:
    """
    Manages backtesting data by fetching REAL historical data from yfinance.
    """
    
    def __init__(self):
        self.symbol_mapping = {
            'BANKNIFTY': '^NSEBANK',
            'NIFTY': '^NSEI', 
            'RELIANCE': 'RELIANCE.NS',
            'TCS': 'TCS.NS'
        }
    
    def get_backtest_data(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        """
        Get REAL historical data for backtesting from yfinance,
        localized to IST and filtered to market hours.
        """
        ticker_symbol = self.symbol_mapping.get(symbol, symbol)

        st.info(f"🔄 Fetching REAL historical data for {ticker_symbol} ({period}, {interval})...")

        if interval != '1d' and period not in ['1d', '5d', '1mo', '60d']:
             st.error(f"yfinance Limitation: Intraday data (15m, 30m, 1h) is only available for the last 60 days. Your '{period}' request will likely fail.")
        
        try:
            ticker = yf.Ticker(ticker_symbol)
            
            if period == "2mo":
                period = "60d" 
                st.info("Changed '2mo' to '60d' to respect yfinance limit.")
            
            data = ticker.history(period=period, interval=interval)
            
            if data.empty:
                st.error(f"No data returned from yfinance for {ticker_symbol} with period={period}, interval={interval}.")
                raise Exception("No data returned from yfinance. Backtest cannot proceed.")

            # --- NEW: TIMEZONE AND MARKET HOURS FIX ---
            
            # 1. Check if index is naive (it should be)
            if data.index.tz is None:
                # Localize the naive UTC timestamps from yfinance
                data.index = data.index.tz_localize('UTC')
            
            # 2. Convert to Indian Standard Time
            data.index = data.index.tz_convert('Asia/Kolkata')
            
            # 3. Filter to NSE market hours (9:15 to 15:30)
            data = data.between_time('09:15', '15:30')
            
            # 4. Make index naive again to simplify downstream processing
            data.index = data.index.tz_localize(None)
            
            # --- END OF FIX ---
            
            data.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
            }, inplace=True)

            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                raise Exception(f"Fetched data is missing required columns: {required_cols}")

            data.dropna(subset=required_cols, inplace=True)
            
            st.success(f"✅ Fetched and filtered {len(data)} real market candles (09:15-15:30 IST).")
            return data
        
        except Exception as e:
            st.error(f"❌ Failed to fetch REAL historical data: {e}")
            raise e