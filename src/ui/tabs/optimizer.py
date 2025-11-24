import streamlit as st
import pandas as pd
import random
from datetime import datetime, timedelta, time as dt_time

def render_optimizer_tab(tester, selected_index, fyers_manager, active_strategy_key):
    """Renders the Optimizer tab."""
    st.subheader("🚀 Strategy Parameter Optimizer")
    st.markdown(f"This tool will run many backtests with random parameters for the **MTA Crossover** strategy on **{selected_index}** to find profitable combinations.")
    st.info("Optimizer always runs in **Simulated Premium** mode for speed.")

    # --- UPDATED: Target Metrics Inputs ---
    st.markdown("#### 🎯 Target Metrics (For Filtering)")
    tcol1, tcol2, tcol3, tcol4 = st.columns(4)
    with tcol1:
        target_sharpe = st.number_input("Min Sharpe Ratio", min_value=0.0, value=0.3, step=0.1, format="%.1f", key="opt_sharpe")
    with tcol2:
        target_win_rate = st.number_input("Min Win Rate (%)", min_value=0, max_value=100, value=40, step=1, key="opt_wr")
    with tcol3:
        target_trades = st.number_input("Min Total Trades", min_value=1, value=10, step=1, key="opt_trades")
    with tcol4:
        target_max_dd = st.number_input("Max Drawdown (%)", min_value=0, max_value=100, value=50, step=1, key="opt_dd")
    
    # --- UPDATED: param_space with new filters ---
    param_space = {
        'ema_short': (5, 15),
        'ema_long': (16, 40),
        'atr_period': (10, 30),
        'atr_tp_multiplier': (1.5, 5.0),
        'atr_sl_multiplier': (0.5, 2.0),
        'max_trades_per_day': (1, 10),
        'trade_start_time': (dt_time(9, 16), dt_time(11, 0)),
        'trade_end_time': (dt_time(13, 0), dt_time(15, 15)),
        'simulated_premium_pct': (0.005, 0.015), # 0.5% to 1.5%
        'simulated_delta': (0.4, 0.7),
        
        # --- NEW: Optimizer ranges for ADX/RSI ---
        'rsi_period': (10, 30),
        'rsi_overbought': (65, 80),
        'rsi_oversold': (20, 35),
        'adx_period': (10, 20),
        'adx_threshold': (18, 30)
    }
    
    def random_time(start, end):
        start_ts = int(start.hour * 60 + start.minute)
        end_ts = int(end.hour * 60 + end.minute)
        rand_ts = random.randint(start_ts, end_ts)
        return dt_time(rand_ts // 60, rand_ts % 60)
    
    opt_col1, opt_col2 = st.columns(2)
    with opt_col1:
        num_iterations = st.number_input("Number of Iterations", min_value=10, max_value=1000, value=200, step=10)
        find_all_matches = st.toggle("Find All Matches (Multi-Search)", value=True, help="If OFF, stop after the first match. If ON, run all iterations.")
    with opt_col2:
        opt_start_date = st.date_input("Start Date", datetime.now() - timedelta(days=365*2), key="opt_start")
        opt_end_date = st.date_input("End Date", datetime.now(), key="opt_end")
        
    # --- NEW: Optimizer Interval Selection ---
    opt_interval = st.selectbox("Optimizer Data Interval", ["1m", "5m"], index=0, key="opt_interval", help="Select the base timeframe for optimization.")
    opt_interval_map = {"1m": "1", "5m": "5"}
    selected_opt_interval = opt_interval_map[opt_interval]
        
    if 'optimizer_results' not in st.session_state:
        st.session_state.optimizer_results = []
        
    if st.button(f"🚀 RUN OPTIMIZER ({num_iterations} Iterations)", use_container_width=True, type="primary"):
        if not tester:
            st.error("Tester not initialized. Check Fyers credentials in Settings.")
        elif not fyers_manager or not fyers_manager.is_authenticated():
            st.error("Fyers API is not authenticated. Please go to the 'Settings' tab to generate a token.")
        else:
            st.session_state.optimizer_running = True 
            log_messages = []
            progress_bar = st.progress(0, text="Optimizer starting...")
            status_text = st.empty()
            try:
                status_text.text(f"Fetching Fyers data for {selected_index} from {opt_start_date} to {opt_end_date} ({opt_interval})...")
                data = tester.engine.data_manager.get_historical_index_data(
                    selected_index, opt_start_date, opt_end_date, selected_opt_interval, is_backtest_log=True
                )
                if data is None or data.empty:
                    raise Exception("No data returned for optimizer.")
                status_text.text(f"Data fetched ({len(data)} candles). Starting {num_iterations} iterations...")
                st.session_state.optimizer_results = []
                
                for i in range(num_iterations):
                    try:
                        # --- UPDATED: rand_params with new filters ---
                        rand_params = {
                            'ema_short': random.randint(param_space['ema_short'][0], param_space['ema_short'][1]),
                            'ema_long': random.randint(param_space['ema_long'][0], param_space['ema_long'][1]),
                            'atr_period': random.randint(param_space['atr_period'][0], param_space['atr_period'][1]),
                            'atr_tp_multiplier': round(random.uniform(param_space['atr_tp_multiplier'][0], param_space['atr_tp_multiplier'][1]), 2),
                            'atr_sl_multiplier': round(random.uniform(param_space['atr_sl_multiplier'][0], param_space['atr_sl_multiplier'][1]), 2),
                            'max_trades_per_day': random.randint(param_space['max_trades_per_day'][0], param_space['max_trades_per_day'][1]),
                            'trade_start_time': random_time(param_space['trade_start_time'][0], param_space['trade_start_time'][1]),
                            'trade_end_time': random_time(param_space['trade_end_time'][0], param_space['trade_end_time'][1]),
                            'simulated_premium_pct': round(random.uniform(param_space['simulated_premium_pct'][0], param_space['simulated_premium_pct'][1]), 4),
                            'simulated_delta': round(random.uniform(param_space['simulated_delta'][0], param_space['simulated_delta'][1]), 2),
                            
                            # --- NEW: Randomize ADX/RSI params ---
                            'use_rsi_filter': True,
                            'rsi_period': random.randint(param_space['rsi_period'][0], param_space['rsi_period'][1]),
                            'rsi_overbought': random.randint(param_space['rsi_overbought'][0], param_space['rsi_overbought'][1]),
                            'rsi_oversold': random.randint(param_space['rsi_oversold'][0], param_space['rsi_oversold'][1]),
                            'use_adx_filter': True,
                            'adx_period': random.randint(param_space['adx_period'][0], param_space['adx_period'][1]),
                            'adx_threshold': random.randint(param_space['adx_threshold'][0], param_space['adx_threshold'][1]),
                            
                            'sl_mode': 'ATR', 
                            'initial_capital': 20000,
                        }
                        if rand_params['ema_short'] >= rand_params['ema_long']:
                            rand_params['ema_long'] = rand_params['ema_short'] + 1
                        
                        result = tester.engine.run_backtest(
                            strategy_name=active_strategy_key,
                            symbol=selected_index,
                            start_date=opt_start_date,
                            end_date=opt_end_date,
                            interval=selected_opt_interval,
                            silent=True, 
                            data=data.copy(),
                            backtest_mode="Simulated Premium (Fast & Approx.)", # Always use fast mode
                            **rand_params
                        )

                        # Use target metric inputs for check
                        is_good = (
                            result.sharpe_ratio >= target_sharpe and
                            result.win_rate > target_win_rate and
                            result.total_trades > target_trades and
                            result.max_drawdown < target_max_dd
                        )
                        
                        if is_good:
                            log_messages.append(f"✅ Found profitable result at iteration {i+1}!")
                            # --- UPDATED: Add new params to results dict ---
                            st.session_state.optimizer_results.append({
                                "Sharpe": result.sharpe_ratio,
                                "Win Rate (%)": result.win_rate,
                                "P&L (₹)": result.total_pnl,
                                "Max DD (%)": result.max_drawdown,
                                "Trades": result.total_trades,
                                "ema_short": rand_params['ema_short'],
                                "ema_long": rand_params['ema_long'],
                                "atr_period": rand_params['atr_period'],
                                "tp_mult": rand_params['atr_tp_multiplier'],
                                "sl_mult": rand_params['atr_sl_multiplier'],
                                "max_trades": rand_params['max_trades_per_day'],
                                "start_time": rand_params['trade_start_time'].strftime("%H:%M"),
                                "end_time": rand_params['trade_end_time'].strftime("%H:%M"),
                                "sim_delta": rand_params['simulated_delta'],
                                "sim_prem_pct": rand_params['simulated_premium_pct'],
                                # --- NEW ---
                                "RSI": rand_params['rsi_period'],
                                "OB": rand_params['rsi_overbought'],
                                "OS": rand_params['rsi_oversold'],
                                "ADX": rand_params['adx_period'],
                                "ADX_Th": rand_params['adx_threshold'],
                            })
                            if not find_all_matches:
                                log_messages.append(f"🛑 Multi-Search is OFF. Stopping at first match.")
                                status_text.success("✅ Found first match! Stopping...")
                                break 
                        else:
                            log_messages.append(f"Iteration {i+1}: Sharpe {result.sharpe_ratio:.2f}, WR {result.win_rate:.1f}%, Trades {result.total_trades}, DD {result.max_drawdown:.1f}%")
                    except Exception as e:
                        log_messages.append(f"❌ Iteration {i+1} failed: {e}")
                    progress_bar.progress((i + 1) / num_iterations, text=f"Optimizer running... {i+1}/{num_iterations}")
                
                if not find_all_matches and len(st.session_state.optimizer_results) > 0:
                    progress_bar.progress(1.0, text="Optimizer stopped after first match.")
                else:
                    progress_bar.progress(1.0, text="Optimization complete!")
                status_text.empty()
                st.text_area("Optimization Log", value="\n".join(log_messages), height=300)

            finally:
                st.session_state.optimizer_running = False 
            st.success("Optimization Complete!")
            
            
    if st.session_state.optimizer_results:
        st.subheader("🏆 Optimizer Results")
        st.write(f"Found {len(st.session_state.optimizer_results)} combinations that meet your criteria.")
        results_df = pd.DataFrame(st.session_state.optimizer_results)
        results_df['Sharpe'] = results_df['Sharpe'].map('{:,.2f}'.format)
        results_df['Win Rate (%)'] = results_df['Win Rate (%)'].map('{:,.1f}'.format)
        results_df['P&L (₹)'] = results_df['P&L (₹)'].map('{:,.0f}'.format)
        results_df['Max DD (%)'] = results_df['Max DD (%)'].map('{:,.1f}'.format)
        st.dataframe(results_df.sort_values(by="Sharpe", ascending=False), use_container_width=True)
    else:
        st.info("No optimization results yet. Run the optimizer to see results.")
