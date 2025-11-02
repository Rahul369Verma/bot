import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import streamlit as st
from .data_fetcher import BacktestDataManager # Make sure this import is correct


class BacktestResult:
    """Results from backtest execution"""
    # ... (no changes) ...
    def __init__(self, total_trades: int, winning_trades: int, losing_trades: int, win_rate: float,
                 total_pnl: float, max_drawdown: float, sharpe_ratio: float, profit_factor: float,
                 avg_trade_pnl: float, best_trade: float, worst_trade: float, avg_winning_trade: float,
                 avg_losing_trade: float, total_days: int, daily_return_avg: float, trade_details: List[Dict],
                 equity_curve: pd.DataFrame, signals_generated: List[Dict], monthly_returns: Dict[str, float],
                 strategy_name: str, parameters: Dict):
        # ... (init code) ...
        self.total_trades=total_trades; self.winning_trades=winning_trades; self.losing_trades=losing_trades; self.win_rate=win_rate
        self.total_pnl=total_pnl; self.max_drawdown=max_drawdown; self.sharpe_ratio=sharpe_ratio; self.profit_factor=profit_factor
        self.avg_trade_pnl=avg_trade_pnl; self.best_trade=best_trade; self.worst_trade=worst_trade; self.avg_winning_trade=avg_winning_trade
        self.avg_losing_trade=avg_losing_trade; self.total_days=total_days; self.daily_return_avg=daily_return_avg
        self.trade_details=trade_details; self.equity_curve=equity_curve; self.signals_generated=signals_generated
        self.monthly_returns=monthly_returns; self.strategy_name=strategy_name; self.parameters=parameters

