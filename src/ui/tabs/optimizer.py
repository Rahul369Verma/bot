import streamlit as st
import pandas as pd
import random
import os
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
        'ema_pairs': [(9, 15), (9, 21), (10, 20), (5, 8), (9, 14), (8, 20), (8, 14)], # Fixed pairs
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
        'adx_threshold': (18, 30),
        
        # --- NEW: Additional Filters & Logic ---
        'max_trade_duration_minutes': (15, 120),
        'trailing_sl_multiplier': (1.0, 3.0),
        'candle_size_factor': (0.5, 2.0),
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
        opt_start_date = st.date_input("Start Date", datetime(2022, 11, 1).date(), key="opt_start")
        opt_end_date = st.date_input("End Date", datetime.now(), key="opt_end")
        
    # --- NEW: Optimizer Interval Selection ---
    opt_interval = st.selectbox("Optimizer Data Interval", ["5m", "1m"], index=0, key="opt_interval", help="Select the base timeframe for optimization.")
    opt_interval_map = {"1m": "1", "5m": "5"}
    selected_opt_interval = opt_interval_map[opt_interval]
        
    # --- NEW: Display Parameter Space ---
    with st.expander("ℹ️ View Parameter Search Space"):
        st.json(param_space)
        
    # --- NEW: Persistence Setup ---
    RESULTS_FILE = "optimizer_results.csv"
    
    if st.button("🗑️ Clear Saved Results", type="secondary"):
        if os.path.exists(RESULTS_FILE):
            os.remove(RESULTS_FILE)
            st.session_state.optimizer_results = []
            st.success("Saved results cleared!")
            st.rerun()
            
    # Load existing results
    existing_results_df = pd.DataFrame()
    seen_params = set()
    
    if os.path.exists(RESULTS_FILE):
        try:
            existing_results_df = pd.read_csv(RESULTS_FILE, on_bad_lines='skip')
            st.info(f"📂 Loaded {len(existing_results_df)} existing results from {RESULTS_FILE}. Resuming...")
            
            # Populate seen_params to avoid duplicates
            # We use a tuple of key parameters as the signature
            for _, row in existing_results_df.iterrows():
                # Create a signature tuple from the row
                # Ensure keys match what we generate in rand_params
                sig = (
                    row.get('ema_short'), row.get('ema_long'), row.get('atr_period'), 
                    row.get('tp_mult'), row.get('sl_mult'), row.get('max_trades'),
                    row.get('TSL'), row.get('TSL_Mult'), row.get('1H'), row.get('30M'), row.get('15M'),
                    row.get('Ribbon')
                )
                seen_params.add(sig)
        except Exception as e:
            st.error(f"Error loading existing results: {e}")

    if 'optimizer_results' not in st.session_state:
        st.session_state.optimizer_results = existing_results_df.to_dict('records')
        
    if st.button(f"🚀 RUN OPTIMIZER ({num_iterations} Iterations)", width='stretch', type="primary"):
        if not tester:
            st.error("Tester not initialized. Check Fyers credentials in Settings.")
        elif not fyers_manager or not fyers_manager.is_authenticated():
            st.error("Fyers API is not authenticated. Please go to the 'Settings' tab to generate a token.")
        else:
            st.session_state.optimizer_running = True 
            log_messages = []
            progress_bar = st.progress(0, text="Optimizer starting...")
            status_text = st.empty()
            current_params_display = st.empty() 
            results_placeholder = st.empty() 
            log_placeholder = st.empty() # Placeholder for live logs

            # Show existing results immediately
            if not existing_results_df.empty:
                 # Sort first
                existing_results_df = existing_results_df.sort_values(by="P&L (₹)", ascending=False)
                
                 # Format for display
                disp_df = existing_results_df.copy()
                cols_to_format = ['Sharpe', 'Win Rate (%)', 'P&L (₹)', 'Max DD (%)']
                # Ensure columns exist before formatting
                for col in cols_to_format:
                    if col in disp_df.columns:
                        if col == 'Sharpe': disp_df[col] = disp_df[col].map('{:,.2f}'.format)
                        elif col == 'P&L (₹)': disp_df[col] = disp_df[col].map('{:,.0f}'.format)
                        else: disp_df[col] = disp_df[col].map('{:,.1f}'.format)
                
                results_placeholder.dataframe(disp_df, width='stretch')

            try:
                status_text.text(f"Fetching Fyers data for {selected_index} from {opt_start_date} to {opt_end_date} (5m, 15m, 30m, 1h)...")
                
                # --- Pre-fetch all timeframes ONCE ---
                prefetched_data = {}
                
                # 5m (Base)
                df_5m = tester.engine.data_manager.get_historical_index_data(selected_index, opt_start_date, opt_end_date, "5", is_backtest_log=True)
                if df_5m is None or df_5m.empty: raise Exception("No 5m data returned.")
                prefetched_data['5m'] = df_5m
                
                # 15m
                df_15m = tester.engine.data_manager.get_historical_index_data(selected_index, opt_start_date, opt_end_date, "15", is_backtest_log=True)
                if df_15m is not None: prefetched_data['15m'] = df_15m
                
                # 30m
                df_30m = tester.engine.data_manager.get_historical_index_data(selected_index, opt_start_date, opt_end_date, "30", is_backtest_log=True)
                if df_30m is not None: prefetched_data['30m'] = df_30m
                
                # 1h
                df_1h = tester.engine.data_manager.get_historical_index_data(selected_index, opt_start_date, opt_end_date, "60", is_backtest_log=True)
                if df_1h is not None: prefetched_data['1h'] = df_1h
                
                status_text.text(f"Data fetched ({len(df_5m)} 5m candles). Starting {num_iterations} iterations...")
                
                for i in range(num_iterations):
                    try:
                        # --- UPDATED: rand_params with new filters ---
                        # Select random EMA pair
                        ema_pair = random.choice(param_space['ema_pairs'])
                        
                        rand_params = {
                            'ema_short': ema_pair[0],
                            'ema_long': ema_pair[1],
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
                            
                            # --- NEW: Additional Params ---
                            'use_1h_filter': random.choice([True, False]),
                            'use_30m_filter': random.choice([True, False]),
                            'use_15m_filter': random.choice([True, False]),
                            'use_ema_ribbon': random.choice([True, False]),
                            'use_trailing_sl': random.choice([True, False]),
                            'trailing_sl_multiplier': round(random.uniform(param_space['trailing_sl_multiplier'][0], param_space['trailing_sl_multiplier'][1]), 1),
                            'max_trade_duration_minutes': random.randint(param_space['max_trade_duration_minutes'][0], param_space['max_trade_duration_minutes'][1]),
                            'use_candle_size_filter': random.choice([True, False]),
                            'candle_size_factor': round(random.uniform(param_space['candle_size_factor'][0], param_space['candle_size_factor'][1]), 1),
                            'skip_last_week_expiry': random.choice([True, False]),
                            
                            'sl_mode': 'ATR', 
                            'initial_capital': 20000,
                        }
                        # EMA check removed as pairs are pre-validated
                        
                        # --- NEW: Check for Duplicates ---
                        current_sig = (
                            rand_params['ema_short'], rand_params['ema_long'], rand_params['atr_period'],
                            rand_params['atr_tp_multiplier'], rand_params['atr_sl_multiplier'], rand_params['max_trades_per_day'],
                            rand_params['use_trailing_sl'], rand_params['trailing_sl_multiplier'], 
                            rand_params['use_1h_filter'], rand_params['use_30m_filter'], rand_params['use_15m_filter'],
                            rand_params['use_ema_ribbon']
                        )
                        
                        if current_sig in seen_params:
                            log_messages.append(f"⚠️ Skipping duplicate params at iter {i+1}")
                            # Update log even for skips
                            log_placeholder.text_area("Optimization Log", value="\n".join(log_messages[-1000:]), height=300)
                            continue # Skip this iteration
                            
                        seen_params.add(current_sig)
                        
                        # Show current params
                        current_params_display.code(f"Iter {i+1}: EMA {rand_params['ema_short']}/{rand_params['ema_long']} | ATR {rand_params['atr_period']} x{rand_params['atr_tp_multiplier']}/{rand_params['atr_sl_multiplier']} | TSL: {rand_params['use_trailing_sl']} | 1H: {rand_params['use_1h_filter']} | 30M: {rand_params['use_30m_filter']} | 15M: {rand_params['use_15m_filter']} | Ribbon: {rand_params['use_ema_ribbon']}")
                        
                        result = tester.engine.run_backtest(
                            strategy_name=active_strategy_key,
                            symbol=selected_index,
                            start_date=opt_start_date,
                            end_date=opt_end_date,
                            interval="5", # Force 5m
                            silent=True, 
                            data=None, # Let run_backtest call prepare_data
                            backtest_mode="Simulated Premium (Fast & Approx.)",
                            prefetched_data=prefetched_data, # Pass pre-fetched data here
                            **rand_params
                        )

                        # Create result dict
                        result_dict = {
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
                            "RSI": rand_params['rsi_period'],
                            "OB": rand_params['rsi_overbought'],
                            "OS": rand_params['rsi_oversold'],
                            "ADX": rand_params['adx_period'],
                            "ADX_Th": rand_params['adx_threshold'],
                            "1H": rand_params['use_1h_filter'],
                            "30M": rand_params['use_30m_filter'],
                            "15M": rand_params['use_15m_filter'],
                            "Ribbon": rand_params['use_ema_ribbon'],
                            "TSL": rand_params['use_trailing_sl'],
                            "TSL_Mult": rand_params['trailing_sl_multiplier'],
                            "MaxDur": rand_params['max_trade_duration_minutes'],
                            "CandleSz": rand_params['use_candle_size_filter'],
                            "SkipExp": rand_params['skip_last_week_expiry'],
                        }
                        
                        # --- NEW: Save Result Immediately ---
                        # Append to session state
                        st.session_state.optimizer_results.append(result_dict)
                        
                        # Append to CSV
                        df_new = pd.DataFrame([result_dict])
                        if not os.path.exists(RESULTS_FILE):
                            df_new.to_csv(RESULTS_FILE, index=False)
                        else:
                            df_new.to_csv(RESULTS_FILE, mode='a', header=False, index=False)

                        # Use target metric inputs for check
                        is_good = (
                            result.sharpe_ratio >= target_sharpe and
                            result.win_rate > target_win_rate and
                            result.total_trades > target_trades and
                            result.max_drawdown < target_max_dd
                        )
                        
                        if is_good:
                            log_messages.append(f"✅ Found profitable result at iteration {i+1}!")
                            
                            # --- NEW: Update Real-time Results ---
                            results_df = pd.DataFrame(st.session_state.optimizer_results)
                            results_df = results_df.sort_values(by="P&L (₹)", ascending=False)
                            
                            # Format for display
                            disp_df = results_df.copy()
                            disp_df['Sharpe'] = disp_df['Sharpe'].map('{:,.2f}'.format)
                            disp_df['Win Rate (%)'] = disp_df['Win Rate (%)'].map('{:,.1f}'.format)
                            disp_df['P&L (₹)'] = disp_df['P&L (₹)'].map('{:,.0f}'.format)
                            disp_df['Max DD (%)'] = disp_df['Max DD (%)'].map('{:,.1f}'.format)
                            
                            results_placeholder.dataframe(disp_df, width='stretch')
                            
                            if not find_all_matches:
                                log_messages.append(f"🛑 Multi-Search is OFF. Stopping at first match.")
                                status_text.success("✅ Found first match! Stopping...")
                                log_placeholder.text_area("Optimization Log", value="\n".join(log_messages[-1000:]), height=300)
                                break 
                        else:
                            log_messages.append(f"Iter {i+1}: Sharpe {result.sharpe_ratio:.2f} | WR {result.win_rate:.1f}% | Trades {result.total_trades} | EMA {rand_params['ema_short']}/{rand_params['ema_long']}")
                    except Exception as e:
                        log_messages.append(f"❌ Iteration {i+1} failed: {e}")
                    
                    # --- NEW: Update Log Display Live ---
                    log_placeholder.text_area("Optimization Log", value="\n".join(log_messages[-1000:]), height=300)
                    progress_bar.progress((i + 1) / num_iterations, text=f"Optimizer running... {i+1}/{num_iterations}")
                
                if not find_all_matches and len(st.session_state.optimizer_results) > 0:
                    progress_bar.progress(1.0, text="Optimizer stopped after first match.")
                else:
                    progress_bar.progress(1.0, text="Optimization complete!")
                status_text.empty()
                # Final update
                log_placeholder.text_area("Optimization Log", value="\n".join(log_messages), height=300)

            finally:
                st.session_state.optimizer_running = False 
            st.success("Optimization Complete!")
            
            
    if st.session_state.optimizer_results:
        st.subheader("🏆 Optimizer Results")
        st.write(f"Found {len(st.session_state.optimizer_results)} combinations.")
        results_df = pd.DataFrame(st.session_state.optimizer_results)
        results_df = results_df.sort_values(by="P&L (₹)", ascending=False)
        
        # Format for display
        disp_df = results_df.copy()
        cols_to_format = ['Sharpe', 'Win Rate (%)', 'P&L (₹)', 'Max DD (%)']
        for col in cols_to_format:
            if col in disp_df.columns:
                if col == 'Sharpe': disp_df[col] = disp_df[col].map('{:,.2f}'.format)
                elif col == 'P&L (₹)': disp_df[col] = disp_df[col].map('{:,.0f}'.format)
                else: disp_df[col] = disp_df[col].map('{:,.1f}'.format)
                
        st.dataframe(disp_df, width='stretch')
    else:
        st.info("No optimization results yet. Run the optimizer to see results.")
