# Modified: src/backtest/backtest.py
# - ADDED missing import for FyersDataManager
# - Fixed ATR renaming to be more robust

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
import json
import streamlit as st
from zoneinfo import ZoneInfo 
import pandas_ta as ta

# --- THIS IS THE FIX ---
# This import was missing, causing the NameError
try:
    from fetcher.fyers_data import FyersDataManager
except ImportError:
    print("CRITICAL: backtest.py failed to import 'from fetcher.fyers_data import FyersDataManager'")
    pass
# --- END FIX ---

try:
    from .yfinance_data import YFinanceData
except ImportError:
    print("Notice: yfinance_data.py not found (this is OK).")
except NameError:
    print("Notice: yfinance_data.py failed to import (this is OK).")


class BacktestResult:
    # ... (no changes in this class) ...
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
    # ... (no changes in this class) ...
    def __init__(self, name: str, description: str = ""): self.name=name; self.description=description; self.parameters={}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: raise NotImplementedError
    def calculate_indicators(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: raise NotImplementedError

class MultiTimeframeStrategy(StrategyTemplate):
    # ... (no changes in this class logic) ...
    def __init__(self):
        super().__init__(
            name="MTA (5m/15m/1h/4h) EMA Crossover", 
            description="Trades 5m EMA Crossover, aligned with 15m, 1h, and 4h."
        )
        self.parameters = {
            'ema_short': 9, 'ema_long': 15, 'lot_size': 35, 'min_investment': 10000, 
            'simulated_premium_pct': 0.008,
            'max_daily_loss': 2000, 
            'sl_mode': 'ATR', 
            'invested_value_sl_pct': 5.0, 
            'tp_sl_ratio': 2.0,
            'atr_period': 30,             
            'atr_tp_multiplier': 2.0,     
            'atr_sl_multiplier': 1.0,
            'max_trades_per_day': 10,
            'trade_start_time': time(9, 30), 
            'trade_end_time': time(15, 0),
        }
        self.IST = ZoneInfo('Asia/Kolkata')
        self.current_day = None
        self.daily_trend = 'NEUTRAL'

    def _resample_data(self, df_5min: pd.DataFrame, rule: str) -> pd.DataFrame:
        df_resampled = df_5min.resample(rule).agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        return df_resampled

    def calculate_indicators(self, data_5min: pd.DataFrame, **kwargs) -> pd.DataFrame:
        try:
            df_5m = data_5min.copy()
            if df_5m.empty: return None
            ema_short_period = kwargs.get('ema_short', self.parameters['ema_short'])
            ema_long_period = kwargs.get('ema_long', self.parameters['ema_long'])
            atr_period = kwargs.get('atr_period', self.parameters['atr_period'])
            df_5m['ema_short'] = df_5m['close'].ewm(span=ema_short_period, adjust=False).mean()
            df_5m['ema_long'] = df_5m['close'].ewm(span=ema_long_period, adjust=False).mean()
            
            original_cols = set(df_5m.columns)
            df_5m.ta.atr(length=atr_period, append=True)
            new_cols = set(df_5m.columns) - original_cols
            atr_col_name = next((col for col in new_cols if col.startswith('ATRr_')), None)
            if atr_col_name:
                df_5m.rename(columns={atr_col_name: 'atr'}, inplace=True)

            df_5m.fillna(method='bfill', inplace=True)
            df_15m = self._resample_data(df_5m, '15min')
            if not df_15m.empty:
                df_15m['ema_short_15m'] = df_15m['close'].ewm(span=ema_short_period, adjust=False).mean()
                df_15m['ema_long_15m'] = df_15m['close'].ewm(span=ema_long_period, adjust=False).mean()
            else: df_15m = pd.DataFrame(columns=['ema_short_15m', 'ema_long_15m'])
            df_1h = self._resample_data(df_5m, '1h')
            if not df_1h.empty:
                df_1h['ema_short_1h'] = df_1h['close'].ewm(span=ema_short_period, adjust=False).mean()
                df_1h['ema_long_1h'] = df_1h['close'].ewm(span=ema_long_period, adjust=False).mean()
            else: df_1h = pd.DataFrame(columns=['ema_short_1h', 'ema_long_1h'])
            df_4h = self._resample_data(df_5m, '4H')
            if not df_4h.empty:
                df_4h['ema_short_4h'] = df_4h['close'].ewm(span=ema_short_period, adjust=False).mean()
                df_4h['ema_long_4h'] = df_4h['close'].ewm(span=ema_long_period, adjust=False).mean()
            else: df_4h = pd.DataFrame(columns=['ema_short_4h', 'ema_long_4h'])
            df_5m['15m_timestamp'] = df_5m.index.floor('15min')
            df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], left_on='15m_timestamp', right_index=True, how='left')
            df_5m['1h_timestamp'] = df_5m.index.floor('1h')
            df_5m = pd.merge(df_5m, df_1h[['ema_short_1h', 'ema_long_1h']], left_on='1h_timestamp', right_index=True, how='left')
            df_5m['4h_timestamp'] = df_5m.index.floor('4H')
            df_5m = pd.merge(df_5m, df_4h[['ema_short_4h', 'ema_long_4h']], left_on='4h_timestamp', right_index=True, how='left')
            df_5m.ffill(inplace=True); df_5m.bfill(inplace=True)
            return df_5m
        except Exception as e:
            print(f"Error calculating indicators: {e}"); return None

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        # ... (no change in crossover logic) ...
        df_5m = self.calculate_indicators(data, **kwargs)
        if df_5m is None: return pd.DataFrame() 
        df_5m['signal'] = 0; df_5m['signal_strength'] = 0.0; df_5m['signal_reason'] = ""
        min_periods = max(self.parameters['ema_long'], kwargs.get('atr_period', 14)) + 1
        if min_periods >= len(df_5m):
            print("Not enough data to generate signals after indicator calculation.")
            return df_5m 
        for i in range(min_periods, len(df_5m)):
            current = df_5m.iloc[i]; prev = df_5m.iloc[i-1]
            if pd.isna(current['ema_short']) or pd.isna(current['ema_short_15m']) or pd.isna(current['ema_short_1h']) or pd.isna(current['ema_short_4h']) or pd.isna(prev['ema_short']):
                continue
            is_4h_uptrend = current['ema_short_4h'] > current['ema_long_4h']; is_4h_downtrend = current['ema_short_4h'] < current['ema_long_4h']
            is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']; is_1h_downtrend = current['ema_short_1h'] < current['ema_long_1h']
            is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']; is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
            is_5m_bullish_cross = (prev['ema_short'] <= prev['ema_long']) and (current['ema_short'] > current['ema_long'])
            is_5m_bearish_cross = (prev['ema_short'] >= prev['ema_long']) and (current['ema_short'] < current['ema_long'])
            all_trends_up = is_15m_uptrend and is_1h_uptrend and is_4h_uptrend
            all_trends_down = is_15m_downtrend and is_1h_downtrend and is_4h_downtrend
            if all_trends_up and is_5m_bullish_cross:
                df_5m.loc[df_5m.index[i], 'signal'] = 1
                df_5m.loc[df_5m.index[i], 'signal_strength'] = 0.95
                df_5m.loc[df_5m.index[i], 'signal_reason'] = "5m-Crossover aligned with 15m/1h/4h-UP"
            elif all_trends_down and is_5m_bearish_cross:
                df_5m.loc[df_5m.index[i], 'signal'] = -1
                df_5m.loc[df_5m.index[i], 'signal_strength'] = 0.95
                df_5m.loc[df_5m.index[i], 'signal_reason'] = "5m-Crossover aligned with 15m/1h/4h-DOWN"
        return df_5m

    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        # ... (no change in crossover logic) ...
        try: 
            today = datetime.now(self.IST).date()
        except: today = datetime.now().date() 
        if self.current_day != today:
            self.current_day = today; self.daily_trend = 'NEUTRAL'
            print(f"--- New Day ({today}): Trend reset to NEUTRAL ---")
        df_5m = self.calculate_indicators(historical_data, **self.parameters)
        if df_5m is None or df_5m.empty or len(df_5m) < 2: return None
        current = df_5m.iloc[-1]; prev = df_5m.iloc[-2]
        if pd.isna(current['ema_short']) or pd.isna(current['ema_short_15m']) or pd.isna(current['ema_short_1h']) or pd.isna(current['ema_short_4h']) or pd.isna(prev['ema_short']):
            return None
        is_4h_uptrend = current['ema_short_4h'] > current['ema_long_4h']; is_4h_downtrend = current['ema_short_4h'] < current['ema_long_4h']
        is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']; is_1h_downtrend = current['ema_short_1h'] < current['ema_long_1h']
        is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']; is_15m_downtrend = current['ema_short_15m'] < current['ema_long_15m']
        is_5m_bullish_cross = (prev['ema_short'] <= prev['ema_long']) and (current['ema_short'] > current['ema_long'])
        is_5m_bearish_cross = (prev['ema_short'] >= prev['ema_long']) and (current['ema_short'] < current['ema_long'])
        signal_to_fire = None
        all_trends_up = is_15m_uptrend and is_1h_uptrend and is_4h_uptrend
        all_trends_down = is_15m_downtrend and is_1h_downtrend and is_4h_downtrend
        if all_trends_up and is_5m_bullish_cross:
            signal_to_fire = {"signal": "BUY", "type": "CE", "price": current['close'], "strike": int(round(current['close'] / 100.0) * 100), "reason": "MTA: 5m Crossover UP (15m/1h/4h UP)", "atr": current['atr']}
        elif all_trends_down and is_5m_bearish_cross:
            signal_to_fire = {"signal": "BUY", "type": "PE", "price": current['close'], "strike": int(round(current['close'] / 100.0) * 100), "reason": "MTA: 5m Crossover DOWN (15m/1h/4h DOWN)", "atr": current['atr']}
        return signal_to_fire