class StrategyTemplate:
    """Base class for all trading strategies"""
    # ... (no changes) ...
    def __init__(self, name: str, description: str = ""): self.name=name; self.description=description; self.parameters={}
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: raise NotImplementedError
    def calculate_indicators(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: return data

# --- UPDATED: Trend Following Strategy ---
class EmaTrendFollowingStrategy(StrategyTemplate):
    """
    1. Sets a daily trend (UP/DOWN) based on the first 15m EMA cross of the day.
    2. Only takes 5m EMA alignment signals that match the locked-in daily trend.
    """
    def __init__(self):
        super().__init__(
            name="5m State / 15m Daily Trend Strategy",
            description="Locks 15m trend for the day. Enters on 5m alignment."
        )
        self.parameters = {
            'ema_short': 9,
            'ema_long': 15,
            'lot_size': 35, 
            'min_investment': 10000, 
            'simulated_premium_pct': 0.008,
            'sl_mode': 'Invested Value (%)', 
            'invested_value_sl_pct': 5.0, 
            'tp_sl_ratio': 2.0,
            'atr_period': 14,              
            'atr_tp_multiplier': 0.5,
            'atr_sl_multiplier': 0.5,
        }

    def _resample_to_15min(self, df_5min: pd.DataFrame) -> pd.DataFrame:
        """Resamples 5-minute data to 15-minute candles."""
        # --- REMOVED TIMEZONE LOGIC ---
        # Data is already naive IST, just resample
        df_15min = df_5min.resample('15min').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        return df_15min

    def calculate_indicators(self, data_5min: pd.DataFrame, **kwargs) -> tuple[pd.DataFrame, pd.DataFrame]:
        # ... (no changes in this method) ...
        df_5m = data_5min.copy()
        ema_short_period = kwargs.get('ema_short', self.parameters['ema_short'])
        ema_long_period = kwargs.get('ema_long', self.parameters['ema_long'])
        df_5m['ema_short'] = df_5m['close'].ewm(span=ema_short_period, adjust=False).mean()
        df_5m['ema_long'] = df_5m['close'].ewm(span=ema_long_period, adjust=False).mean()
        atr_period = kwargs.get('atr_period', self.parameters['atr_period'])
        df_5m['tr1'] = abs(df_5m['high'] - df_5m['low']); df_5m['tr2'] = abs(df_5m['high'] - df_5m['close'].shift(1)); df_5m['tr3'] = abs(df_5m['low'] - df_5m['close'].shift(1))
        df_5m['true_range'] = df_5m[['tr1', 'tr2', 'tr3']].max(axis=1)
        df_5m['atr'] = df_5m['true_range'].rolling(window=atr_period).mean().bfill(); df_5m['atr'] = df_5m['atr'].ewm(alpha=1/atr_period, adjust=False).mean()
        df_15m = self._resample_to_15min(df_5m)
        df_15m['ema_short'] = df_15m['close'].ewm(span=ema_short_period, adjust=False).mean()
        df_15m['ema_long'] = df_15m['close'].ewm(span=ema_long_period, adjust=False).mean()
        return df_5m, df_15m

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        # ... (no changes in this method) ...
        df_5m, df_15m = self.calculate_indicators(data, **kwargs)
        df_5m['15m_timestamp'] = df_5m.index.floor('15min')
        df_5m = pd.merge(df_5m, df_15m[['ema_short', 'ema_long']], left_on='15m_timestamp', right_index=True, how='left', suffixes=('', '_15m'))
        df_5m[['ema_short_15m', 'ema_long_15m']] = df_5m[['ema_short_15m', 'ema_long_15m']].ffill().bfill()
        df_5m['signal'] = 0; df_5m['signal_strength'] = 0.0; df_5m['signal_reason'] = ""
        min_periods = max(self.parameters['ema_long'], kwargs.get('atr_period', 14)) + 1
        daily_trend = 'NEUTRAL'; current_day = None
        prev_aligned_bull = False; prev_aligned_bear = False
        for i in range(min_periods, len(df_5m)):
            current_5m = df_5m.iloc[i]
            if current_day is None or current_5m.name.date() != current_day:
                current_day = current_5m.name.date(); daily_trend = 'NEUTRAL'
                prev_aligned_bull = False; prev_aligned_bear = False
            if pd.isna(current_5m['ema_short']) or pd.isna(current_5m['ema_long']) or pd.isna(current_5m['ema_short_15m']) or pd.isna(current_5m['ema_long_15m']): continue
            if daily_trend == 'NEUTRAL':
                is_15m_uptrend = current_5m['ema_short_15m'] > current_5m['ema_long_15m']
                is_15m_downtrend = current_5m['ema_short_15m'] < current_5m['ema_long_15m']
                if is_15m_uptrend: daily_trend = 'UP'
                elif is_15m_downtrend: daily_trend = 'DOWN'
            is_5m_bullish = current_5m['ema_short'] > current_5m['ema_long']
            is_5m_bearish = current_5m['ema_short'] < current_5m['ema_long']
            currently_aligned_bull = (daily_trend == 'UP') and is_5m_bullish
            currently_aligned_bear = (daily_trend == 'DOWN') and is_5m_bearish
            if currently_aligned_bull and not prev_aligned_bull:
                df_5m.loc[df_5m.index[i], 'signal'] = 1; df_5m.loc[df_5m.index[i], 'signal_strength'] = 0.65
                df_5m.loc[df_5m.index[i], 'signal_reason'] = "5m-Bull align with Daily-UP-Trend"
            elif currently_aligned_bear and not prev_aligned_bear:
                df_5m.loc[df_5m.index[i], 'signal'] = -1; df_5m.loc[df_5m.index[i], 'signal_strength'] = 0.65
                df_5m.loc[df_5m.index[i], 'signal_reason'] = "5m-Bear align with Daily-DOWN-Trend"
            prev_aligned_bull = currently_aligned_bull; prev_aligned_bear = currently_aligned_bear
        return df_5m


# --- Old Strategies (Unchanged) ---
class EmaFastCrossoverStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Fast EMA Crossover (Scalp Sim)", description="..."); self.parameters = {...}
    pass
class EmaTrendConfirmationStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="5m Entry / 15m Trend EMA Strategy", description="..."); self.parameters = {...}
    pass
class EmaMomentumStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Momentum Strategy", description="..."); self.parameters = {...}
    pass
class EMAStrategy(StrategyTemplate):
    def __init__(self): super().__init__(name="9-15 EMA Confluence Strategy (Strict)", description="..."); self.parameters = {...}
    pass

