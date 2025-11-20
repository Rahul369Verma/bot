# Modified: src/ui/streamlit_app.py
# - Tab 2: Added new expander for ADX/RSI filter inputs.
# - Tab 3: Added new ADX/RSI params to 'param_space' for optimization.
# - Tab 3: Optimizer loop now randomizes these new params.
# - Tab 3: Optimizer results table now shows the new params.

import os
import sys
import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
import threading
import random 

# --- (Path fix logic... no change) ---
current_file_path = os.path.abspath(__file__)
ui_dir = os.path.dirname(current_file_path)
src_dir = os.path.dirname(ui_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

try:
    from fetcher.angel_client import AngelClient 
    from backtest.backtest import StrategyTester 
    from fetcher.fyers_data import FyersDataManager
except ImportError as e:
    st.error(f"CRITICAL IMPORT ERROR: {e}")
    st.error(f"Failed to load modules. Is 'src' directory correctly added to path? Path being added: {src_dir}")
    st.error("Have you run 'pip install -r requirements.txt --upgrade'?")
    st.stop()

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()
BOT_HEARTBEAT_SECONDS = 30
UI_REFRESH_SECONDS = 10     
IST = ZoneInfo('Asia/Kolkata') 

# ---------------------------
# The Bot's "Heartbeat" Loop
# ---------------------------
def bot_loop(client: AngelClient):
    # ... (no change) ...
    print("✅ Bot background thread started. Waiting for the next 30-second mark to align...")
    while True:
        try:
            current_time = time.time()
            seconds_to_wait = BOT_HEARTBEAT_SECONDS - (current_time % BOT_HEARTBEAT_SECONDS)
            time.sleep(seconds_to_wait)
            now_ist = datetime.now(IST)
            is_market_open = (now_ist.weekday() < 5) and (dt_time(9, 15) <= now_ist.time() <= dt_time(15, 30))
            if is_market_open:
                client.check_new_day()
                client.check_and_close_positions()
                signals = client.generate_continuous_signals()
        except Exception as e:
            print(f"❌ CRITICAL ERROR in bot_loop: {e}")
            time.sleep(5) 

# ---------------------------
# Initialize Core Components
# ---------------------------
@st.cache_resource
def init_fyers_manager():
    # ... (no change) ...
    try:
        return FyersDataManager()
    except ValueError as e:
        st.error(f"Failed to init Fyers Manager: {e}")
        return None

@st.cache_resource
def init_angel_client(index_name: str):
    # ... (no change) ...
    try:
        client = AngelClient(paper=True, index_name=index_name)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Angel Client: {e}")
        return None

@st.cache_resource
def init_strategy_tester(_fyers_manager):
    # ... (no change) ...
    if _fyers_manager is None:
        return None
    try:
        return StrategyTester(fyers_manager=_fyers_manager)
    except Exception as e:
         st.error(f"Failed to initialize StrategyTester: {e}")
         return None

# ---------------------------
# Streamlit Layout (The Dashboard)
# ---------------------------
st.set_page_config(page_title="Index Trading Bot", layout="wide")

st.sidebar.title("⚙️ Bot Controls")
selected_index = st.sidebar.selectbox(
    "SELECT INDEX", 
    ["BANKNIFTY", "NIFTY 50"],
    key="selected_index"
)

active_strategy_key = "mta_ema_crossover"
strategy_name_map = {
    'mta_ema_crossover': "MTA Crossover (EMA)"
}

fyers_manager = init_fyers_manager()
angel = init_angel_client(index_name=selected_index)
tester = init_strategy_tester(fyers_manager)

# ---------------------------
# Start the Bot Thread (Runs Once)
# ---------------------------
with threading.Lock():
    # ... (no change) ...
    if 'bot_thread_running' not in st.session_state:
        if angel:
            print("--- Starting bot background thread... ---")
            t = threading.Thread(target=bot_loop, args=(angel,), daemon=True)
            t.start()
            st.session_state['bot_thread_running'] = True 
            print("✅ Bot background thread is now running.")
        else:
            st.error("Cannot start bot thread: Angel Client failed to initialize.")

# ---------------------------
# Helper functions
# ---------------------------
# ... (no change) ...
def safe_dataframe_formatting(df, columns_format):
    df_formatted = df.copy()
    for col, format_func in columns_format.items():
        if col in df_formatted.columns:
            if pd.api.types.is_numeric_dtype(df_formatted[col]):
                 try: df_formatted[col] = df_formatted[col].apply(format_func)
                 except Exception: pass
    return df_formatted
def format_volume(volume):
    if pd.isna(volume): return "N_A"
    volume = float(volume)
    if volume >= 1000000: return f"{volume/1000000:.1f}M"
    elif volume >= 1000: return f"{volume/1000:.1f}K"
    else: return f"{volume:.0f}"
def highlight_atm(row, atm_strike):
    is_atm = row['strike'] == atm_strike
    style = 'background-color: #FDE7B3; color: black;'
    return [style if is_atm else '' for _ in row]

st.title(f"🎯 {selected_index} Live Trading Bot {'(PAPER MODE)' if angel.paper else '(REAL MONEY MODE)'}")

if angel.paper:
    st.success("Bot is in PAPER TRADING mode. No real money will be used.")
else:
    st.error("WARNING: Bot is in REAL MONEY mode. Real trades will be placed.")

now_ist = datetime.now(IST)
is_market_open = (now_ist.weekday() < 5) and (dt_time(9, 15) <= now_ist.time() <= dt_time(15, 30))

if 'optimizer_running' not in st.session_state:
    st.session_state.optimizer_running = False
if 'backtest_running' not in st.session_state:
    st.session_state.backtest_running = False

if 'auth_code' in st.query_params and fyers_manager:
    auth_code = st.query_params['auth_code']
    with st.spinner("Generating Fyers Access Token..."):
        if fyers_manager.generate_and_save_token(auth_code):
            st.success("✅ Fyers Access Token generated and saved successfully! You can now run backtests.")
            st.query_params.clear()
        else:
            st.error("❌ Failed to generate Fyers Access Token. Check your App ID/Secret.")

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📈 Live Trading", "🔬 Single Backtest", "🚀 Optimizer", "🔑 Settings"])

with tab1:
    # ---------------------------
    # Bot Status Dashboard
    # ---------------------------
    # ... (no change) ...
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
    
    # ---------------------------
    # Market Data Section
    # ---------------------------
    # ... (no change) ...
    st.subheader(f"📊 Live Market Data ({selected_index})")
    if not is_market_open:
        st.warning("Market is CLOSED. Live data (LTP, OI, IV) will be unavailable or show last 'close' price.")
    spot_price = 0.0 
    if angel:
        try:
            spot_price = angel.get_index_ltp()
            ema_data = angel.market_data.calculate_emas(angel.get_5m_historical_data())
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1: st.metric(f"{selected_index} Spot", f"₹{spot_price:,.2f}")
            with col2: st.metric("5m EMA 9", f"₹{ema_data['ema_9']:,.2f}")
            with col3: st.metric("5m EMA 15", f"₹{ema_data['ema_15']:,.2f}")
            with col4:
                ema_diff = ema_data['ema_9'] - ema_data['ema_15']; trend = "BULLISH" if ema_diff > 0 else "BEARISH"
                st.metric("5m Trend", trend, delta=f"₹{ema_diff:,.2f}")
            with col5: st.metric("Last Update (IST)", now_ist.strftime("%H:%M:%S"))
        except Exception as e:
            st.error(f"❌ Failed to load market data: {e}")
            if not is_market_open: st.info("This is expected as the market is closed.")
    
    # ---------------------------
    # Live Positions & P&L
    # ---------------------------
    # ... (no change) ...
    st.subheader("💰 Live Portfolio (Paper)")
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
    # ... (no change) ...
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
    # ... (no change) ...
    st.subheader(f"📋 Real Option Chain ({selected_index})")
    if angel:
        try:
            all_expiry_dates = angel.get_expiry_dates(); display_expiries = all_expiry_dates 
            col1, col2 = st.columns([1, 3])
            with col1:
                if display_expiries: expiry = st.selectbox("Select Expiry", display_expiries, index=0); st.caption(f"Selected: {expiry}")
                else: st.error("No expiry dates available"); expiry = None
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
            
    # --- (Auto-refresh fix... no change) ---
    if not st.session_state.optimizer_running and not st.session_state.backtest_running:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=UI_REFRESH_SECONDS * 1000, limit=None, key="ui_refresh")
        except ImportError:
            st.sidebar.warning("Auto-refresh not installed.\n`pip install streamlit-autorefresh`")
            if st.sidebar.button("🔄 Refresh Dashboard"):
                st.rerun()


