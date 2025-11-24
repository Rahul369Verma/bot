import streamlit as st
import pandas as pd
from datetime import datetime, time as dt_time
from ..utils import safe_dataframe_formatting, format_volume, highlight_atm

def render_live_dashboard(angel, selected_index, active_strategy_key, strategy_name_map, is_market_open, now_ist, ui_refresh_seconds):
    """Renders the Live Dashboard tab."""
    # ---------------------------
    # Bot Status Dashboard
    # ---------------------------
    st.subheader("🤖 Bot Status & Rules")
    if angel:
        st.info(f"Strategy: **{strategy_name_map[active_strategy_key]}**")
        
        # --- NEW: Get params from the *live* strategy instance ---
        live_strategy = angel.strategies.get(active_strategy_key)
        if live_strategy:
            default_params = live_strategy.parameters
        else:
            st.error(f"Active strategy '{active_strategy_key}' not found in AngelClient!")
            default_params = {}

        st_col1, st_col2, st_col3, st_col4 = st.columns(4)
        max_loss_input = st_col1.number_input(
            "Max Daily Loss (₹)", 
            value=default_params.get('max_daily_loss', 2000), 
            min_value=100, step=100,
            help="Bot will stop trading for the day if Today's Realized P&L hits this level.",
            key="live_max_loss"
        )
        max_trades_input = st_col2.number_input(
            "Max Trades Per Day",
            value=default_params.get('max_trades_per_day', 10),
            min_value=1, step=1,
            key="live_max_trades"
        )
        start_time_input = st_col3.time_input(
            "Trade Start Time",
            value=default_params.get('trade_start_time', dt_time(9, 30)),
            key="live_start_time"
        )
        end_time_input = st_col4.time_input(
            "Trade End Time",
            value=default_params.get('trade_end_time', dt_time(15, 0)),
            key="live_end_time"
        )
        
        # --- NEW: UI for live ADX/RSI filters ---
        with st.expander("Live Strategy Filter Controls"):
            fcol1, fcol2, fcol3 = st.columns(3)
            with fcol1:
                use_adx = st.toggle("Use ADX Filter", value=default_params.get('use_adx_filter', True), key="live_adx_toggle")
                adx_thresh = st.number_input("ADX Threshold", min_value=0, value=default_params.get('adx_threshold', 20), step=1, key="live_adx_thresh")
            with fcol2:
                use_rsi = st.toggle("Use RSI Filter", value=default_params.get('use_rsi_filter', True), key="live_rsi_toggle")
                rsi_ob = st.number_input("RSI Overbought", min_value=50, max_value=100, value=default_params.get('rsi_overbought', 70), step=1, key="live_rsi_ob")
            with fcol3:
                st.write("") # Spacer
                st.write("") # Spacer
                rsi_os = st.number_input("RSI Oversold", min_value=0, max_value=50, value=default_params.get('rsi_oversold', 30), step=1, key="live_rsi_os")
        
        # --- NEW: Update all params in AngelClient/Strategy ---
        if live_strategy:
            # Update live risk params
            angel.set_trading_parameters(
                max_daily_loss=max_loss_input,
                max_trades=max_trades_input,
                start_time=start_time_input,
                end_time=end_time_input
            )
            # Update live filter params
            live_strategy.parameters['use_adx_filter'] = use_adx
            live_strategy.parameters['adx_threshold'] = adx_thresh
            live_strategy.parameters['use_rsi_filter'] = use_rsi
            live_strategy.parameters['rsi_overbought'] = rsi_ob
            live_strategy.parameters['rsi_oversold'] = rsi_os
        
        daily_pnl = angel.daily_pnl 
        skip_today = angel.skip_today
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            st.metric("Today's Realized P&L", f"₹{daily_pnl:,.2f}")
        with scol2:
            st.metric("Today's Trades", f"{angel.today_trades_count} / {max_trades_input}")
        with scol3:
            if not is_market_open: st.info("MARKET CLOSED")
            elif daily_pnl <= -abs(max_loss_input): st.error(f"STOPPED: Max loss hit.")
            elif angel.today_trades_count >= max_trades_input: st.error(f"STOPPED: Max trades hit.")
            elif skip_today: st.warning("SKIPPED: Lot cost < ₹10k.")
            elif len(angel.positions_map) > 0: st.success("POSITION OPEN")
            elif not (start_time_input <= now_ist.time() <= end_time_input): st.info("WAITING (Outside trade window)")
            else: st.success(f"MONITORING ({strategy_name_map[active_strategy_key]})")
    
        # --- NEW: Detailed Strategy Logic Display ---
        with st.expander("🔍 Detailed Strategy Logic & Filters", expanded=False):
            if live_strategy:
                p = live_strategy.parameters
                
                # 1. Core Strategy
                st.markdown("#### 🧠 Core Strategy (MTA)")
                c1, c2, c3 = st.columns(3)
                c1.metric("EMA Short", p.get('ema_short', 9))
                c2.metric("EMA Long", p.get('ema_long', 15))
                c3.metric("Base Interval", "5m")
                
                st.markdown("---")
                
                # 2. Filters
                st.markdown("#### 🛡️ Active Filters")
                
                # ADX
                adx_col, rsi_col, candle_col = st.columns(3)
                with adx_col:
                    st.markdown("**ADX Filter**")
                    st.write(f"Status: {'✅ ON' if p.get('use_adx_filter') else '❌ OFF'}")
                    if p.get('use_adx_filter'):
                        st.write(f"Threshold: > {p.get('adx_threshold', 20)}")
                        st.write(f"Period: {p.get('adx_period', 14)}")
                
                # RSI
                with rsi_col:
                    st.markdown("**RSI Filter**")
                    st.write(f"Status: {'✅ ON' if p.get('use_rsi_filter') else '❌ OFF'}")
                    if p.get('use_rsi_filter'):
                        st.write(f"Overbought: > {p.get('rsi_overbought', 70)}")
                        st.write(f"Oversold: < {p.get('rsi_oversold', 30)}")
                        st.write(f"Period: {p.get('rsi_period', 14)}")

                # Candle Size
                with candle_col:
                    st.markdown("**Candle Size Filter**")
                    st.write(f"Status: {'✅ ON' if p.get('use_candle_size_filter') else '❌ OFF'}")
                    if p.get('use_candle_size_filter'):
                        st.write(f"Factor: {p.get('candle_size_factor', 1.0)}x Avg")
                        st.write(f"Avg Period: {p.get('candle_size_period', 20)}")
                
                st.markdown("---")
                
                # 3. Risk & Expiry
                st.markdown("#### ⚙️ Risk & Expiry Rules")
                r1, r2 = st.columns(2)
                with r1:
                    st.markdown("**Stop Loss & Target**")
                    if p.get('sl_mode') == 'ATR':
                        st.write(f"Mode: ATR Based")
                        st.write(f"SL: {p.get('atr_sl_multiplier')}x ATR")
                        st.write(f"TP: {p.get('atr_tp_multiplier')}x ATR")
                    else:
                        st.write(f"Mode: Fixed %")
                        st.write(f"SL: {p.get('invested_value_sl_pct')}%")
                        st.write(f"TP: {p.get('tp_sl_ratio')}x SL")
                
                with r2:
                    st.markdown("**Expiry Rules**")
                    skip_exp = p.get('skip_last_week_expiry', False)
                    st.write(f"Skip Last Week: {'✅ YES' if skip_exp else '❌ NO'}")
                    if skip_exp:
                        st.caption("Monthly: Skips last 7 days. Weekly: Skips last 2 days.")
    
    # ---------------------------
    # Market Data Section
    # ---------------------------
    st.subheader(f"📊 Live Market Data ({selected_index})")
    if not is_market_open:
        st.warning("Market is CLOSED. Live data (LTP, OI, IV) will be unavailable or show last 'close' price.")
    spot_price = 0.0 
    if angel:
        try:
            # Cache market data for 5 minutes (aligned with signal generation) to reduce API calls
            # Floor to 5-minute mark: 04:17 -> 04:15, 04:22 -> 04:20
            cache_minute = (now_ist.minute // 5) * 5
            cache_key = f"market_data_{selected_index}_{now_ist.strftime('%Y%m%d%H')}{cache_minute:02d}"
            
            if cache_key not in st.session_state:
                spot_price = angel.get_index_ltp()
                ema_data = angel.market_data.calculate_emas(angel.get_5m_historical_data())
                fetch_time = now_ist
                st.session_state[cache_key] = {'spot_price': spot_price, 'ema_data': ema_data, 'fetch_time': fetch_time}
            else:
                cached = st.session_state[cache_key]
                spot_price = cached['spot_price']
                ema_data = cached['ema_data']
                fetch_time = cached['fetch_time']
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1: st.metric(f"{selected_index} Spot", f"₹{spot_price:,.2f}")
            with col2: st.metric("5m EMA 9", f"₹{ema_data['ema_9']:,.2f}")
            with col3: st.metric("5m EMA 15", f"₹{ema_data['ema_15']:,.2f}")
            with col4:
                ema_diff = ema_data['ema_9'] - ema_data['ema_15']; trend = "BULLISH" if ema_diff > 0 else "BEARISH"
                st.metric("5m Trend", trend, delta=f"₹{ema_diff:,.2f}")
            with col5: st.metric("Last Update (IST)", fetch_time.strftime("%H:%M:%S"))
        except Exception as e:
            st.error(f"❌ Failed to load market data: {e}")
            if not is_market_open: st.info("This is expected as the market is closed.")
            
    # ---------------------------
    # Live Positions & P&L
    # ---------------------------
    # ---------------------------
    # Live Positions & P&L
    # ---------------------------
    portfolio_header = "💰 Live Portfolio (REAL)" if (angel and not angel.paper) else "💰 Live Portfolio (Paper)"
    st.subheader(portfolio_header)
    if angel:
        try:
            portfolio = angel.get_portfolio_value()
            positions = angel.get_positions()
            col1, col2, col3 = st.columns(3)
            with col1: st.metric("Total Investment", f"₹{portfolio['total_investment']:,.2f}")
            with col2: st.metric("Current Value", f"₹{portfolio['total_current_value']:,.2f}")
            with col3: st.metric("Unrealized P&L", f"₹{portfolio['total_unrealized_pnl']:,.2f}", delta=f"{portfolio['total_unrealized_pnl']:,.2f}")
            st.metric("Today's Realized P&L", f"₹{portfolio['daily_realized_pnl']:,.2f}")
            if st.button("🚨 CLOSE ALL OPEN POSITIONS 🚨", type="primary", use_container_width=True):
                if angel and len(angel.positions_map) > 0:
                    with st.spinner("Closing all positions..."):
                        close_results = angel.close_all_live_positions()
                        for res in close_results.get('results', []):
                            if res.get('status'):
                                pnl = res.get('trade_pnl', 0); color = "green" if pnl >= 0 else "red"
                                st.success(f"Closed {res['data']['tradingsymbol']} for P&L: ₹{pnl:,.2f}")
                            else: st.error(f"Failed to close position: {res.get('message')}")
                        st.info(f"Total P&L from closing: ₹{close_results.get('total_pnl', 0):,.2f}")
                else: st.info("No open positions to close.")
            if positions:
                st.write("**Current Open Positions**"); df_positions = pd.DataFrame(positions)
                st.dataframe(df_positions[['tradingsymbol', 'qty', 'avg_price', 'current_price', 'unrealized_pnl', 'sl', 'tp']], width='stretch')
            else: st.info("No open positions.")
            trade_history = angel.get_trade_history()
            if trade_history:
                st.write("**Today's Closed Trades**"); df_history = pd.DataFrame(trade_history)
                df_history['time'] = pd.to_datetime(df_history['timestamp'], unit='s').dt.strftime('%H:%M:%S')
                st.dataframe(df_history[['time', 'tradingsymbol', 'quantity', 'price', 'pnl']], width='stretch')
        except Exception as e: st.error(f"❌ Paper trading error: {e}")
    
    # ---------------------------
    # Manual Trade Testing Section
    # ---------------------------
    st.subheader("🛠️ Manual Trade Testing")
    st.write(f"Test the paper trading system by firing a fake signal for **{strategy_name_map[active_strategy_key]}**. This uses all bot rules.")
    mcol1, mcol2 = st.columns(2)
    with mcol1:
        if st.button("📈 Test FAKE BUY (CE) Signal"):
            if angel:
                with st.spinner("Attempting fake BUY..."):
                    result = angel.execute_manual_test_trade(signal_type='CE')
                    if result.get('status'): st.success(f"✅ {result.get('message')}")
                    else: st.error(f"❌ {result.get('message')}")
    with mcol2:
        if st.button("📉 Test FAKE SELL (PE) Signal"):
            if angel:
                with st.spinner("Attempting fake SELL..."):
                    result = angel.execute_manual_test_trade(signal_type='PE')
                    if result.get('status'): st.success(f"✅ {result.get('message')}")
                    else: st.error(f"❌ {result.get('message')}")
    
    # ---------------------------
    # Real Option Chain Section
    # ---------------------------
    st.subheader(f"📋 Real Option Chain ({selected_index})")
    if angel:
        try:
            all_expiry_dates = angel.get_expiry_dates()
            display_expiries = all_expiry_dates
            
            # Determine expiry type label for display
            if selected_index == "BANKNIFTY":
                expiry_type_label = "Weekly"
            else:  # NIFTY 50
                # Check if we have weekly expiries (gap ~7 days)
                if len(display_expiries) >= 2:
                    from datetime import datetime
                    try:
                        date1 = datetime.strptime(display_expiries[0], "%d-%b-%Y")
                        date2 = datetime.strptime(display_expiries[1], "%d-%b-%Y")
                        gap = (date2 - date1).days
                        expiry_type_label = "Weekly (Auto)" if gap <= 10 else "Monthly"
                    except:
                        expiry_type_label = "Auto"
                else:
                    expiry_type_label = "Auto"
            
            col1, col2 = st.columns([1, 3])
            with col1:
                if display_expiries:
                    expiry = st.selectbox("Select Expiry", display_expiries, index=0)
                    st.caption(f"Selected: {expiry} ({expiry_type_label})")
                else:
                    st.error("No expiry dates available")
                    expiry = None
            if expiry and spot_price > 0:
                atm_strike = int(round(spot_price / 100.0) * 100)
                option_chain = angel.get_option_chain(expiry=expiry)
                if option_chain:
                    st.success(f"✅ Loaded {len(option_chain)} options for {expiry} (Data is from last close)")
                    df_chain = pd.DataFrame(option_chain)
                    atm_options = df_chain[(df_chain['strike'] >= atm_strike - 300) & (df_chain['strike'] <= atm_strike + 300)].sort_values('strike')
                    ce_chain = atm_options[atm_options['type'] == 'CE']; pe_chain = atm_options[atm_options['type'] == 'PE']
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**📈 CALL Options (ATM: ₹{atm_strike})**"); 
                        if not ce_chain.empty:
                            display_ce = ce_chain[['tradingsymbol', 'strike', 'ltp', 'oi', 'volume', 'iv']].head(8)
                            formatting_opt = {'ltp': lambda x: f'₹{x:.2f}', 'oi': lambda x: f'{x:,.0f}', 'volume': lambda x: format_volume(x), 'iv': lambda x: f'{x:.1f}%' if x > 0 else 'N/A'}
                            display_ce = safe_dataframe_formatting(display_ce, formatting_opt)
                            display_ce_styled = display_ce.style.apply(highlight_atm, atm_strike=atm_strike, axis=1)
                            st.dataframe(display_ce_styled, width='stretch')
                        else: st.info("No CALL options available")
                    with col2:
                        st.write(f"**📉 PUT Options (ATM: ₹{atm_strike})**")
                        if not pe_chain.empty:
                            display_pe = pe_chain[['tradingsymbol', 'strike', 'ltp', 'oi', 'volume', 'iv']].head(8)
                            display_pe = safe_dataframe_formatting(display_pe, formatting_opt)
                            display_pe_styled = display_pe.style.apply(highlight_atm, atm_strike=atm_strike, axis=1)
                            st.dataframe(display_pe_styled, width='stretch')
                        else: st.info("No PUT options available")
                    total_oi_call = ce_chain['oi'].sum() if not ce_chain.empty else 0; total_oi_put = pe_chain['oi'].sum() if not pe_chain.empty else 0
                    pcr = total_oi_put / total_oi_call if total_oi_call > 0 else 0
                    st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}")
                else: st.error("❌ No option chain data available for selected expiry")
        except Exception as e:
            st.error(f"❌ Failed to load option chain: {e}")
            if not is_market_open: st.info("This is expected as the market is closed.")
            
    # --- (Auto-refresh fix) ---
    # Stop auto-refresh if:
    # 1. Optimizer is running
    # 2. Backtest is running
    # 3. Backtest results are being viewed (so user can analyze without reload)
    # 4. AI Training is running
    if not st.session_state.optimizer_running and not st.session_state.backtest_running and st.session_state.get('backtest_result') is None and not st.session_state.ai_training_running:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=ui_refresh_seconds * 1000, limit=None, key="ui_refresh")
        except ImportError:
            st.sidebar.warning("Auto-refresh not installed.\n`pip install streamlit-autorefresh`")
            if st.sidebar.button("🔄 Refresh Dashboard"):
                st.rerun()