class BacktestEngine:
    """Main backtesting engine with risk management"""

    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital 
        self.strategies = {}
        self.data_manager = BacktestDataManager()
        self.register_builtin_strategies()

    def register_builtin_strategies(self):
        """Register built-in strategies"""
        self.strategies['ema_daily_trend'] = EmaTrendFollowingStrategy() # NEW DEFAULT
        self.strategies['ema_scalp_sim'] = EmaFastCrossoverStrategy()
        self.strategies['ema_trend_confirm'] = EmaTrendConfirmationStrategy()
        self.strategies['ema_momentum'] = EmaMomentumStrategy()
        self.strategies['ema_confluence_strict'] = EMAStrategy()

    def register_strategy(self, name: str, strategy: StrategyTemplate): self.strategies[name] = strategy

    def run_backtest(self, strategy_name: str, symbol: str = "BANKNIFTY",
                    period: str = "60d", interval: str = "5m",
                    **strategy_params) -> BacktestResult:
        
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' not found. Available: {list(self.strategies.keys())}")
        
        self.initial_capital = strategy_params.get('initial_capital', 100000)
        
        if strategy_name in ['ema_daily_trend', 'ema_scalp_sim', 'ema_trend_following', 'ema_trend_confirm']:
            interval = '5m' 
            st.info(f"Using '5m' interval for the '{strategy_name}' strategy.")
            if period not in ['1d', '5d', '1mo', '60d']:
                 st.warning(f"Period '{period}' may be too long for 5m data (max 60d). Data might be limited.")
        
        data = self.data_manager.get_backtest_data(symbol, period, interval)
        if data is None or data.empty:
             st.error("Failed to load data. Backtest cannot proceed.")
             return BacktestResult(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],pd.DataFrame(),[],{},"",{})

        strategy = self.strategies[strategy_name]
        original_params = strategy.parameters.copy()
        merged_params = {**strategy.parameters, **strategy_params}
        strategy.parameters = merged_params 

        st.info(f"🔍 Generating signals using '{strategy.name}' on {interval} data...")
        data_with_signals = strategy.generate_signals(data, **merged_params)

        st.info("💰 Executing trades with risk management...")
        result = self._execute_trades_with_risk_management(data_with_signals, strategy_name, merged_params)

        strategy.parameters = original_params # Restore defaults
        return result

    def _execute_trades_with_risk_management(self, data: pd.DataFrame, strategy_name: str, params: Dict) -> BacktestResult:
        """
        Executes trades with all new rules:
        1. "2 Stop-Loss hits" per day rule.
        2. "1 Lot > 10k" filter and "skip day" rule.
        3. Selectable SL/TP (Invested Value vs ATR).
        """
        
        trades = []
        position = 0; entry_price = 0; entry_index = 0
        trade_active = False; current_trade = {}
        
        capital = self.initial_capital 
        equity_curve = []
        max_capital = capital
        max_drawdown = 0

        # --- Daily State Variables ---
        today_sl_count = 0
        skip_today = False 
        current_day = None

        lot_size = params.get('lot_size', 35)
        sl_mode = params.get('sl_mode', 'Invested Value (%)') 
        min_investment = params.get('min_investment', 10000)
        simulated_premium_pct = params.get('simulated_premium_pct', 0.008)

        if sl_mode == "ATR" and 'atr' not in data.columns:
            st.error("ATR column missing, cannot use ATR stop-loss mode.")
            raise ValueError("ATR column missing") 

        for i, (timestamp, row) in enumerate(data.iterrows()):
            
            # --- NEW: Daily Logic ---
            # Timestamp is now naive IST, so .date() is correct
            trade_date = timestamp.date()
            if current_day != trade_date:
                current_day = trade_date
                today_sl_count = 0 
                skip_today = False 
            
            if pd.isna(row['close']) or (sl_mode == "ATR" and pd.isna(row['atr'])):
                equity_curve.append({'timestamp': timestamp, 'equity': capital, 'price': np.nan})
                continue
            
            current_price = row['close']

            # Check for SL/TP
            if trade_active:
                # ... (SL/TP trigger logic remains the same) ...
                stop_loss_price = current_trade.get('stop_loss', 0)
                take_profit_price = current_trade.get('take_profit', float('inf') if position > 0 else 0)
                stop_loss_trigger = False; take_profit_trigger = False
                if position > 0:  # Long
                    if current_price <= stop_loss_price: stop_loss_trigger = True
                    elif current_price >= take_profit_price: take_profit_trigger = True
                elif position < 0: # Short
                    if current_price >= stop_loss_price: stop_loss_trigger = True
                    elif current_price <= take_profit_price: take_profit_trigger = True

                if stop_loss_trigger or take_profit_trigger:
                    exit_price = current_price
                    if stop_loss_trigger: 
                        exit_price = stop_loss_price
                        today_sl_count += 1 # Increment SL counter
                    if take_profit_trigger: exit_price = take_profit_price
                    exit_price = max(0.01, exit_price)
                    if position > 0: pnl = (exit_price - entry_price) * position
                    else: pnl = (entry_price - exit_price) * abs(position)
                    invested_amount = current_trade.get('invested_amount', 1)
                    return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
                    current_trade.update({'exit_time': timestamp, 'exit_price': exit_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': 'STOP_LOSS' if stop_loss_trigger else 'TAKE_PROFIT', 'trade_duration': i - entry_index})
                    trades.append(current_trade); capital += pnl; trade_active = False; position = 0
            
            # Open new position
            if not trade_active and row['signal'] != 0:
                
                if today_sl_count >= 2: continue 
                if skip_today: continue 
                
                simulated_premium = row['close'] * simulated_premium_pct
                cost_per_lot = simulated_premium * lot_size
                
                if cost_per_lot < min_investment:
                    skip_today = True 
                    continue 
                
                quantity_units = lot_size # Always 1 lot
                invested_amount = cost_per_lot 
                
                position = quantity_units * (1 if row['signal'] == 1 else -1)
                entry_price = current_price
                entry_index = i
                
                atm_strike = int(round(entry_price / 100.0) * 100)
                simulated_option_type = "ATM CALL" if position > 0 else "ATM PUT"
                simulated_symbol = f"{simulated_option_type} @ {atm_strike}"
                
                stop_loss_price = 0.0
                take_profit_price = 0.0
                
                temp_sl_mode = sl_mode
                
                if temp_sl_mode == "Invested Value (%)":
                    sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0
                    tp_ratio = params.get('tp_sl_ratio', 2.0)
                    sl_amount_total = invested_amount * sl_pct
                    sl_points_per_unit = sl_amount_total / quantity_units
                    tp_points_per_unit = sl_points_per_unit * tp_ratio
                    
                    if position > 0: # Long
                        stop_loss_price = entry_price - sl_points_per_unit
                        take_profit_price = entry_price + tp_points_per_unit
                    else: # Short
                        stop_loss_price = entry_price + sl_points_per_unit
                        take_profit_price = entry_price - tp_points_per_unit

                elif temp_sl_mode == "ATR":
                    current_atr = row['atr']
                    if pd.isna(current_atr) or current_atr <= 0:
                        st.warning(f"ATR is invalid ({current_atr}) at {timestamp}. Falling back to Invested Value SL/TP for this trade.")
                        temp_sl_mode = "Invested Value (%)" # Fallback
                        sl_pct = params.get('invested_value_sl_pct', 5.0) / 100.0; tp_ratio = params.get('tp_sl_ratio', 2.0)
                        sl_amount_total = invested_amount * sl_pct; sl_points_per_unit = sl_amount_total / quantity_units
                        tp_points_per_unit = sl_points_per_unit * tp_ratio
                        if position > 0: stop_loss_price = entry_price - sl_points_per_unit; take_profit_price = entry_price + tp_points_per_unit
                        else: stop_loss_price = entry_price + sl_points_per_unit; take_profit_price = entry_price - tp_points_per_unit
                    else:
                        tp_points = current_atr * params.get('atr_tp_multiplier', 2.0)
                        sl_points = current_atr * params.get('atr_sl_multiplier', 1.0)
                        if position > 0: take_profit_price = entry_price + tp_points; stop_loss_price = entry_price - sl_points
                        else: take_profit_price = entry_price - tp_points; stop_loss_price = entry_price + sl_points
                
                elif temp_sl_mode == "Index Percentage":
                    stop_loss_pct_val = params.get('stop_loss_pct', 0.1) / 100
                    take_profit_pct_val = params.get('take_profit_pct', 0.1) / 100
                    if position > 0: take_profit_price = entry_price * (1 + take_profit_pct_val); stop_loss_price = entry_price * (1 - stop_loss_pct_val)
                    else: take_profit_price = entry_price * (1 - take_profit_pct_val); stop_loss_price = entry_price * (1 + stop_loss_pct_val)
                
                stop_loss_price = max(0.01, stop_loss_price) if not pd.isna(stop_loss_price) else entry_price * 0.9
                take_profit_price = max(0.01, take_profit_price) if not pd.isna(take_profit_price) else entry_price * 1.1
                
                current_trade = {
                    'strategy': strategy_name, 'entry_time': timestamp, 'entry_price': entry_price, 
                    'position': position, 'quantity': quantity_units, 'invested_amount': invested_amount, 
                    'simulated_option': simulated_symbol, 'signal_strength': row.get('signal_strength', 0.5), 
                    'signal_reason': row.get('signal_reason', ''), 'stop_loss': stop_loss_price, 'take_profit': take_profit_price
                }
                trade_active = True

            # Update equity curve
            current_equity = capital
            if trade_active:
                if position > 0: unrealized_pnl = (current_price - entry_price) * position
                else: unrealized_pnl = (entry_price - current_price) * abs(position)
                current_equity += unrealized_pnl
            equity_curve.append({'timestamp': timestamp, 'equity': current_equity, 'price': current_price})
            
            max_capital = max(max_capital, current_equity)
            drawdown = (max_capital - current_equity) / max_capital * 100 if max_capital > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        # Close any remaining position at the end
        if trade_active:
            # ... (logic remains the same) ...
            last_row = data.iloc[-1]; last_price = last_row['close']
            if position > 0: pnl = (last_price - entry_price) * position
            else: pnl = (entry_price - last_price) * abs(position)
            invested_amount = current_trade.get('invested_amount', 1); return_pct = (pnl / invested_amount) * 100 if invested_amount else 0
            current_trade.update({'exit_time': data.index[-1], 'exit_price': last_price, 'pnl': pnl, 'return_pct': return_pct, 'exit_reason': 'END_OF_DATA', 'trade_duration': len(data) - entry_index})
            trades.append(current_trade); capital += pnl
        
        return self._calculate_performance_metrics(trades, equity_curve, data, strategy_name, params, capital)

    # ... (_calculate_performance_metrics method remains the same) ...
    def _calculate_performance_metrics(self, trades: List[Dict], equity_curve: List[Dict],
                                     data: pd.DataFrame, strategy_name: str, params: Dict,
                                     final_capital: float) -> BacktestResult:
        # ... (implementation as before) ...
        total_trades=len(trades); winning_trades=len([t for t in trades if t['pnl'] > 0]); losing_trades=total_trades-winning_trades
        win_rate=(winning_trades/total_trades*100) if total_trades > 0 else 0
        total_pnl=final_capital-self.initial_capital; avg_trade_pnl=total_pnl/total_trades if total_trades > 0 else 0
        winning_pnls=[t['pnl'] for t in trades if t['pnl'] > 0]; losing_pnls=[t['pnl'] for t in trades if t['pnl'] < 0]
        best_trade=max([t['pnl'] for t in trades]) if trades else 0; worst_trade=min([t['pnl'] for t in trades]) if trades else 0
        avg_winning_trade=np.mean(winning_pnls) if winning_pnls else 0; avg_losing_trade=np.mean(losing_pnls) if losing_pnls else 0
        returns=[t['return_pct']/100 for t in trades if t.get('return_pct') is not None]
        if returns and len(returns)>1: std_dev=np.std(returns); sharpe_ratio=np.mean(returns)/std_dev if std_dev>0 else 0
        else: sharpe_ratio=0
        gross_profit=sum(t['pnl'] for t in trades if t['pnl']>0); gross_loss=abs(sum(t['pnl'] for t in trades if t['pnl']<0))
        profit_factor=gross_profit/gross_loss if gross_loss>0 else float('inf')
        equity_df=pd.DataFrame(equity_curve).set_index('timestamp')
        if not equity_df.empty:
            equity_df['peak']=equity_df['equity'].expanding().max()
            equity_df['drawdown_pct']=(equity_df['equity']-equity_df['peak'])/equity_df['peak']
            max_drawdown_series = equity_df['drawdown_pct'].dropna()
            max_drawdown=abs(max_drawdown_series.min())*100 if not max_drawdown_series.empty else 0
        else: max_drawdown=0
        if trades:
            first_trade=min(t['entry_time'] for t in trades); last_trade=max(t['exit_time'] for t in trades)
            total_days=(last_trade-first_trade).days+1
            daily_return_avg=(total_pnl/self.initial_capital)/total_days*100 if total_days>0 else 0
        else: total_days=0; daily_return_avg=0
        monthly_returns=self._calculate_monthly_returns(trades)
        signals=[];
        if 'signal' in data.columns:
            for i, (timestamp, row) in enumerate(data.iterrows()):
                 if row['signal'] != 0:
                      signals.append({'timestamp': timestamp, 'signal': 'BUY' if row['signal'] == 1 else 'SELL', 'price': row['close'], 'strength': row.get('signal_strength', 0.5), 'reason': row.get('signal_reason', ''), 'ema_short': row.get('ema_short'), 'ema_long': row.get('ema_long')})
        return BacktestResult(total_trades=total_trades,winning_trades=winning_trades,losing_trades=losing_trades,win_rate=win_rate,total_pnl=total_pnl,max_drawdown=max_drawdown,sharpe_ratio=sharpe_ratio,profit_factor=profit_factor,avg_trade_pnl=avg_trade_pnl,best_trade=best_trade,worst_trade=worst_trade,avg_winning_trade=avg_winning_trade,avg_losing_trade=avg_losing_trade,total_days=total_days,daily_return_avg=daily_return_avg,trade_details=trades,equity_curve=equity_df,signals_generated=signals,monthly_returns=monthly_returns,strategy_name=strategy_name,parameters=params)

    # ... (_calculate_monthly_returns method remains the same) ...
    def _calculate_monthly_returns(self, trades: List[Dict]) -> Dict[str, float]:
        monthly_returns = {};
        if not trades: return monthly_returns
        trades_df = pd.DataFrame(trades); trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        trades_df['month'] = trades_df['entry_time'].dt.strftime('%Y-%m')
        monthly_pnl = trades_df.groupby('month')['pnl'].sum()
        for month, pnl in monthly_pnl.items(): monthly_returns[month] = pnl
        return monthly_returns


class StrategyTester:
    """Interactive strategy tester"""
    # ... (no changes) ...
    def __init__(self): self.engine = BacktestEngine(); self.custom_strategies = {}
    def create_custom_strategy(self, code: str, strategy_name: str) -> bool:
        try:
            exec_globals = {'pd': pd, 'np': np, 'StrategyTemplate': StrategyTemplate}
            exec(code, exec_globals)
            for obj in exec_globals.values():
                if (isinstance(obj, type) and issubclass(obj, StrategyTemplate) and obj != StrategyTemplate):
                    strategy_instance = obj(); self.engine.register_strategy(strategy_name, strategy_instance)
                    self.custom_strategies[strategy_name] = strategy_instance; return True
            st.error("Custom code did not define a class inheriting from StrategyTemplate.")
            return False
        except Exception as e: st.error(f"Error creating custom strategy: {e}"); return False
    def get_available_strategies(self) -> List[str]: return list(self.engine.strategies.keys())
    def get_strategy_parameters(self, strategy_name: str) -> Dict:
        if strategy_name in self.engine.strategies: return self.engine.strategies[strategy_name].parameters
        return {}

# ... (CUSTOM_STRATEGY_TEMPLATE remains the same) ...
# Example custom strategy template
CUSTOM_STRATEGY_TEMPLATE = '''
# ... (template remains the same) ...
class CustomStrategy(StrategyTemplate):
    """Custom strategy template"""
    def __init__(self): super().__init__("Custom Strategy"); self.parameters = {'param1': 10, 'param2': 20}
    def calculate_indicators(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: df = data.copy(); return df
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame: df = self.calculate_indicators(data, **kwargs); df['signal'] = 0; return df
'''