with tab2:
    # ---------------------------
    # Backtesting Section
    # ---------------------------
    # ... (no change in this tab) ...
    st.subheader(f"🧪 Backtest Engine (Index: {selected_index})") 

    if not tester:
        st.error("StrategyTester failed to initialize. Check Fyers credentials in Settings.")
    else:
        bt_strategy_key = "mta_ema_crossover"
        bt_strategy_params_default = tester.get_strategy_parameters(bt_strategy_key)
        st.info(tester.engine.strategies[bt_strategy_key].description)
        st.info("Using **5m** data interval from Fyers.")

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
            start_date = st.date_input("Start Date", datetime.now() - timedelta(days=365))
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
        with rcol2: strategy_params['min_investment'] = st.number_input("Min. Invest (₹)", value=bt_strategy_params_default.get('min_investment', 10000), min_value=1000, key="bt_min_invest")
        
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
                        
                        result = tester.engine.run_backtest(
                            strategy_name=bt_strategy_key, 
                            symbol=selected_index, 
                            start_date=start_date, 
                            end_date=end_date, 
                            interval="5",
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
            st.markdown("---"); st.subheader(f"📊 BACKTEST RESULTS ({result.parameters.get('backtest_mode', 'N/A')})")
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total P&L", f"₹{result.total_pnl:,.0f}"); st.metric("Win Rate", f"{result.win_rate:.1f}%")
            with col2: st.metric("Total Trades", result.total_trades); st.metric("Profit Factor", f"{result.profit_factor:.2f}")
            with col3: st.metric("Max Drawdown", f"{result.max_drawdown:.1f}%"); st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
            with col4: st.metric("Best Trade", f"₹{result.best_trade:,.0f}"); st.metric("Worst Trade", f"₹{result.worst_trade:,.0f}")
            st.markdown("#### 📈 Portfolio Growth")
            if result.equity_curve is not None and not result.equity_curve.empty:
                st.line_chart(result.equity_curve['equity']) 
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
                st.dataframe(trades_df[display_columns], width='stretch', height=400)
            else: st.info("No trades were executed during this backtest period.")


with tab3:
    # ---------------------------
    # Optimizer Section
    # ---------------------------
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
                status_text.text(f"Fetching Fyers data for {selected_index} from {opt_start_date} to {opt_end_date}...")
                data = tester.engine.data_manager.get_historical_index_data(
                    selected_index, opt_start_date, opt_end_date, "5", is_backtest_log=True
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
                            interval="5",
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
                st.rerun() 

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

with tab4:
    # ---------------------------
    # Settings Tab
    # ---------------------------
    # ... (no change) ...
    st.subheader("🔑 Fyers API Settings")
    if not fyers_manager:
        st.error("Fyers Manager failed to initialize. Check your .env file.")
        st.code("Create a .env file in the root directory with:\n\nFYERS_APP_ID=YOUR_APP_ID\nFYERS_SECRET_KEY=YOUR_SECRET_KEY\nFYERS_REDIRECT_URL=YOUR_NGROK_URL")
    else:
        st.info(f"**App ID:** `{fyers_manager.app_id[:4]}...{fyers_manager.app_id[-4:]}`")
        st.info(f"**Redirect URL:** `{fyers_manager.redirect_url}`")
        st.warning("Ensure your Redirect URL in the Fyers App Dashboard matches *exactly*.")
    
        if fyers_manager.is_authenticated():
            st.success("✅ Fyers API is authenticated and ready.")
            st.write(f"Your Access Token is saved in `fyers_token.json`")
        else:
            st.error("Fyers API is not authenticated.")
            try:
                login_url = fyers_manager.get_login_url()
                st.link_button("1. Click here to log in to Fyers", login_url, type="primary")
                st.write("2. After logging in, you will be redirected back here. The app will automatically generate and save your token.")
            except Exception as e:
                st.error(f"Could not generate login URL: {e}")