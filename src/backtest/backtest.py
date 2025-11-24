# Modified: src/backtest/backtest.py
# - Added ADX and RSI filters to MultiTimeframeStrategy
# - New params: use_adx_filter, adx_period, adx_threshold
# - New params: use_rsi_filter, rsi_period, rsi_overbought, rsi_oversold
# - Updated calculate_indicators, generate_signals, and generate_live_signal

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time, date
from typing import List, Dict, Any, Optional
import json
import streamlit as st
from zoneinfo import ZoneInfo 
import pandas_ta as ta
import calendar

# --- Import FyersDataManager ---
try:
    from fetcher.fyers_data import FyersDataManager
except ImportError:
    print("CRITICAL: backtest.py failed to import 'from fetcher.fyers_data import FyersDataManager'")
    pass

try:
    from ml.predictor import PricePredictor
except ImportError:
    print("Warning: Could not import PricePredictor in backtest.py")
    pass

class BacktestResult:
    # ... (no changes) ...
    def __init__(self, total_trades: int, winning_trades: int, losing_trades: int, win_rate: float,
                 total_pnl: float, max_drawdown: float, sharpe_ratio: float, profit_factor: float,
                 avg_trade_pnl: float, best_trade: float, worst_trade: float, avg_winning_trade: float,
                 avg_losing_trade: float, total_days: int, daily_return_avg: float, trade_details: List[Dict],
                 equity_curve: pd.DataFrame, signals_generated: List[Dict], monthly_returns: Dict[str, float],
                 strategy_name: str, parameters: Dict):
        self.total_trades=total_trades; self.winning_trades=winning_trades; self.losing_trades=losing_trades; self.win_rate=win_rate
        self.total_pnl=total_pnl; self.max_drawdown=max_drawdown; self.sharpe_ratio=sharpe_ratio; self.profit_factor=profit_factor
        self.avg_trade_pnl=avg_trade_pnl; self.best_trade=best_trade; self.worst_trade=worst_trade; self.avg_winning_trade=avg_winning_trade
        self.avg_losing_trade=avg_losing_trade; self.total_days=total_days; self.daily_return_avg=daily_return_avg
        self.trade_details=trade_details; self.equity_curve=equity_curve; self.signals_generated=signals_generated
        self.monthly_returns=monthly_returns; self.strategy_name=strategy_name; self.parameters=parameters

