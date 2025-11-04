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
             st.error(f"yfinance Limitation: Intraday data is only available for the last 60 days. Your '{period}' request will likely fail.")
        
        try:
            ticker = yf.Ticker(ticker_symbol)
            
            if period == "2mo":
                period = "60d" 
                st.info("Changed '2mo' to '60d' to respect yfinance limit.")
            
            data = ticker.history(period=period, interval=interval)
            
            if data.empty:
                st.error(f"No data returned from yfinance for {ticker_symbol} with period={period}, interval={interval}.")
                raise Exception("No data returned from yfinance. Backtest cannot proceed.")

            # --- TIMEZONE AND MARKET HOURS FIX ---
            if data.index.tz is None:
                try: data.index = data.index.tz_localize('UTC')
                except Exception: pass
            
            try: data.index = data.index.tz_convert('Asia/Kolkata')
            except Exception: pass
            
            # --- UPDATED: Stop at 15:20 ---
            data = data.between_time('09:15', '15:20')
            
            data.index = data.index.tz_localize(None)
            # --- END OF FIX ---
            
            data.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
            }, inplace=True)

            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                raise Exception(f"Fetched data is missing required columns: {required_cols}")

            data.dropna(subset=required_cols, inplace=True)
            
            st.success(f"✅ Fetched and filtered {len(data)} real market candles (09:15-15:20 IST).")
            return data
        
        except Exception as e:
            st.error(f"❌ Failed to fetch REAL historical data: {e}")
            raise e