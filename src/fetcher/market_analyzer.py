import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
from typing import List, Dict, Any, Optional

class MarketAnalyzer:
    """
    Analyzes market data using the Multi-Timeframe (MTA) Strategy.
    """
    def __init__(self):
        self.ema_short = 9
        self.ema_long = 15
        self.atr_period = 30 
        
        self.current_day = None
        self.daily_trend = 'NEUTRAL'
        self.prev_aligned_bull = False
        self.prev_aligned_bear = False

    def _resample_data(self, df_5min: pd.DataFrame, rule: str) -> pd.DataFrame:
        """Resamples 5-minute data to a higher timeframe."""
        df_resampled = df_5min.resample(rule).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        return df_resampled

    def calculate_indicators(self, df_5min_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Calculates 5m, 15m, and 1h indicators and merges them."""
        try:
            df_5m = df_5min_raw.copy()

            if df_5m.index.tz is None:
                try: df_5m.index = df_5m.index.tz_localize('Asia/Kolkata') # yfinance data is naive but represents IST
                except Exception: pass
            else:
                try: df_5m.index = df_5m.index.tz_convert('Asia/Kolkata')
                except Exception: pass
            
            # --- UPDATED: Stop at 15:20 ---
            df_5m = df_5m.between_time('09:15', '15:20')
            
            df_5m.index = df_5m.index.tz_localize(None)
            
            if df_5m.empty:
                print("No market data after filtering for 9:15-15:20.")
                return None
            
            # ... (rest of indicator calculation is unchanged) ...
            df_5m['ema_short'] = df_5m['Close'].ewm(span=self.ema_short, adjust=False).mean()
            df_5m['ema_long'] = df_5m['Close'].ewm(span=self.ema_long, adjust=False).mean()
            df_5m['tr1'] = abs(df_5m['High'] - df_5m['Low'])
            df_5m['tr2'] = abs(df_5m['High'] - df_5m['Close'].shift(1))
            df_5m['tr3'] = abs(df_5m['Low'] - df_5m['Close'].shift(1))
            df_5m['true_range'] = df_5m[['tr1', 'tr2', 'tr3']].max(axis=1)
            df_5m['atr'] = df_5m['true_range'].rolling(window=self.atr_period).mean().bfill()
            df_5m['atr'] = df_5m['atr'].ewm(alpha=1/self.atr_period, adjust=False).mean()
            df_15m = self._resample_data(df_5m, '15min')
            if df_15m.empty:
                df_5m['ema_short_15m'] = np.nan; df_5m['ema_long_15m'] = np.nan
            else:
                df_15m['ema_short_15m'] = df_15m['Close'].ewm(span=self.ema_short, adjust=False).mean()
                df_15m['ema_long_15m'] = df_15m['Close'].ewm(span=self.ema_long, adjust=False).mean()
            df_1h = self._resample_data(df_5m, '1h')
            if df_1h.empty:
                df_5m['ema_short_1h'] = np.nan; df_5m['ema_long_1h'] = np.nan
            else:
                df_1h['ema_short_1h'] = df_1h['Close'].ewm(span=self.ema_short, adjust=False).mean()
                df_1h['ema_long_1h'] = df_1h['Close'].ewm(span=self.ema_long, adjust=False).mean()
            df_5m['15m_timestamp'] = df_5m.index.floor('15min')
            df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], 
                             left_on='15m_timestamp', right_index=True, how='left', suffixes=('', '_15m'))
            df_5m['1h_timestamp'] = df_5m.index.floor('1h')
            df_5m = pd.merge(df_5m, df_1h[['ema_short_1h', 'ema_long_1h']], 
                             left_on='1h_timestamp', right_index=True, how='left', suffixes=('', '_1h'))
            df_5m[['ema_short_15m', 'ema_long_15m']] = df_5m[['ema_short_15m', 'ema_long_15m']].ffill().bfill()
            df_5m[['ema_short_1h', 'ema_long_1h']] = df_5m[['ema_short_1h', 'ema_long_1h']].ffill().bfill()
            
            return df_5m
        except Exception as e:
            print(f"Error calculating indicators: {e}")
            return None

    def generate_trading_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        # ... (no change in this function) ...
        try: today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        except: today = datetime.now().date() 
        if self.current_day != today:
            self.current_day = today; self.daily_trend = 'NEUTRAL'
            self.prev_aligned_bull = False; self.prev_aligned_bear = False
            print(f"--- New Day ({today}): Trend reset to NEUTRAL ---")
        df_5m = self.calculate_indicators(historical_data)
        if df_5m is None or df_5m.empty or len(df_5m) < 2: return None
        current = df_5m.iloc[-1]; prev = df_5m.iloc[-2]
        if pd.isna(current['ema_short']) or pd.isna(current['ema_short_15m']) or pd.isna(current['ema_short_1h']) or pd.isna(prev['ema_short']): return None
        if self.daily_trend == 'NEUTRAL':
            is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
            is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
            if is_15m_uptrend: self.daily_trend = 'UP'; print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: UP")
            elif is_15m_downtrend: self.daily_trend = 'DOWN'; print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: DOWN")
        is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']
        is_1h_downtrend = current['ema_short_1h'] < current['ema_long_1h']
        is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
        is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
        is_5m_bullish_cross = (current['ema_short'] > current['ema_long']) and (prev['ema_short'] <= prev['ema_long'])
        is_5m_bearish_cross = (current['ema_short'] < current['ema_long']) and (prev['ema_short'] >= prev['ema_long'])
        signal_to_fire = None
        if is_5m_bullish_cross and is_15m_uptrend and is_1h_uptrend:
            signal_to_fire = {"signal": "BUY", "type": "CE", "price": current['Close'], "strike": int(round(current['Close'] / 100.0) * 100), "reason": "MTA: 5m Cross UP (15m/1h UP)", "atr": current['atr']}
        elif is_5m_bearish_cross and is_15m_downtrend and is_1h_downtrend:
            signal_to_fire = {"signal": "BUY", "type": "PE", "price": current['Close'], "strike": int(round(current['Close'] / 100.0) * 100), "reason": "MTA: 5m Cross DOWN (15m/1h DOWN)", "atr": current['atr']}
        # We no longer use prev_aligned_bull/bear, this is a crossover strategy now
        return signal_to_fire