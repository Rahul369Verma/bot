import streamlit as st
import pandas as pd
import gc
from datetime import datetime, time as dt_time

def render_backtest_tab(tester, selected_index, fyers_manager):
    """Renders the Backtest tab."""
    st.subheader(f"🧪 Backtest Engine (Index: {selected_index})") 

    if not tester:
        st.error("StrategyTester failed to initialize. Check Fyers credentials in Settings.")
    else:
        bt_strategy_key = "mta_ema_crossover"
        bt_strategy_params_default = tester.get_strategy_parameters(bt_strategy_key)
        st.info(tester.engine.strategies[bt_strategy_key].description)
        
        # --- NEW: Interval Selection ---
        # Default to 5m for MTA Strategy
        data_interval = st.selectbox("Data Interval", ["5m", "1m"], index=0, help="Select the base timeframe for data fetching and signal generation. MTA Strategy uses 5m base.")
        interval_map = {"1m": "1", "5m": "5"}
        selected_interval = interval_map[data_interval]
        
        st.info(f"Using **{data_interval}** data interval from Fyers.")

        backtest_mode = st.radio(
            "Backtest Mode",
            ["Real Option Data (Slow & Accurate)", "Simulated Premium (Fast & Approx.)"],
            index=0,
            key="bt_mode",
            horizontal=True,
            help="**Real Option Data:** Fetches actual historical option data for every trade. Very accurate, but slower. \n\n**Simulated Premium:** *Does not* fetch option data. Simulates premium price using index movement and a 0.5 Delta. Very fast."
        )

        bt_date_col1, bt_date_col2 = st.columns(2)
        with bt_date_col1:
            start_date = st.date_input("Start Date", datetime(2022, 11, 1))
        with bt_date_col2:
            end_date = st.date_input("End Date", datetime.now())
        
        st.markdown("#### 🛡️ Risk & Sizing (Defaults from strategy)")
        strategy_params = {} 
        strategy_params['initial_capital'] = st.number_input("Starting Capital (₹)", value=20000, min_value=10000, key="bt_init_cap")
        
        bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)
        with bt_col1:
            strategy_params['max_daily_loss'] = st.number_input("Max Daily Loss (₹)", value=bt_strategy_params_default.get('max_daily_loss', 2000), min_value=100, step=100, key="bt_max_loss")
        with bt_col2:
            strategy_params['max_trades_per_day'] = st.number_input("Max Trades Per Day", value=bt_strategy_params_default.get('max_trades_per_day', 10), min_value=1, step=1, key="bt_max_trades")
        with bt_col3:
            strategy_params['trade_start_time'] = st.time_input("Trade Start Time", value=bt_strategy_params_default.get('trade_start_time', dt_time(9, 30)), key="bt_start_time")
        with bt_col4:
            strategy_params['trade_end_time'] = st.time_input("Trade End Time", value=bt_strategy_params_default.get('trade_end_time', dt_time(15, 0)), key="bt_end_time")
        
        rcol1, rcol2, rcol3 = st.columns(3)
        with rcol1: strategy_params['lot_size'] = st.number_input("Lot Size", value=bt_strategy_params_default.get('lot_size', 35), min_value=1, key="bt_lot_size")
        with rcol2: strategy_params['min_investment'] = st.number_input("Min. Invest (₹)", value=bt_strategy_params_default.get('min_investment', 10000), min_value=10, key="bt_min_invest")
        
        with rcol3:
            if "Simulated" in backtest_mode:
                strategy_params['simulated_premium_pct'] = st.number_input("Sim. Premium (%)", value=bt_strategy_params_default.get('simulated_premium_pct', 0.8)*100, min_value=0.1, max_value=5.0, step=0.1, format="%.1f", key="bt_sim_prem") / 100.0
                strategy_params['simulated_delta'] = st.number_input("Sim. Delta", value=0.5, min_value=0.1, max_value=1.0, step=0.1, format="%.1f", key="bt_sim_delta")
            else:
                strategy_params['simulated_premium_pct'] = bt_strategy_params_default.get('simulated_premium_pct', 0.008)
                strategy_params['simulated_delta'] = 0.5

        sl_method_choice = st.selectbox("Stop-Loss Method", ["Invested Value (%)", "ATR"], index=1, key="bt_sl_mode")
        strategy_params['sl_mode'] = sl_method_choice
        
        if sl_method_choice == "Invested Value (%)":
            st.info("SL based on % of calculated Invested Value | TP = SL Amount x Multiplier")
            iv_col1, iv_col2 = st.columns(2)
            with iv_col1: 
                sl_pct = st.number_input("SL (% of Invested Value)", value=bt_strategy_params_default.get('invested_value_sl_pct', 5.0), min_value=0.5, step=0.5, key="bt_sl_pct")
                strategy_params['invested_value_sl_pct'] = sl_pct
            with iv_col2: 
                tp_mult = st.number_input("TP (Multiplier of SL Amount)", value=bt_strategy_params_default.get('tp_sl_ratio', 2.0), min_value=1.0, step=0.5, key="bt_tp_mult")
                strategy_params['tp_sl_ratio'] = tp_mult
        elif sl_method_choice == "ATR":
            if "Simulated" in backtest_mode:
                st.info("Using dynamic ATR (from Index) x Multiplier to set SL/TP levels (on Index).")
            else:
                st.info("Using dynamic ATR (from Index) to set SL/TP levels (on Option Premium via 0.5 Delta).")
            atr_col1, atr_col2, atr_col3 = st.columns(3)
            with atr_col1: 
                strategy_params['atr_period'] = st.number_input("ATR Period", value=bt_strategy_params_default.get('atr_period', 14), min_value=1, key="bt_atr_period")
            with atr_col2: 
                strategy_params['atr_tp_multiplier'] = st.number_input("ATR TP Multiplier", value=bt_strategy_params_default.get('atr_tp_multiplier', 2.0), min_value=0.1, step=0.1, format="%.1f", key="bt_atr_tp")
            with atr_col3: 
                strategy_params['atr_sl_multiplier'] = st.number_input("ATR SL Multiplier", value=bt_strategy_params_default.get('atr_sl_multiplier', 1.0), min_value=0.1, step=0.1, format="%.1f", key="bt_atr_sl")
        
        # --- NEW: Dynamic Risk Management ---
        strategy_params['use_dynamic_risk'] = st.toggle("Enable Dynamic Risk Management (ADX-based TP)", value=True, help="Adjusts TP Multiplier based on ADX trend strength.")
        
        with st.expander("Strategy-Specific Parameters (MTA)"):
            em_col1, em_col2 = st.columns(2)
            with em_col1: strategy_params['ema_short'] = st.number_input("EMA Short", value=bt_strategy_params_default.get('ema_short', 9), min_value=1, key="bt_ema_s")
            with em_col2: strategy_params['ema_long'] = st.number_input("EMA Long", value=bt_strategy_params_default.get('ema_long', 15), min_value=1, key="bt_ema_l")
        
        # --- NEW: UI for ADX/RSI filters in single backtest ---
        with st.expander("Strategy Filters (ADX & RSI)"):
            fcol1, fcol2, fcol3 = st.columns(3)
            with fcol1:
                strategy_params['use_adx_filter'] = st.toggle("Use ADX Filter", value=bt_strategy_params_default.get('use_adx_filter', True), key="bt_adx_toggle")
                strategy_params['adx_period'] = st.number_input("ADX Period", min_value=1, value=bt_strategy_params_default.get('adx_period', 14), step=1, key="bt_adx_period")
                strategy_params['adx_threshold'] = st.number_input("ADX Threshold", min_value=0, value=bt_strategy_params_default.get('adx_threshold', 20), step=1, key="bt_adx_thresh")
            with fcol2:
                strategy_params['use_rsi_filter'] = st.toggle("Use RSI Filter", value=bt_strategy_params_default.get('use_rsi_filter', True), key="bt_rsi_toggle")
                strategy_params['rsi_period'] = st.number_input("RSI Period", min_value=1, value=bt_strategy_params_default.get('rsi_period', 14), step=1, key="bt_rsi_period")
            with fcol3:
                strategy_params['rsi_overbought'] = st.number_input("RSI Overbought", min_value=50, max_value=100, value=bt_strategy_params_default.get('rsi_overbought', 70), step=1, key="bt_rsi_ob")
                strategy_params['rsi_oversold'] = st.number_input("RSI Oversold", min_value=0, max_value=50, value=bt_strategy_params_default.get('rsi_oversold', 30), step=1, key="bt_rsi_os")
            
            # --- NEW: AI Trend Filter Checkbox ---
            ai_filter_disabled = True
            if 'ai_predictor' in st.session_state and st.session_state.ai_predictor is not None and st.session_state.ai_predictor.trend_model is not None:
                ai_filter_disabled = False
            
            use_ai_trend_filter = st.checkbox("Use AI Trend Filter (1H)", value=False, disabled=ai_filter_disabled, help="Uses the trained 1H Trend Model to filter signals. Train it in the AI Prediction tab first.")
            if use_ai_trend_filter and ai_filter_disabled:
                st.caption("⚠️ Train Trend Model in AI Tab first.")
                
            # --- NEW: Skip Last Week of Expiry Checkbox ---
            strategy_params['skip_last_week_expiry'] = st.checkbox("Skip Expiry Volatility", value=bt_strategy_params_default.get('skip_last_week_expiry', False), help="Skips high volatility periods before expiry:\n- Monthly Expiry: Skips last 7 days.\n- Weekly Expiry: Skips last 2 days (Tue & Wed).")
            
            # --- NEW: Candle Size Filter UI ---
            st.markdown("---")
            st.markdown("**Candle Size Filter**")
            cs_col1, cs_col2, cs_col3 = st.columns(3)
            with cs_col1:
                strategy_params['use_candle_size_filter'] = st.toggle("Use Candle Size Filter", value=bt_strategy_params_default.get('use_candle_size_filter', False), key="bt_cs_toggle", help="Only trade if signal candle is larger than average.")
            with cs_col2:
                strategy_params['candle_size_period'] = st.number_input("Avg Period", min_value=5, value=bt_strategy_params_default.get('candle_size_period', 20), step=1, key="bt_cs_period")
            with cs_col3:
                strategy_params['candle_size_factor'] = st.number_input("Size Factor", min_value=0.5, value=bt_strategy_params_default.get('candle_size_factor', 1.0), step=0.1, format="%.1f", key="bt_cs_factor", help="Multiplier for average size. 1.0 = Average, 1.5 = 50% larger than average.")
        
        if st.button("🚀 RUN INTRADAY BACKTEST", use_container_width=True, type="primary"):
            if not tester:
                st.error("StrategyTester not initialized. Check Fyers credentials in Settings.")
            elif "Real Option" in backtest_mode and (not fyers_manager or not fyers_manager.is_authenticated()):
                st.error("Fyers API is not authenticated. Please go to the 'Settings' tab to generate a token.")
            else:
                st.session_state.backtest_running = True 
                st.session_state.backtest_result = None 
                try:
                    spinner_msg = f"Fetching Fyers 5m data for {selected_index} from {start_date} to {end_date}..."
                    if "Real Option" in backtest_mode:
                        spinner_msg = f"Running REAL OPTION backtest... This may take several minutes as it fetches option data for *each trade*."
                    else:
                        spinner_msg = f"Running SIMULATED backtest... This should be very fast."

                    with st.spinner(spinner_msg):
                        tester.engine.initial_capital = strategy_params['initial_capital']
                        
                        # --- NEW: Set AI Trend Predictor on Strategy ---
                        strategy = tester.engine.strategies[bt_strategy_key]
                        if use_ai_trend_filter:
                            strategy.set_trend_predictor(st.session_state.ai_predictor)
                        else:
                            strategy.set_trend_predictor(None)
                        
                        result = tester.engine.run_backtest(
                            strategy_name=bt_strategy_key, 
                            symbol=selected_index, 
                            start_date=start_date, 
                            end_date=end_date, 
                            interval=selected_interval,
                            silent=False,
                            backtest_mode=backtest_mode, 
                            **strategy_params
                        )
                        st.session_state.backtest_result = result
                except Exception as e:
                    st.error(f"❌ Backtest failed: {e}")
                    import traceback
                    st.exception(traceback.format_exc())
                    st.session_state.backtest_result = None 
                finally:
                    st.session_state.backtest_running = False 
                    st.rerun() 

        if 'backtest_result' in st.session_state and st.session_state.backtest_result:
            result = st.session_state.backtest_result
            
            # --- NEW: Clear Data Button ---
            c_col1, c_col2 = st.columns([3, 1])
            with c_col1:
                st.markdown("---"); st.subheader(f"📊 BACKTEST RESULTS ({result.parameters.get('backtest_mode', 'N/A')})")
            with c_col2:
                st.write("") # Spacer
                st.write("") 
                if st.button("🗑️ Clear Results & Free Memory", type="primary", use_container_width=True):
                    st.session_state.backtest_result = None
                    import gc
                    gc.collect()
                    st.rerun()

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total P&L", f"₹{result.total_pnl:,.0f}"); st.metric("Win Rate", f"{result.win_rate:.1f}%")
            with col2: st.metric("Total Trades", result.total_trades); st.metric("Profit Factor", f"{result.profit_factor:.2f}")
            with col3: st.metric("Max Drawdown", f"{result.max_drawdown:.1f}%"); st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
            with col4: st.metric("Best Trade", f"₹{result.best_trade:,.0f}"); st.metric("Worst Trade", f"₹{result.worst_trade:,.0f}")
            st.markdown("#### 📈 Portfolio Growth")
            if result.equity_curve is not None and not result.equity_curve.empty:
                # --- NEW: Downsample Chart Data ---
                chart_data = result.equity_curve['equity']
                if len(chart_data) > 5000:
                    st.caption(f"⚠️ Chart downsampled from {len(chart_data)} to 5000 points for performance.")
                    chart_data = chart_data.iloc[::len(chart_data)//5000]
                st.line_chart(chart_data) 
            else: st.info("No equity data to plot.")
            if result.trade_details:
                st.markdown("#### 📋 Full Trade Log")
                trades_df = pd.DataFrame(result.trade_details)
                trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'], errors='coerce').dt.strftime('%m/%d %H:%M')
                trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'], errors='coerce').dt.strftime('%m/%d %H:%M')
                trades_df['invested_amount'] = trades_df['invested_amount'].apply(lambda x: f"₹{x:,.0f}")
                trades_df['pnl'] = trades_df['pnl'].apply(lambda x: f"₹{x:,.2f}")
                
                if "Simulated" in result.parameters.get('backtest_mode', ''):
                    display_columns = ['entry_time', 'simulated_option', 'quantity', 'invested_amount', 'entry_price', 'exit_time', 'exit_price', 'pnl', 'exit_reason', 'entry_index_price', 'exit_index_price']
                else:
                    display_columns = ['entry_time', 'simulated_option', 'quantity', 'invested_amount', 'entry_price', 'exit_time', 'exit_price', 'pnl', 'exit_reason']
                
                display_columns = [col for col in display_columns if col in trades_df.columns]
                
                # --- NEW: Limit Table Rows ---
                if len(trades_df) > 100:
                    st.warning(f"⚠️ Showing last 100 trades out of {len(trades_df)} total trades to improve performance.")
                    st.dataframe(trades_df[display_columns].tail(100), width='stretch', height=400)
                else:
                    st.dataframe(trades_df[display_columns], width='stretch', height=400)
            else: st.info("No trades were executed during this backtest period.")