class StrategyTemplate:
    # ... (no changes) ...
    def __init__(self, name: str, description: str = ""): self.name=name; self.description=description; self.parameters={}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: raise NotImplementedError
    def calculate_indicators(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: raise NotImplementedError

# --- NEW: Upgraded MultiTimeframeStrategy ---
class MultiTimeframeStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__(
            name="MTA (5m) EMA Crossover", 
            description="Trades 5m EMA Crossover, aligned with 15m/1h trends. Fetches 5m/15m/1h data directly from Fyers."
        )
        self.parameters = {
            'ema_short': 9, 'ema_long': 15,
            'atr_period': 14, 'adx_period': 14, 'rsi_period': 5,
            
            # Filters (Enabled by Default)
            'use_adx_filter': False, 'adx_threshold': 20,
            'use_rsi_filter': True, 'rsi_overbought': 70, 'rsi_oversold': 30,
            
            # --- NEW: Expiry Filter ---
            'skip_last_week_expiry': True,
            
            # --- NEW: Candle Size Filter ---
            'use_candle_size_filter': True,
            'candle_size_period': 10,
            'candle_size_factor': 1.0,
            
            # Risk params
            'lot_size': 35, 'min_investment': 10000, 
            'max_daily_loss': 2000, 'max_trades_per_day': 10,
            'trade_start_time': time(9, 30), 'trade_end_time': time(14, 0),
            
            # SL/TP
            'sl_mode': 'ATR', 'invested_value_sl_pct': 5.0, 'tp_sl_ratio': 2.0,
            'atr_tp_multiplier': 4.0, 'atr_sl_multiplier': 1.4,
            
            # Sim params
            'simulated_premium_pct': 0.008, 'simulated_delta': 0.5,
        }
        self.IST = ZoneInfo('Asia/Kolkata')
        self.current_day = None
        self.daily_trend = 'NEUTRAL'
        self.trend_predictor = None # AI Trend Model

    def set_trend_predictor(self, predictor):
        self.trend_predictor = predictor

    def _get_last_wednesday(self, year: int, month: int) -> date:
        """Finds the last Wednesday of a given month and year."""
        last_day = calendar.monthrange(year, month)[1]
        last_day_date = date(year, month, last_day)
        last_day_weekday = last_day_date.weekday() # Mon=0, Wed=2
        days_to_subtract = (last_day_weekday - 2 + 7) % 7
        return last_day_date - timedelta(days=days_to_subtract)

    def _is_last_week_of_expiry(self, current_dt: datetime) -> bool:
        """
        Checks if the date is within the restricted period before expiry.
        - Monthly Expiry: Skip last 7 days (Thu-Wed).
        - Weekly Expiry: Skip last 2 days (Tue-Wed).
        """
        current_date = current_dt.date()
        
        # 1. Find the next Wednesday (Expiry)
        # If today is Wed (2), days_ahead=0. If Thu (3), days_ahead=6.
        days_ahead = (2 - current_date.weekday() + 7) % 7
        next_expiry = current_date + timedelta(days=days_ahead)
        
        # 2. Check if it's a Monthly Expiry
        last_wed_of_month = self._get_last_wednesday(next_expiry.year, next_expiry.month)
        is_monthly = (next_expiry == last_wed_of_month)
        
        if is_monthly:
            # Monthly Rule: Skip last 7 days (Thu before to Wed of expiry)
            # This means if we are within 6 days of expiry (Thu=6, Fri=5... Wed=0)
            return days_ahead <= 6
        else:
            # Weekly Rule: Skip last 2 days (Tue & Wed)
            # Tue=1, Wed=0
            return days_ahead <= 1

    def prepare_data(self, engine: 'BacktestEngine', symbol: str, start_date: datetime, end_date: datetime, interval: str, **kwargs) -> pd.DataFrame:
        """
        Fetches 5m, 15m, and 1h data separately and merges them.
        """
        print(f"[DEBUG] MTA Strategy prepare_data called for {symbol} with interval {interval}")
        # 1. Fetch Base Data (5m) - Force 5m interval
        if interval != "5":
            print(f"Warning: MTA Strategy requires 5m base interval. Overriding {interval} to 5.")
            interval = "5"
            
        df_5m = engine.data_manager.get_historical_index_data(symbol, start_date, end_date, "5", is_backtest_log=True)
        if df_5m is None or df_5m.empty: return None
        
        # 2. Fetch 15m Data
        df_15m = engine.data_manager.get_historical_index_data(symbol, start_date, end_date, "15", is_backtest_log=True)
        
        # 3. Fetch 1h Data
        df_1h = engine.data_manager.get_historical_index_data(symbol, start_date, end_date, "60", is_backtest_log=True)
        
        # 4. Calculate Indicators on Higher Timeframes BEFORE merging
        # This is crucial because merging first would mess up the rolling calculations
        ema_short = kwargs.get('ema_short', 9)
        ema_long = kwargs.get('ema_long', 15)
        
        if df_15m is not None and not df_15m.empty:
            df_15m['ema_short_15m'] = df_15m['close'].ewm(span=ema_short, adjust=False).mean()
            df_15m['ema_long_15m'] = df_15m['close'].ewm(span=ema_long, adjust=False).mean()
            
        if df_1h is not None and not df_1h.empty:
            df_1h['ema_short_1h'] = df_1h['close'].ewm(span=ema_short, adjust=False).mean()
            df_1h['ema_long_1h'] = df_1h['close'].ewm(span=ema_long, adjust=False).mean()
            
        # 5. Merge Higher Timeframes to Base (5m)
        # We align by timestamp. 15m/1h data will be sparse on the 5m index.
        # We use ffill() to propagate the last known 15m/1h value forward.
        
        df_5m['15m_timestamp'] = df_5m.index.floor('15min')
        df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], left_on='15m_timestamp', right_index=True, how='left')
        
        # Fix for 1h candles starting at 09:15 (NSE Market Hours)
        # Logic: Shift back 15m -> floor to hour -> shift forward 15m
        # e.g. 09:20 -> 09:05 -> 09:00 -> 09:15
        df_5m['1h_timestamp'] = (df_5m.index - pd.Timedelta(minutes=15)).floor('1h') + pd.Timedelta(minutes=15)
        df_5m = pd.merge(df_5m, df_1h[['ema_short_1h', 'ema_long_1h']], left_on='1h_timestamp', right_index=True, how='left')
        
        # Forward fill to propagate signals
        df_5m.ffill(inplace=True)
        df_5m.dropna(inplace=True) # Remove initial rows with NaNs
        
        return df_5m

    def calculate_indicators(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        try:
            df = data.copy()
            if df.empty: return None
            
            # Get periods from kwargs or defaults
            ema_short_period = kwargs.get('ema_short', self.parameters['ema_short'])
            ema_long_period = kwargs.get('ema_long', self.parameters['ema_long'])
            atr_period = kwargs.get('atr_period', self.parameters['atr_period'])
            rsi_period = kwargs.get('rsi_period', self.parameters['rsi_period'])
            adx_period = kwargs.get('adx_period', self.parameters['adx_period'])
            
            # --- NEW: Candle Size Params ---
            candle_size_period = kwargs.get('candle_size_period', self.parameters['candle_size_period'])
            
            # --- 1. Calculate Indicators on Base (5m) ---
            df['ema_short'] = df['close'].ewm(span=ema_short_period, adjust=False).mean()
            df['ema_long'] = df['close'].ewm(span=ema_long_period, adjust=False).mean()
            
            # ATR
            df.ta.atr(length=atr_period, append=True)
            atr_col_name = f'ATRr_{atr_period}'
            if atr_col_name in df.columns:
                df.rename(columns={atr_col_name: 'atr'}, inplace=True)
            
            # RSI
            df.ta.rsi(length=rsi_period, append=True)
            rsi_col_name = f'RSI_{rsi_period}'
            if rsi_col_name in df.columns:
                df.rename(columns={rsi_col_name: 'rsi'}, inplace=True)

            # ADX
            df.ta.adx(length=adx_period, append=True)
            adx_col_name = f'ADX_{adx_period}'
            if adx_col_name in df.columns:
                df.rename(columns={adx_col_name: 'adx'}, inplace=True)
            
            df.drop(columns=[f'DMP_{adx_period}', f'DMN_{adx_period}'], errors='ignore', inplace=True)
            
            # --- NEW: Candle Size Indicators ---
            df['candle_range'] = df['high'] - df['low']
            df['avg_candle_range'] = df['candle_range'].rolling(window=candle_size_period).mean()

            # Note: Higher timeframe indicators (ema_short_15m, etc.) are already present 
            # because they were added in prepare_data. We just need to ensure they exist.
            required_cols = ['ema_short_15m', 'ema_long_15m', 'ema_short_1h', 'ema_long_1h']
            for col in required_cols:
                if col not in df.columns:
                    # Fallback if data wasn't prepared correctly (e.g. in live mode later)
                    df[col] = np.nan 

            return df
        except Exception as e:
            print(f"Error calculating indicators: {e}"); return None

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df_5m = self.calculate_indicators(data, **kwargs)
        if df_5m is None: return pd.DataFrame() 
        
        df_5m['signal'] = 0
        df_5m['strike'] = 0
        df_5m['opt_type'] = ""
        
        # --- NEW: AI Trend Filter Integration ---
        if self.trend_predictor:
            try:
                # Resample to 1h for AI (or use existing 1h columns if possible, but predictor expects raw OHLCV)
                # Since we have 1h data merged, we can try to reconstruct or just resample 5m -> 1h
                # For simplicity and robustness, we resample the 5m data to 1h
                df_1h_ai = self._resample_data(df_5m, '1h')
                if not df_1h_ai.empty:
                    trend_results, _ = self.trend_predictor.predict_trend(df_1h_ai)
                    # Merge predictions back to 5m
                    df_5m['1h_timestamp'] = df_5m.index.floor('1h')
                    df_5m = pd.merge(df_5m, trend_results[['Predicted']], left_on='1h_timestamp', right_index=True, how='left')
                    df_5m.rename(columns={'Predicted': 'ai_trend'}, inplace=True)
                    df_5m['ai_trend'] = df_5m['ai_trend'].ffill()
            except Exception as e:
                print(f"AI Trend Prediction failed: {e}")
        
        # --- NEW: Get filter params from kwargs ---
        use_adx_filter = kwargs.get('use_adx_filter', self.parameters['use_adx_filter'])
        adx_threshold = kwargs.get('adx_threshold', self.parameters['adx_threshold'])
        use_rsi_filter = kwargs.get('use_rsi_filter', self.parameters['use_rsi_filter'])
        rsi_overbought = kwargs.get('rsi_overbought', self.parameters['rsi_overbought'])
        rsi_oversold = kwargs.get('rsi_oversold', self.parameters['rsi_oversold'])
        skip_last_week_expiry = kwargs.get('skip_last_week_expiry', self.parameters['skip_last_week_expiry'])
        
        # --- NEW: Candle Size Filter Params ---
        use_candle_size_filter = kwargs.get('use_candle_size_filter', self.parameters['use_candle_size_filter'])
        candle_size_factor = kwargs.get('candle_size_factor', self.parameters['candle_size_factor'])
        
        min_periods = max(
            self.parameters['ema_long'], 
            kwargs.get('atr_period', 14),
            kwargs.get('adx_period', 14),
            kwargs.get('rsi_period', 14),
            kwargs.get('candle_size_period', 20)
        ) + 1
        
        if min_periods >= len(df_5m):
            print("Not enough data to generate signals after indicator calculation.")
            return df_5m 
            
        for i in range(min_periods, len(df_5m)):
            current = df_5m.iloc[i]; prev = df_5m.iloc[i-1]
            current_dt = df_5m.index[i]
            
            # --- NEW: Skip Last Week of Expiry Filter ---
            if skip_last_week_expiry:
                if self._is_last_week_of_expiry(current_dt):
                    continue # Skip signal generation for this candle
            
            if pd.isna(current['ema_short']) or pd.isna(current['ema_short_15m']) or pd.isna(current['ema_short_1h']) or pd.isna(prev['ema_short']):
                continue
            
            # --- NEW: ADX Trend Strength Filter ---
            if use_adx_filter:
                if pd.isna(current['adx']) or current['adx'] < adx_threshold:
                    continue # Market is not trending, skip signal
            
            # --- NEW: Candle Size Filter ---
            if use_candle_size_filter:
                if pd.isna(current['avg_candle_range']) or current['candle_range'] < (current['avg_candle_range'] * candle_size_factor):
                    continue # Candle is too small, skip signal
            
            # Trend conditions
            is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']
            is_1h_downtrend = current['ema_short_1h'] < current['ema_long_1h']
            is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
            is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
            is_5m_uptrend = current['ema_short'] > current['ema_long'] # This is the 5m trend, not 5m crossover
            is_5m_downtrend = current['ema_short'] < current['ema_long'] # This is the 5m trend, not 5m crossover
            
            # Signal conditions (5m Crossover)
            is_5m_bullish_cross = (prev['ema_short'] <= prev['ema_long']) and (current['ema_short'] > current['ema_long'])
            is_5m_bearish_cross = (prev['ema_short'] >= prev['ema_long']) and (current['ema_short'] < current['ema_long'])
            
            strike = int(round(current['close'] / 100.0) * 100)

            # BUY Signal (All timeframes aligned)
            if is_5m_bullish_cross and is_15m_uptrend and is_1h_uptrend:
                # --- NEW: RSI Overbought Filter ---
                if use_rsi_filter:
                    if not pd.isna(current['rsi']) and current['rsi'] > rsi_overbought:
                        continue # Market is overbought, skip BUY
                
                # --- NEW: AI Trend Filter ---
                if self.trend_predictor and 'ai_trend' in df_5m.columns:
                    ai_trend = current['ai_trend']
                    if not pd.isna(ai_trend) and ai_trend == 0: # AI predicts DOWN
                         continue
                
                df_5m.loc[df_5m.index[i], 'signal'] = 1
                df_5m.loc[df_5m.index[i], 'strike'] = strike
                df_5m.loc[df_5m.index[i], 'opt_type'] = "CE"
            
            # SELL Signal (All timeframes aligned)
            elif is_5m_bearish_cross and is_15m_downtrend and is_1h_downtrend:
                # --- NEW: RSI Oversold Filter ---
                if use_rsi_filter:
                    if not pd.isna(current['rsi']) and current['rsi'] < rsi_oversold:
                        continue # Market is oversold, skip SELL

                # --- NEW: AI Trend Filter ---
                if self.trend_predictor and 'ai_trend' in df_5m.columns:
                    ai_trend = current['ai_trend']
                    if not pd.isna(ai_trend) and ai_trend == 1: # AI predicts UP
                         continue
                
                df_5m.loc[df_5m.index[i], 'signal'] = -1
                df_5m.loc[df_5m.index[i], 'strike'] = strike
                df_5m.loc[df_5m.index[i], 'opt_type'] = "PE"
                
        return df_5m

    # --- NEW: Updated Live Signal Generator ---
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        try: 
            today = datetime.now(self.IST).date()
        except: today = datetime.now().date() 
            
        if self.current_day != today:
            self.current_day = today; self.daily_trend = 'NEUTRAL'
            print(f"--- New Day ({today}): Trend reset to NEUTRAL ---")
            
        # Get latest params (in case they were changed in UI)
        params = self.parameters 
        
        # Note: historical_data already has 5m, 15m, 1h merged from AngelClient.get_multi_timeframe_data()
        # We just need to calculate the base 5m indicators (EMA, ATR, RSI, ADX) on top of it.
        # The higher timeframe columns (ema_short_15m, ema_long_15m, etc.) are ALREADY present.
        
        df_5m = self.calculate_indicators(historical_data, **params)
        
        if df_5m is None or df_5m.empty or len(df_5m) < 2: return None
            
        # --- NEW: Ensure we use the LAST COMPLETED candle ---
        # If the last candle in the dataframe is still forming (based on time), we use the one before it.
        last_candle_time = df_5m.index[-1]
        now = datetime.now(self.IST)
        
        # Assuming 5m candles. If current time is before candle_start + 5m, it's forming.
        # We add a small buffer (e.g. 1 sec) to be safe.
        is_forming = (last_candle_time + timedelta(minutes=5)) > now
        
        if is_forming:
            # Last candle is forming, so use the previous one (which is completed)
            if len(df_5m) < 3: return None # Need at least 2 completed candles
            current = df_5m.iloc[-2]
            prev = df_5m.iloc[-3]
            # print(f"[{now.strftime('%H:%M:%S')}] Last candle ({last_candle_time.strftime('%H:%M')}) is forming. Using {current.name.strftime('%H:%M')}.")
        else:
            # Last candle is completed
            current = df_5m.iloc[-1]
            prev = df_5m.iloc[-2]
            # print(f"[{now.strftime('%H:%M:%S')}] Last candle ({last_candle_time.strftime('%H:%M')}) is completed. Using it.")
        
        # Check if required columns exist (they should be there from get_multi_timeframe_data)
        if pd.isna(current['ema_short']) or pd.isna(current['ema_short_15m']) or pd.isna(current['ema_short_1h']) or pd.isna(prev['ema_short']):
            # print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping signal: Missing EMA data (5m/15m/1h)")
            return None
        
        # --- NEW: Get filter params ---
        use_adx_filter = params.get('use_adx_filter', False)
        adx_threshold = params.get('adx_threshold', 20)
        use_rsi_filter = params.get('use_rsi_filter', True)
        rsi_overbought = params.get('rsi_overbought', 70)
        rsi_oversold = params.get('rsi_oversold', 30)
        
        # --- NEW: Expiry Filter ---
        skip_last_week_expiry = params.get('skip_last_week_expiry', True)
        if skip_last_week_expiry:
            if self._is_last_week_of_expiry(datetime.now(self.IST)):
                # print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping signal: Last week of expiry")
                return None

        # --- NEW: Candle Size Filter ---
        use_candle_size_filter = params.get('use_candle_size_filter', True)
        candle_size_factor = params.get('candle_size_factor', 1.0)
        
        if use_candle_size_filter:
            if pd.isna(current['avg_candle_range']) or current['candle_range'] < (current['avg_candle_range'] * candle_size_factor):
                # print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping signal: Candle too small")
                return None
        
        # --- NEW: ADX Filter ---
        if use_adx_filter:
            if pd.isna(current['adx']) or current['adx'] < adx_threshold:
                # print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping signal check: ADX ({current['adx']:.1f}) is below threshold ({adx_threshold})")
                return None
            
        if self.daily_trend == 'NEUTRAL':
            is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
            is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
            if is_15m_uptrend: self.daily_trend = 'UP'; print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: UP")
            elif is_15m_downtrend: self.daily_trend = 'DOWN'; print(f"[{datetime.now().strftime('%H:%M:%S')}] Daily Trend LOCKED: DOWN")
        
        is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']
        is_1h_downtrend = current['ema_short_1h'] < current['ema_long_1h']
        is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
        is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
        is_5m_uptrend = current['ema_short'] > current['ema_long'] # Base trend (5m)
        is_5m_downtrend = current['ema_short'] < current['ema_long'] # Base trend (5m)
        
        # Signal is a 5m Crossover (previously named 1m, but data is 5m)
        is_5m_bullish_cross = (prev['ema_short'] <= prev['ema_long']) and (current['ema_short'] > current['ema_long'])
        is_5m_bearish_cross = (prev['ema_short'] >= prev['ema_long']) and (current['ema_short'] < current['ema_long'])
        
        signal_to_fire = None
        
        if is_5m_bullish_cross and is_5m_uptrend and is_15m_uptrend and is_1h_uptrend:
            # --- NEW: RSI Overbought Filter ---
            if use_rsi_filter and not pd.isna(current['rsi']) and current['rsi'] > rsi_overbought:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping BUY signal: RSI ({current['rsi']:.1f}) is Overbought (>{rsi_overbought})")
                return None
                
            signal_to_fire = {"signal": "BUY", "type": "CE", "price": current['close'], 
                              "strike": int(round(current['close'] / 100.0) * 100), 
                              "reason": "MTA: 5m Crossover UP (5m/15m/1h UP)", 
                              "atr": current['atr'], "adx": current['adx'],
                              "timestamp": current.name}
                              
        elif is_5m_bearish_cross and is_5m_downtrend and is_15m_downtrend and is_1h_downtrend:
            # --- NEW: RSI Oversold Filter ---
            if use_rsi_filter and not pd.isna(current['rsi']) and current['rsi'] < rsi_oversold:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping SELL signal: RSI ({current['rsi']:.1f}) is Oversold (<{rsi_oversold})")
                return None

            signal_to_fire = {"signal": "BUY", "type": "PE", "price": current['close'], 
                              "strike": int(round(current['close'] / 100.0) * 100), 
                              "reason": "MTA: 5m Crossover DOWN (5m/15m/1h DOWN)", 
                              "atr": current['atr'], "adx": current['adx'],
                              "timestamp": current.name}
        
        return signal_to_fire

# --- (Other strategies are unchanged) ...
class EmaTrendFollowingStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m State / 15m Daily Trend Strategy", description="Placeholder"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaFastCrossoverStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Fast Crossover (Scalp Sim)", description="Placeholder"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaTrendConfirmationStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Entry / 15m Trend EMA Strategy", description="Placeholder"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaMomentumStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Momentum Strategy", description="Placeholder"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EMAStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Confluence Strategy (Strict)", description="Placeholder"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None

# --- NEW: AI Prediction Strategy ---
class AIStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__(
            name="AI Prediction Strategy", 
            description="Trades based on Neural Network predictions (5m/15m/1h features)."
        )
        self.parameters = {
            'lookback': 10,
            'lot_size': 35, 'min_investment': 10000,
            'max_daily_loss': 2000, 'max_trades_per_day': 10,
            'trade_start_time': time(9, 30), 'trade_end_time': time(15, 0),
            'sl_mode': 'ATR', 'invested_value_sl_pct': 5.0, 'tp_sl_ratio': 2.0,
            'atr_tp_multiplier': 2.0, 'atr_sl_multiplier': 1.0,
            'simulated_premium_pct': 0.008, 'simulated_delta': 0.5,
        }
        self.predictor = None

    def set_predictor(self, predictor):
        self.predictor = predictor

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        if self.predictor is None:
            print("AIStrategy: No predictor set. Returning empty signals.")
            return pd.DataFrame()

        df = data.copy()
        
        # Run prediction
        # Note: predictor.predict expects the dataframe to have the raw columns.
        # It will handle feature generation.
        try:
            results, _ = self.predictor.predict(df, lookback=kwargs.get('lookback', 10))
        except Exception as e:
            print(f"AIStrategy Prediction Error: {e}")
            return pd.DataFrame()
        
        # Join predictions back to original dataframe
        # 'results' index is a subset of 'df' index (due to lags)
        df = df.join(results[['Predicted']], how='left')
        
        df['signal'] = 0
        df['strike'] = 0
        df['opt_type'] = ""
        
        # Calculate ATR for SL/TP
        if 'atr' not in df.columns:
             df.ta.atr(length=14, append=True)
             if 'ATRr_14' in df.columns: df.rename(columns={'ATRr_14': 'atr'}, inplace=True)

        # Generate Signals
        # BUY if Predicted > Close (Expect UP)
        # SELL if Predicted < Close (Expect DOWN)
        
        # We use a small threshold to avoid noise? 
        # For now, raw direction.
        
        buy_condition = (df['Predicted'] > df['close'])
        sell_condition = (df['Predicted'] < df['close'])
        
        df.loc[buy_condition, 'signal'] = 1
        df.loc[buy_condition, 'opt_type'] = "CE"
        
        df.loc[sell_condition, 'signal'] = -1
        df.loc[sell_condition, 'opt_type'] = "PE"
        
        df['strike'] = (df['close'] / 100).round() * 100
        
        return df

    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        # Not implemented for live yet, as it requires the trained model state
        return None


class BacktestEngine:
    # ... (init, register_builtin_strategies, register_strategy are unchanged) ...
    def __init__(self, initial_capital: float = 100000, fyers_manager: 'FyersDataManager' = None):
        self.initial_capital = initial_capital 
        self.strategies = {}
        if fyers_manager is None:
            raise ValueError("BacktestEngine requires a FyersDataManager instance.")
        self.data_manager = fyers_manager
        self.register_builtin_strategies()

    def register_builtin_strategies(self):
        """Register built-in strategies"""
        self.strategies['mta_ema_crossover'] = MultiTimeframeStrategy()
        self.strategies['ema_daily_trend'] = EmaTrendFollowingStrategy() 
        self.strategies['ema_scalp_sim'] = EmaFastCrossoverStrategy()
        self.strategies['ema_trend_confirm'] = EmaTrendConfirmationStrategy()
        self.strategies['ema_momentum'] = EmaMomentumStrategy()
        self.strategies['ema_momentum'] = EmaMomentumStrategy()
        self.strategies['ema_confluence_strict'] = EMAStrategy()
        self.strategies['ai_prediction'] = AIStrategy()

    def register_strategy(self, name: str, strategy: StrategyTemplate): 
        self.strategies[name] = strategy

    def run_backtest(self, strategy_name: str, symbol: str,
                    start_date: datetime, end_date: datetime, interval: str = "5",
                    silent: bool = False, 
                    data: pd.DataFrame = None, 
                    backtest_mode: str = "Real Option Data", 
                    **strategy_params) -> BacktestResult:
        
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' not found.")
            
        self.initial_capital = strategy_params.get('initial_capital', 100000)
        
        strategy = self.strategies[strategy_name]
        
        # --- NEW: Use strategy's prepare_data method ---
        if data is None:
            if not silent: st.info(f"Fetching data for {symbol}...")
            data = strategy.prepare_data(self, symbol, start_date, end_date, interval, **strategy_params)
            
        if data is None or data.empty:
            if not silent: st.error("No data found.")
            return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})
        
        original_params = strategy.parameters.copy()
        merged_params = {**strategy.parameters, **strategy_params, "backtest_mode": backtest_mode}
        strategy.parameters = merged_params 
        
        if not silent: st.info(f"🔍 Generating signals on {symbol} index data...")
        data_with_signals = strategy.generate_signals(data.copy(), **merged_params)
        
        if data_with_signals is None:
             if not silent: st.error(f"Signal generation failed for {strategy.name}.")
             return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})
             
        result = None
        if "Real Option" in backtest_mode:
            if not silent: st.info("💰 Executing trades with REAL option data...")
            result = self._execute_trades_with_risk_management(
                data_with_signals, 
                strategy_name, 
                merged_params, 
                symbol,
                silent=silent
            )
        else:
            if not silent: st.info("💰 Executing trades with SIMULATED premium...")
            result = self._execute_trades_simulated(
                data_with_signals,
                strategy_name,
                merged_params,
                symbol,
                silent=silent
            )
        
        strategy.parameters = original_params
        return result

    # --- ( _execute_trades_simulated is unchanged ) ---
    def _execute_trades_simulated(self, data: pd.DataFrame, strategy_name: str, params: Dict, index_name: str, silent: bool = False) -> BacktestResult:
        """
        Executes a backtest using simulated premium based on index price movements
        and a fixed delta. This is very fast as it makes NO API calls.
        """
        
        eod_exit_time = time(15, 19)
        trades, equity_curve = [], []
        position_type = None # "CE" or "PE"
        entry_price = 0.0      # Simulated option entry price
        entry_index_price = 0.0 # Index price at entry
        
        trade_active = False; current_trade = {}
        capital = self.initial_capital; max_capital = capital; max_drawdown = 0
        today_realized_pnl = 0.0; skip_today = False; current_day = None
        
        today_trades_count = 0
        max_trades_per_day = params.get('max_trades_per_day', 999)
        trade_start_time = params.get('trade_start_time', time(9, 15))
        trade_end_time = params.get('trade_end_time', time(15, 19))
        
        lot_size = params.get('lot_size', 35)
        sl_mode = params.get('sl_mode', 'Invested Value (%)') 
        min_investment = params.get('min_investment', 10000)
        max_daily_loss = params.get('max_daily_loss', 2000)
        
        sim_premium_pct = params.get('simulated_premium_pct', 0.008)
        sim_delta = params.get('simulated_delta', 0.5) # 0.5 Delta
        
        if sl_mode == "ATR" and 'atr' not in data.columns:
            if not silent: st.error(f"ATR column missing for simulated trade. Backtest failed."); 
            raise ValueError("ATR column missing")
            
        for i, (timestamp, row) in enumerate(data.iterrows()):
            trade_date = timestamp.date()
            current_time = timestamp.time()
            is_eod_exit = current_time >= eod_exit_time
            
            if current_day != trade_date: 
                current_day = trade_date; today_realized_pnl = 0.0; skip_today = False 
                today_trades_count = 0
                
            if pd.isna(row['close']):
                equity_curve.append({'timestamp': timestamp, 'equity': capital, 'price': np.nan})
                continue
                
            current_index_price = row['close'] # Price of the index
            
            # --- 1. Check for Active Trade Exits ---
            if trade_active:
                stop_loss_price = current_trade.get('stop_loss_price', 0)
                take_profit_price = current_trade.get('take_profit_price', float('inf'))
                
                # Calculate current simulated premium
                index_points_diff = current_index_price - entry_index_price
                if position_type == "PE":
                    index_points_diff = -index_points_diff
                
                premium_points_diff = index_points_diff * sim_delta
                current_premium_price = max(0.05, entry_price + premium_points_diff)
                
                stop_loss_trigger, take_profit_trigger = False, False
                if current_premium_price <= stop_loss_price: stop_loss_trigger = True
                if current_premium_price >= take_profit_price: take_profit_trigger = True
                
                if stop_loss_trigger or take_profit_trigger or is_eod_exit:
                    exit_price = current_premium_price
                    exit_index_price = current_index_price
                    if stop_loss_trigger: exit_price = stop_loss_price
                    if take_profit_trigger: exit_price = take_profit_price
                    
                    pnl = (exit_price - entry_price) * lot_size
                    today_realized_pnl += pnl 
                    invested_amount = current_trade.get('invested_amount', 1)
                    return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
                    exit_reason = 'EOD_SQUARE_OFF' if is_eod_exit else ('STOP_LOSS' if stop_loss_trigger else 'TAKE_PROFIT')
                    
                    current_trade.update({
                        'exit_time': timestamp, 'exit_price': exit_price, 'pnl': pnl, 
                        'return_pct': return_pct, 'exit_reason': exit_reason, 
                        'trade_duration': (timestamp - current_trade['entry_time']).total_seconds() / 60,
                        'exit_index_price': exit_index_price
                    })
                    trades.append(current_trade)
                    capital += pnl
                    trade_active = False; position_type = None
            
            # --- 2. Check for New Trade Entry ---
            if not trade_active and row['signal'] != 0 and not is_eod_exit:
                if current_time < trade_start_time or current_time > trade_end_time: continue
                if today_trades_count >= max_trades_per_day: continue
                if today_realized_pnl <= -abs(max_daily_loss): continue 
                if skip_today: continue 
                
                strike = int(row['strike'])
                opt_type = row['opt_type']
                
                entry_index_price = row['close']
                entry_price = entry_index_price * sim_premium_pct

                quantity = lot_size
                invested_amount = entry_price * quantity
                
                if invested_amount < min_investment: 
                    if not silent: print(f"Simulated price {entry_price} too low. Skipping day.")
                    skip_today = True; continue 
                
                position_type = opt_type # "CE" or "PE"
                
                stop_loss_price_level, take_profit_price_level = 0.0, 0.0
                
                if sl_mode == "ATR":
                    current_atr = row['atr']
                    if pd.isna(current_atr) or current_atr <= 0:
                        if not silent: st.warning("Invalid ATR, falling back to % SL")
                        temp_sl_mode = "Invested Value (%)"
                    else:
                        temp_sl_mode = "ATR"
                        
                        # --- NEW: Dynamic Risk Management ---
                        use_dynamic_risk = params.get('use_dynamic_risk', False)
                        tp_mult = params.get('atr_tp_multiplier', 2.0)
                        sl_mult = params.get('atr_sl_multiplier', 1.0)
                        
                        if use_dynamic_risk and 'adx' in row and not pd.isna(row['adx']):
                            adx_val = row['adx']
                            # If ADX > 25, increase TP multiplier (Trend Following)
                            # If ADX < 20, decrease TP multiplier (Choppy)
                            if adx_val > 25:
                                tp_mult *= (1 + (adx_val - 25) / 100.0) # e.g. ADX 45 -> +20% TP
                            elif adx_val < 20:
                                tp_mult *= 0.8 # Reduce TP in low ADX
                        
                        option_sl_points = (current_atr * sl_mult) * sim_delta
                        option_tp_points = (current_atr * tp_mult) * sim_delta
                else:
                    temp_sl_mode = "Invested Value (%)"

                if temp_sl_mode == "Invested Value (%)":
                    sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0
                    tp_ratio = params.get('tp_sl_ratio', 2.0)
                    option_sl_points = entry_price * sl_pct
                    option_tp_points = option_sl_points * tp_ratio

                stop_loss_price_level = entry_price - option_sl_points
                take_profit_price_level = entry_price + option_tp_points
                stop_loss_price_level = max(0.05, stop_loss_price_level) 
                
                current_trade = {
                    'strategy': strategy_name, 'entry_time': timestamp, 'entry_price': entry_price, 
                    'position': quantity, 'quantity': quantity, 'invested_amount': invested_amount,
                    'simulated_option': f"SIM_{index_name} {strike} {opt_type}", 
                    'signal_reason': row.get('signal_reason', ''), 
                    'stop_loss_price': stop_loss_price_level, 
                    'take_profit_price': take_profit_price_level,
                    'entry_index_price': entry_index_price
                }
                trade_active = True
                today_trades_count += 1
            
            # --- 3. Update Equity Curve ---
            current_equity = capital
            if trade_active:
                index_points_diff = current_index_price - entry_index_price
                if position_type == "PE":
                    index_points_diff = -index_points_diff
                premium_points_diff = index_points_diff * sim_delta
                current_premium_price = max(0.05, entry_price + premium_points_diff)
                
                unrealized_pnl = (current_premium_price - entry_price) * lot_size
                current_equity += unrealized_pnl
                
            equity_curve.append({'timestamp': timestamp, 'equity': current_equity, 'price': current_index_price})
            max_capital = max(max_capital, current_equity); drawdown = (max_capital - current_equity) / max_capital * 100 if max_capital > 0 else 0; max_drawdown = max(max_drawdown, drawdown)
        
        # --- 4. Handle End of Data ---
        if trade_active:
            last_index_price = data.iloc[-1]['close']
            index_points_diff = last_index_price - entry_index_price
            if position_type == "PE":
                index_points_diff = -index_points_diff
            premium_points_diff = index_points_diff * sim_delta
            last_premium_price = max(0.05, entry_price + premium_points_diff)
            
            pnl = (last_premium_price - entry_price) * lot_size
            invested_amount = current_trade.get('invested_amount', 1); return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
            current_trade.update({
                'exit_time': data.index[-1], 'exit_price': last_premium_price, 'pnl': pnl, 
                'return_pct': return_pct, 'exit_reason': 'END_OF_DATA', 
                'trade_duration': (data.index[-1] - current_trade['entry_time']).total_seconds() / 60,
                'exit_index_price': last_index_price
            })
            trades.append(current_trade); capital += pnl
            
        return self._calculate_performance_metrics(trades, equity_curve, data, strategy_name, params, capital)


    # --- ( _execute_trades_with_risk_management is unchanged ) ---
    def _execute_trades_with_risk_management(self, data: pd.DataFrame, strategy_name: str, params: Dict, index_name: str, silent: bool = False) -> BacktestResult:
        
        eod_exit_time = time(15, 19)
        trades, equity_curve = [], []
        position = 0; entry_price = 0; entry_index = 0
        trade_active = False; current_trade = {}
        capital = self.initial_capital; max_capital = capital; max_drawdown = 0
        today_realized_pnl = 0.0; skip_today = False; current_day = None
        
        today_trades_count = 0
        max_trades_per_day = params.get('max_trades_per_day', 999)
        trade_start_time = params.get('trade_start_time', time(9, 15))
        trade_end_time = params.get('trade_end_time', time(15, 19))
        
        lot_size = params.get('lot_size', 35)
        sl_mode = params.get('sl_mode', 'Invested Value (%)') 
        min_investment = params.get('min_investment', 10000)
        max_daily_loss = params.get('max_daily_loss', 2000) 
        
        if sl_mode == "ATR" and 'atr' not in data.columns:
            if not silent: st.error(f"ATR column missing. Backtest failed."); 
            raise ValueError("ATR column missing")
            
        daily_option_data_cache = {}
        current_option_df = None
            
        for i, (timestamp, row) in enumerate(data.iterrows()):
            trade_date = timestamp.date()
            current_time = timestamp.time()
            is_eod_exit = current_time >= eod_exit_time
            
            if current_day != trade_date: 
                current_day = trade_date; today_realized_pnl = 0.0; skip_today = False 
                today_trades_count = 0
                daily_option_data_cache = {} 
                current_option_df = None
                
            if pd.isna(row['close']):
                equity_curve.append({'timestamp': timestamp, 'equity': capital, 'price': np.nan})
                continue
                
            current_index_price = row['close']
            
            # --- 1. Check for Active Trade Exits ---
            if trade_active:
                try:
                    option_candle = current_option_df.loc[timestamp]
                    current_option_price = option_candle['close']
                except KeyError:
                    current_option_price = entry_price 
                except Exception as e:
                    print(f"Error getting option price: {e}")
                    current_option_price = entry_price

                stop_loss_price = current_trade.get('stop_loss', 0)
                take_profit_price = current_trade.get('take_profit', float('inf'))
                
                stop_loss_trigger, take_profit_trigger = False, False
                
                if current_option_price <= stop_loss_price: stop_loss_trigger = True
                elif current_option_price >= take_profit_price: take_profit_trigger = True
                
                if stop_loss_trigger or take_profit_trigger or is_eod_exit:
                    exit_price = current_option_price
                    if stop_loss_trigger: exit_price = stop_loss_price
                    if take_profit_trigger: exit_price = take_profit_price
                    if is_eod_exit: exit_price = current_option_price
                    
                    pnl = (exit_price - entry_price) * position
                    today_realized_pnl += pnl 
                    invested_amount = current_trade.get('invested_amount', 1)
                    return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
                    exit_reason = 'EOD_SQUARE_OFF' if is_eod_exit else ('STOP_LOSS' if stop_loss_trigger else 'TAKE_PROFIT')
                    
                    current_trade.update({'exit_time': timestamp, 'exit_price': exit_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': exit_reason, 'trade_duration': (timestamp - current_trade['entry_time']).total_seconds() / 60})
                    trades.append(current_trade)
                    capital += pnl
                    trade_active = False; position = 0; current_option_df = None
            
            # --- 2. Check for New Trade Entry ---
            if not trade_active and row['signal'] != 0 and not is_eod_exit:
                if current_time < trade_start_time or current_time > trade_end_time: continue
                if today_trades_count >= max_trades_per_day: continue
                if today_realized_pnl <= -abs(max_daily_loss): continue 
                if skip_today: continue 
                
                try:
                    strike = int(row['strike'])
                    opt_type = row['opt_type']
                    cache_key = f"{strike}{opt_type}"
                    
                    if cache_key not in daily_option_data_cache:
                        if not silent: st.info(f"Fetching {index_name} {strike} {opt_type} data for {trade_date}...")
                        option_df = self.data_manager.get_historical_option_data(index_name, trade_date, strike, opt_type, "5")
                        if option_df is None or option_df.empty:
                            raise Exception("No historical option data found.")
                        daily_option_data_cache[cache_key] = option_df
                    
                    current_option_df = daily_option_data_cache[cache_key]
                    
                    option_candle = current_option_df.loc[timestamp]
                    if isinstance(option_candle, pd.DataFrame):
                        option_candle = option_candle.iloc[0]
                    entry_price = option_candle['close']
                    
                except KeyError:
                    if not silent: st.warning(f"No option data found for {cache_key} at exact time {timestamp}. Skipping trade.")
                    skip_today = True; continue
                except Exception as e:
                    if not silent: st.error(f"Error fetching option data: {e}. Skipping day.")
                    skip_today = True; continue

                quantity = lot_size
                invested_amount = entry_price * quantity
                
                if invested_amount < min_investment: 
                    if not silent: st.warning(f"Option price {entry_price} too low. Skipping day.")
                    skip_today = True; continue 
                
                position = quantity # Always Long (Buy CE or Buy PE) 
                entry_index = i
                
                stop_loss_price, take_profit_price = 0.0, 0.0
                if sl_mode == "ATR":
                    current_atr = row['atr']
                    if pd.isna(current_atr) or current_atr <= 0:
                        if not silent: st.warning("Invalid ATR, falling back to % SL")
                        temp_sl_mode = "Invested Value (%)"
                    else:
                        temp_sl_mode = "ATR"
                        
                        # --- NEW: Dynamic Risk Management ---
                        use_dynamic_risk = params.get('use_dynamic_risk', False)
                        tp_mult = params.get('atr_tp_multiplier', 2.0)
                        sl_mult = params.get('atr_sl_multiplier', 1.0)
                        
                        if use_dynamic_risk and 'adx' in row and not pd.isna(row['adx']):
                            adx_val = row['adx']
                            if adx_val > 25:
                                tp_mult *= (1 + (adx_val - 25) / 100.0)
                            elif adx_val < 20:
                                tp_mult *= 0.8
                                
                        option_sl_points = (current_atr * sl_mult) * 0.5
                        option_tp_points = (current_atr * tp_mult) * 0.5
                else:
                    temp_sl_mode = "Invested Value (%)"

                if temp_sl_mode == "Invested Value (%)":
                    sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0
                    tp_ratio = params.get('tp_sl_ratio', 2.0)
                    option_sl_points = entry_price * sl_pct
                    option_tp_points = option_sl_points * tp_ratio

                stop_loss_price = entry_price - option_sl_points
                take_profit_price = entry_price + option_tp_points
                stop_loss_price = max(0.05, stop_loss_price) 
                
                current_trade = {'strategy': strategy_name, 'entry_time': timestamp, 'entry_price': entry_price, 
                                 'position': position, 'quantity': quantity, 'invested_amount': invested_amount,
                                 'simulated_option': f"{index_name} {strike} {opt_type}", 
                                 'signal_reason': row.get('signal_reason', ''), 
                                 'stop_loss': stop_loss_price, 'take_profit': take_profit_price}
                trade_active = True
                today_trades_count += 1
            
            # --- 3. Update Equity Curve ---
            current_equity = capital
            if trade_active:
                try:
                    current_option_price = current_option_df.loc[timestamp]['close']
                except Exception:
                    current_option_price = entry_price
                
                unrealized_pnl = (current_option_price - entry_price) * position
                current_equity += unrealized_pnl
                
            equity_curve.append({'timestamp': timestamp, 'equity': current_equity, 'price': current_index_price})
            max_capital = max(max_capital, current_equity); drawdown = (max_capital - current_equity) / max_capital * 100 if max_capital > 0 else 0; max_drawdown = max(max_drawdown, drawdown)
        
        # --- 4. Handle End of Data ---
        if trade_active:
            last_option_price = current_option_df.iloc[-1]['close']
            pnl = (last_option_price - entry_price) * position
            invested_amount = current_trade.get('invested_amount', 1); return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
            current_trade.update({'exit_time': data.index[-1], 'exit_price': last_option_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': 'END_OF_DATA', 'trade_duration': (data.index[-1] - current_trade['entry_time']).total_seconds() / 60})
            trades.append(current_trade); capital += pnl
            
        return self._calculate_performance_metrics(trades, equity_curve, data, strategy_name, params, capital)

    # --- ( _calculate_performance_metrics is unchanged ) ---
    def _calculate_performance_metrics(self, trades: List[Dict], equity_curve: List[Dict],
                                     data: pd.DataFrame, strategy_name: str, params: Dict,
                                     final_capital: float) -> BacktestResult:
        # ... (no changes in this method) ...
        total_trades=len(trades); winning_trades=len([t for t in trades if t['pnl'] > 0]); losing_trades=total_trades-winning_trades
        win_rate=(winning_trades/total_trades*100) if total_trades > 0 else 0
        total_pnl=final_capital-self.initial_capital; avg_trade_pnl=total_pnl/total_trades if total_trades > 0 else 0
        winning_pnls=[t['pnl'] for t in trades if t['pnl'] > 0]; losing_pnls=[t['pnl'] for t in trades if t['pnl'] < 0]
        best_trade=max([t['pnl'] for t in trades]) if trades else 0; worst_trade=min([t['pnl'] for t in trades]) if trades else 0
        avg_winning_trade=np.mean(winning_pnls) if winning_pnls else 0; avg_losing_trade=np.mean(losing_pnls) if losing_pnls else 0
        returns=[t['return_pct']/100 for t in trades if t.get('return_pct') is not None]
        sharpe_ratio=0
        if returns and len(returns)>1: 
            std_dev=np.std(returns)
            if std_dev>0 : sharpe_ratio=np.mean(returns)/std_dev
        gross_profit=sum(t['pnl'] for t in trades if t['pnl']>0); gross_loss=abs(sum(t['pnl'] for t in trades if t['pnl']<0))
        profit_factor=gross_profit/gross_loss if gross_loss>0 else float('inf')
        equity_df=pd.DataFrame(equity_curve).set_index('timestamp')
        max_drawdown=0
        if not equity_df.empty:
            equity_df['peak']=equity_df['equity'].expanding().max()
            equity_df['drawdown_pct']=(equity_df['equity']-equity_df['peak'])/equity_df['peak']
            max_drawdown_series = equity_df['drawdown_pct'].dropna()
            if not max_drawdown_series.empty: max_drawdown=abs(max_drawdown_series.min())*100
        total_days=0; daily_return_avg=0
        if trades:
            first_trade=min(t['entry_time'] for t in trades); last_trade=max(t['exit_time'] for t in trades)
            total_days=(last_trade-first_trade).days+1
            if total_days>0: daily_return_avg=(total_pnl/self.initial_capital)/total_days*100
        monthly_returns=self._calculate_monthly_returns(trades)
        signals=[];
        if 'signal' in data.columns:
            for i, (timestamp, row) in enumerate(data.iterrows()):
                 if row['signal'] != 0:
                      signals.append({'timestamp': timestamp, 'signal': 'BUY' if row['signal'] == 1 else 'SELL', 
                                      'price': row['close'], 'reason': row.get('signal_reason', '')})
        return BacktestResult(total_trades,winning_trades,losing_trades,win_rate,total_pnl,max_drawdown,sharpe_ratio,profit_factor,avg_trade_pnl,best_trade,worst_trade,avg_winning_trade,avg_losing_trade,total_days,daily_return_avg,trades,equity_df,signals,monthly_returns,strategy_name,params)

    # --- ( _calculate_monthly_returns is unchanged ) ---
    def _calculate_monthly_returns(self, trades: List[Dict]) -> Dict[str, float]:
        # ... (no changes in this method) ...
        monthly_returns = {};
        if not trades: return monthly_returns
        trades_df = pd.DataFrame(trades); trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        trades_df['month'] = trades_df['entry_time'].dt.strftime('%Y-%m')
        monthly_pnl = trades_df.groupby('month')['pnl'].sum()
        for month, pnl in monthly_pnl.items(): monthly_returns[month] = pnl
        return monthly_returns


class StrategyTester:
    # ... (no changes) ...
    def __init__(self, fyers_manager: 'FyersDataManager'):
        if fyers_manager is None:
            raise ValueError("StrategyTester requires a FyersDataManager instance.")
        self.engine = BacktestEngine(fyers_manager=fyers_manager)
        self.custom_strategies = {}
    
    def create_custom_strategy(self, code: str, strategy_name: str) -> bool:
        # ... (no changes in this method) ...
        try:
            exec_globals = {'pd': pd, 'np': np, 'StrategyTemplate': StrategyTemplate, 'ta': ta}
            exec(code, exec_globals)
            for obj in exec_globals.values():
                if (isinstance(obj, type) and issubclass(obj, StrategyTemplate) and obj != StrategyTemplate):
                    strategy_instance = obj(); self.engine.register_strategy(strategy_name, strategy_instance)
                    self.custom_strategies[strategy_name] = strategy_instance; return True
            st.error("Custom code did not define a class inheriting from StrategyTemplate.")
            return False
        except Exception as e: st.error(f"Error creating custom strategy: {e}"); return False

    def get_available_strategies(self) -> List[str]: 
        return list(self.engine.strategies.keys())
    
    def get_strategy_parameters(self, strategy_name: str) -> Dict:
        if strategy_name in self.engine.strategies: 
            return self.engine.strategies[strategy_name].parameters
        return {}

    def run_backtest(self, strategy_name: str, symbol: str, start_date: datetime, end_date: datetime, interval: str = "5", silent: bool = False, **kwargs) -> BacktestResult:
        return self.engine.run_backtest(strategy_name, symbol, start_date, end_date, interval, silent, **kwargs)