# --- (Other placeholder strategies... no change) ---
class EmaTrendFollowingStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m State / 15m Daily Trend Strategy", description="Placeholder strategy"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaFastCrossoverStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Fast EMA Crossover (Scalp Sim)", description="Placeholder strategy"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaTrendConfirmationStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Entry / 15m Trend EMA Strategy", description="Placeholder strategy"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EmaMomentumStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Momentum Strategy", description="Placeholder strategy"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None
class EMAStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Confluence Strategy (Strict)", description="Placeholder strategy"); self.parameters = {}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: data['signal'] = 0; return data
    def generate_live_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]: return None


class BacktestEngine:
    """Main backtesting engine with risk management"""
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
        self.strategies['ema_confluence_strict'] = EMAStrategy()

    def register_strategy(self, name: str, strategy: StrategyTemplate): 
        self.strategies[name] = strategy

    def run_backtest(self, strategy_name: str, symbol: str,
                    start_date: datetime, end_date: datetime, interval: str = "5",
                    silent: bool = False, 
                    data: pd.DataFrame = None, 
                    **strategy_params) -> BacktestResult:
        # ... (no changes in this method) ...
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' not found. Available: {list(self.strategies.keys())}")
        self.initial_capital = strategy_params.get('initial_capital', 100000)
        if data is None:
            if not self.data_manager.is_authenticated():
                if not silent: st.error("Fyers API is not authenticated. Go to Settings tab.")
                return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})
            data = self.data_manager.get_historical_data(symbol, start_date, end_date, interval, is_backtest_log=not silent)
            if data is None or data.empty:
                 if not silent: st.error("Failed to load Fyers data. Backtest cannot proceed.")
                 return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})
        strategy = self.strategies[strategy_name]
        original_params = strategy.parameters.copy()
        merged_params = {**strategy.parameters, **strategy_params}
        strategy.parameters = merged_params 
        if not silent: st.info(f"🔍 Generating signals using '{strategy.name}' on {interval} min data...")
        data_with_signals = strategy.generate_signals(data.copy(), **merged_params)
        if data_with_signals is None:
             if not silent: st.error(f"Signal generation failed for {strategy.name}.")
             return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})
        if not silent: st.info("💰 Executing trades with risk management...")
        result = self._execute_trades_with_risk_management(data_with_signals, strategy_name, merged_params, silent=silent)
        strategy.parameters = original_params
        return result

    def _execute_trades_with_risk_management(self, data: pd.DataFrame, strategy_name: str, params: Dict, silent: bool = False) -> BacktestResult:
        # ... (no changes in this method) ...
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
        simulated_premium_pct = params.get('simulated_premium_pct', 0.008)
        max_daily_loss = params.get('max_daily_loss', 2000) 
        if sl_mode == "ATR" and 'atr' not in data.columns:
            if not silent: st.error(f"ATR column missing for SL mode. Columns: {data.columns}. Backtest failed."); 
            raise ValueError("ATR column missing") 
        for i, (timestamp, row) in enumerate(data.iterrows()):
            trade_date = timestamp.date()
            current_time = timestamp.time()
            is_eod_exit = current_time >= eod_exit_time
            if current_day != trade_date: 
                current_day = trade_date; today_realized_pnl = 0.0; skip_today = False 
                today_trades_count = 0
            if pd.isna(row['close']) or (sl_mode == "ATR" and pd.isna(row['atr'])):
                equity_curve.append({'timestamp': timestamp, 'equity': capital, 'price': np.nan})
                continue
            current_price = row['close']
            if trade_active:
                stop_loss_price = current_trade.get('stop_loss', 0)
                take_profit_price = current_trade.get('take_profit', float('inf') if position > 0 else 0)
                stop_loss_trigger, take_profit_trigger = False, False
                if position > 0:
                    if current_price <= stop_loss_price: stop_loss_trigger = True
                    elif current_price >= take_profit_price: take_profit_trigger = True
                elif position < 0:
                    if current_price >= stop_loss_price: stop_loss_trigger = True
                    elif current_price <= take_profit_price: take_profit_trigger = True
                if stop_loss_trigger or take_profit_trigger or is_eod_exit:
                    exit_price = current_price
                    if stop_loss_trigger: exit_price = stop_loss_price
                    if take_profit_trigger: exit_price = take_profit_price
                    if is_eod_exit: exit_price = current_price
                    exit_price = max(0.01, exit_price)
                    pnl = (exit_price - entry_price) * position if position > 0 else (entry_price - exit_price) * abs(position)
                    today_realized_pnl += pnl 
                    invested_amount = current_trade.get('invested_amount', 1)
                    return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
                    exit_reason = 'EOD_SQUARE_OFF' if is_eod_exit else ('STOP_LOSS' if stop_loss_trigger else 'TAKE_PROFIT')
                    current_trade.update({'exit_time': timestamp, 'exit_price': exit_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': exit_reason, 'trade_duration': i - entry_index})
                    trades.append(current_trade); capital += pnl; trade_active = False; position = 0
            if not trade_active and row['signal'] != 0 and not is_eod_exit:
                if current_time < trade_start_time or current_time > trade_end_time: continue
                if today_trades_count >= max_trades_per_day: continue
                if today_realized_pnl <= -abs(max_daily_loss): continue 
                if skip_today: continue 
                simulated_premium = row['close'] * simulated_premium_pct; cost_per_lot = simulated_premium * lot_size
                if cost_per_lot < min_investment: 
                    skip_today = True; continue 
                quantity_units = lot_size; invested_amount = cost_per_lot 
                position = quantity_units * (1 if row['signal'] == 1 else -1)
                entry_price = current_price; entry_index = i
                atm_strike = int(round(entry_price / 100.0) * 100)
                simulated_option_type = "ATM CALL" if position > 0 else "ATM PUT"; simulated_symbol = f"{simulated_option_type} @ {atm_strike}"
                stop_loss_price, take_profit_price = 0.0, 0.0
                temp_sl_mode = sl_mode
                if temp_sl_mode == "Invested Value (%)":
                    sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0; tp_ratio = params.get('tp_sl_ratio', 2.0)
                    sl_amount_total = invested_amount * sl_pct; sl_points_per_unit = sl_amount_total / quantity_units
                    tp_points_per_unit = sl_points_per_unit * tp_ratio
                    if position > 0: stop_loss_price = entry_price - sl_points_per_unit; take_profit_price = entry_price + tp_points_per_unit
                    else: stop_loss_price = entry_price + sl_points_per_unit; take_profit_price = entry_price - tp_points_per_unit
                elif temp_sl_mode == "ATR":
                    current_atr = row['atr']
                    if pd.isna(current_atr) or current_atr <= 0:
                        if not silent: st.warning(f"ATR is invalid ({current_atr}) at {timestamp}. Falling back to Invested Value SL/TP.")
                        temp_sl_mode = "Invested Value (%)"
                        sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0; tp_ratio = params.get('tp_sl_ratio', 2.0)
                        sl_amount_total = invested_amount * sl_pct; sl_points_per_unit = sl_amount_total / quantity_units
                        tp_points_per_unit = sl_points_per_unit * tp_ratio
                        if position > 0: stop_loss_price = entry_price - sl_points_per_unit; take_profit_price = entry_price + tp_points_per_unit
                        else: stop_loss_price = entry_price + sl_points_per_unit; take_profit_price = entry_price - tp_points_per_unit
                    else:
                        tp_points = current_atr * params.get('atr_tp_multiplier', 2.0); sl_points = current_atr * params.get('atr_sl_multiplier', 1.0)
                        if position > 0: take_profit_price = entry_price + tp_points; stop_loss_price = entry_price - sl_points
                        else: take_profit_price = entry_price - tp_points; stop_loss_price = entry_price + sl_points
                stop_loss_price = max(0.01, stop_loss_price) if not pd.isna(stop_loss_price) else entry_price * 0.9
                take_profit_price = max(0.01, take_profit_price) if not pd.isna(take_profit_price) else entry_price * 1.1
                current_trade = {'strategy': strategy_name, 'entry_time': timestamp, 'entry_price': entry_price, 'position': position, 'quantity': quantity_units, 'invested_amount': invested_amount, 'simulated_option': simulated_symbol, 'signal_strength': row.get('signal_strength', 0.5), 'signal_reason': row.get('signal_reason', ''), 'stop_loss': stop_loss_price, 'take_profit': take_profit_price}
                trade_active = True
                today_trades_count += 1
            current_equity = capital
            if trade_active:
                unrealized_pnl = (current_price - entry_price) * position if position > 0 else (entry_price - current_price) * abs(position)
                current_equity += unrealized_pnl
            equity_curve.append({'timestamp': timestamp, 'equity': current_equity, 'price': current_price})
            max_capital = max(max_capital, current_equity); drawdown = (max_capital - current_equity) / max_capital * 100 if max_capital > 0 else 0; max_drawdown = max(max_drawdown, drawdown)
        if trade_active:
            last_row = data.iloc[-1]; last_price = last_row['close']
            pnl = (last_price - entry_price) * position if position > 0 else (entry_price - last_price) * abs(position)
            invested_amount = current_trade.get('invested_amount', 1); return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
            current_trade.update({'exit_time': data.index[-1], 'exit_price': last_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': 'END_OF_DATA', 'trade_duration': len(data) - entry_index})
            trades.append(current_trade); capital += pnl
        return self._calculate_performance_metrics(trades, equity_curve, data, strategy_name, params, capital)

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
                                      'price': row['close'], 'strength': row.get('signal_strength', 0.5), 
                                      'reason': row.get('signal_reason', '')})
        return BacktestResult(total_trades,winning_trades,losing_trades,win_rate,total_pnl,max_drawdown,sharpe_ratio,profit_factor,avg_trade_pnl,best_trade,worst_trade,avg_winning_trade,avg_losing_trade,total_days,daily_return_avg,trades,equity_df,signals,monthly_returns,strategy_name,params)

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
    """Interactive strategy tester"""
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