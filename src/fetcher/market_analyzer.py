import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
from typing import List, Dict, Any, Optional

class MarketAnalyzer:
    """
    Analyzes market data to find signals based on the 5m/15m Daily Trend strategy.
    This class is now STATEFUL to track the daily trend.
    """
    def __init__(self):
        self.ema_short = 9
        self.ema_long = 15
        self.atr_period = 14 # ATR Period
        
        self.current_day = None
        self.daily_trend = 'NEUTRAL' # 'NEUTRAL', 'UP', 'DOWN'
        self.prev_aligned_bull = False
        self.prev_aligned_bear = False

    def _resample_to_15min(self, df_5min: pd.DataFrame) -> pd.DataFrame:
        """Resamples 5-minute data to 15-minute candles."""
        df_15min = df_5min.resample('15min').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        return df_15min

    def calculate_indicators(self, df_5min_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Calculates 5m and 15m indicators and merges them."""
        try:
            df_5m = df_5min_raw.copy()

            # --- TIMEZONE FIX ---
            if df_5m.index.tz is None:
                try: df_5m.index = df_5m.index.tz_localize('UTC')
                except Exception: pass
            try: df_5m.index = df_5m.index.tz_convert('Asia/Kolkata')
            except Exception: pass
            df_5m = df_5m.between_time('09:15', '15:30')
            df_5m.index = df_5m.index.tz_localize(None)
            # --- END FIX ---
            
            if df_5m.empty:
                print("No market data after filtering for 9:15-15:30.")
                return None
            
            # 1. Calculate 5m EMAs
            df_5m['ema_short'] = df_5m['Close'].ewm(span=self.ema_short, adjust=False).mean()
            df_5m['ema_long'] = df_5m['Close'].ewm(span=self.ema_long, adjust=False).mean()

            # --- NEW: Calculate 5m ATR ---
            df_5m['tr1'] = abs(df_5m['High'] - df_5m['Low'])
            df_5m['tr2'] = abs(df_5m['High'] - df_5m['Close'].shift(1))
            df_5m['tr3'] = abs(df_5m['Low'] - df_5m['Close'].shift(1))
            df_5m['true_range'] = df_5m[['tr1', 'tr2', 'tr3']].max(axis=1)
            df_5m['atr'] = df_5m['true_range'].rolling(window=self.atr_period).mean().bfill()
            df_5m['atr'] = df_5m['atr'].ewm(alpha=1/self.atr_period, adjust=False).mean()
            # --- END ATR ---

            # 2. Resample to 15m
            df_15m = self._resample_to_15min(df_5m)
            if df_15m.empty:
                df_5m['ema_short_15m'] = np.nan
                df_5m['ema_long_15m'] = np.nan
            else:
                df_15m['ema_short_15m'] = df_15m['Close'].ewm(span=self.ema_short, adjust=False).mean()
                df_15m['ema_long_15m'] = df_15m['Close'].ewm(span=self.ema_long, adjust=False).mean()
            
                # 3. Map 15m trend info back to 5m df
                df_5m['15m_timestamp'] = df_5m.index.floor('15min')
                df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], 
                                 left_on='15m_timestamp', 
                                 right_index=True,        
                                 how='left', suffixes=('', '_15m'))
            
            df_5m[['ema_short_15m', 'ema_long_15m']] = df_5m[['ema_short_15m', 'ema_long_15m']].ffill().bfill()
            
            return df_5m
        except Exception as e:
            print(f"Error calculating indicators: {e}")
            return None

    def generate_trading_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Checks the LATEST candle for a trade signal based on the daily trend strategy.
        Returns a single signal or None.
        """
        
        try: today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        except: today = datetime.now().date() 

        if self.current_day != today:
            self.current_day = today
            self.daily_trend = 'NEUTRAL'
            self.prev_aligned_bull = False
            self.prev_aligned_bear = False
            print(f"--- New Day ({today}): Trend reset to NEUTRAL ---")

        df_5m = self.calculate_indicators(historical_data)
        if df_5m is None or df_5m.empty:
            return None

        current_5m = df_5m.iloc[-1]

        # --- Check for ATR as well ---
        if pd.isna(current_5m['ema_short']) or pd.isna(current_5m['ema_long']) or \
           pd.isna(current_5m['ema_short_15m']) or pd.isna(current_5m['ema_long_15m']) or \
           pd.isna(current_5m['atr']):
            return None # Not enough data yet

        if self.daily_trend == 'NEUTRAL':
            is_15m_uptrend = current_5m['ema_short_15m'] > current_5m['ema_long_15m']
            is_15m_downtrend = current_5m['ema_short_15m'] < current_5m['ema_long_15m']
            
            if is_15m_uptrend:
                self.daily_trend = 'UP'
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: UP")
            elif is_15m_downtrend:
                self.daily_trend = 'DOWN'
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: DOWN")
        
        is_5m_bullish = current_5m['ema_short'] > current_5m['ema_long']
        is_5m_bearish = current_5m['ema_short'] < current_5m['ema_long']

        currently_aligned_bull = (self.daily_trend == 'UP') and is_5m_bullish
        currently_aligned_bear = (self.daily_trend == 'DOWN') and is_5m_bearish

        signal_to_fire = None

        if currently_aligned_bull and not self.prev_aligned_bull:
            signal_to_fire = {
                "signal": "BUY", "type": "CE",
                "price": current_5m['Close'],
                "strike": int(round(current_5m['Close'] / 100.0) * 100),
                "reason": "5m-Bull aligns with Daily-UP-Trend",
                "atr": current_5m['atr'] # --- NEW: Pass the ATR value ---
            }
        
        elif currently_aligned_bear and not self.prev_aligned_bear:
            signal_to_fire = {
                "signal": "BUY", "type": "PE",
                "price": current_5m['Close'],
                "strike": int(round(current_5m['Close'] / 100.0) * 100),
                "reason": "5m-Bear aligns with Daily-DOWN-Trend",
                "atr": current_5m['atr'] # --- NEW: Pass the ATR value ---
            }

        self.prev_aligned_bull = currently_aligned_bull
        self.prev_aligned_bear = currently_aligned_bear

        return signal_to_fire