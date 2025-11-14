# Modified: src/ui/streamlit_app.py
# - Added 'optimizer_running' to session_state
# - Auto-refresh in tab1 is now blocked by this flag.
# - Optimizer button in tab3 now sets/unsets this flag using try...finally.

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
except ImportError as e:
    st.error(f"CRITICAL IMPORT ERROR: {e}")
    st.error(f"Failed to load modules. Is 'src' directory correctly added to path? Path being added: {src_dir}")
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
# Initialize Angel Client
# ---------------------------
@st.cache_resource
def init_angel_client(index_name: str):
    # ... (no change) ...
    try:
        client = AngelClient(paper=True, index_name=index_name)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Angel Client: {e}")
        return None

# ---------------------------
# Initialize StrategyTester
# ---------------------------
@st.cache_resource
def init_strategy_tester():
    try:
        return StrategyTester()
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

angel = init_angel_client(index_name=selected_index)
tester = init_strategy_tester()

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

# --- NEW: Initialize session state for optimizer ---
if 'optimizer_running' not in st.session_state:
    st.session_state.optimizer_running = False
# --- END NEW ---

tab1, tab2, tab3 = st.tabs(["📈 Live Trading", "🔬 Single Backtest", "🚀 Optimizer"])

with tab1:
    # ---------------------------
    # Bot Status Dashboard
    # ---------------------------
    # ... (no change in this section) ...
    st.subheader("🤖 Bot Status & Rules")
    if angel:
        st.info(f"Strategy: **{strategy_name_map[active_strategy_key]}**")
        default_params = angel.strategies[active_strategy_key].parameters
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
        angel.set_trading_parameters(
            max_daily_loss=max_loss_input,
            max_trades=max_trades_input,
            start_time=start_time_input,
            end_time=end_time_input
        )
        daily_pnl = angel.daily_pnl 
        skip_day = angel.skip_today
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            st.metric("Today's Realized P&L", f"₹{daily_pnl:,.2f}")
        with scol2:
            st.metric("Today's Trades", f"{angel.today_trades_count} / {max_trades_input}")
        with scol3:
            if not is_market_open:
                st.info("MARKET CLOSED")
            elif daily_pnl <= -abs(max_loss_input):
                st.error(f"STOPPED: Max loss hit.")
            elif angel.today_trades_count >= max_trades_input:
                st.error(f"STOPPED: Max trades hit.")
            elif skip_day:
                st.warning("SKIPPED: Lot cost < ₹10k.")
            elif len(angel.positions_map) > 0:
                st.success("POSITION OPEN")
            elif not (start_time_input <= now_ist.time() <= end_time_input):
                st.info("WAITING (Outside trade window)")
            else:
                st.success(f"MONITORING ({strategy_name_map[active_strategy_key]})")
    # ---------------------------
    # Market Data Section
    # ---------------------------
    # ... (no change in this section) ...
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
    # ... (no change in this section) ...
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
    # ... (no change in this section) ...
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
    # ... (no change in this section) ...
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
            
    # --- MODIFIED: Auto-refresh is now CONDITIONAL ---
    if not st.session_state.optimizer_running:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=UI_REFRESH_SECONDS * 1000, limit=None, key="ui_refresh")
        except ImportError:
            st.sidebar.warning("Auto-refresh not installed.\n`pip install streamlit-autorefresh`")
            if st.sidebar.button("🔄 Refresh Dashboard"):
                st.rerun()
    # --- END OF MOVE ---


with tab2:
    # ---------------------------
    # Backtesting Section
    # ---------------------------
    # ... (no change in this tab) ...
    st.subheader(f"🧪 Backtest Engine (Index: {selected_index})") 
    if not tester:
        st.error("StrategyTester failed to initialize. Check logs.")
    else:
        bt_strategy_key = "mta_ema_crossover"
        bt_strategy_params_default = tester.get_strategy_parameters(bt_strategy_key)
        st.info(tester.engine.strategies[bt_strategy_key].description)
        backtest_interval = "5m"; st.info(f"Using **{backtest_interval}** data interval for signals (Max 60 days).")
        period_options = ["1d", "5d", "1mo", "60d"]; default_index = 3 
        backtest_period = st.selectbox("Test Period (Max 60d)", period_options, index=default_index, key="backtest_period")
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
        with rcol3: strategy_params['simulated_premium_pct'] = st.number_input("Sim. Premium (%)", value=bt_strategy_params_default.get('simulated_premium_pct', 0.008)*100, min_value=0.1, max_value=5.0, step=0.1, format="%.1f", key="bt_sim_prem") / 100.0 
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
            st.info("Using dynamic ATR-based Take Profit and Stop Loss.")
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
        if st.button("🚀 RUN INTRADAY BACKTEST", use_container_width=True, type="primary"):
            with st.spinner(f"Fetching {backtest_period} of real {backtest_interval} data for {selected_index}..."):
                try:
                    tester.engine.initial_capital = strategy_params['initial_capital']
                    result = tester.engine.run_backtest(
                        strategy_name=bt_strategy_key, 
                        symbol=selected_index, 
                        period=backtest_period, 
                        interval=backtest_interval, 
                        silent=False,
                        **strategy_params
                    )
                    st.session_state.backtest_result = result
                    st.success(f"✅ Backtest completed! {result.total_trades} trades analyzed.")
                except Exception as e:
                    st.error(f"❌ Backtest failed: {e}"); st.exception(e)
        if 'backtest_result' in st.session_state:
            result = st.session_state.backtest_result
            st.markdown("---"); st.subheader("📊 BACKTEST RESULTS")
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total P&L", f"₹{result.total_pnl:,.0f}"); st.metric("Win Rate", f"₹{result.win_rate:.1f}%")
            with col2: st.metric("Total Trades", result.total_trades); st.metric("Profit Factor", f"₹{result.profit_factor:.2f}")
            with col3: st.metric("Max Drawdown", f"₹{result.max_drawdown:.1f}%"); st.metric("Sharpe Ratio", f"₹{result.sharpe_ratio:.2f}")
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
                display_columns = ['entry_time', 'simulated_option', 'quantity', 'invested_amount', 'entry_price', 'exit_time', 'exit_price', 'pnl', 'exit_reason']
                st.dataframe(trades_df[display_columns], width='stretch', height=400)
            else: st.info("No trades were executed during this backtest period.")


with tab3:
    # ---------------------------
    # Optimizer Section
    # ---------------------------
    # ... (no change in parameter space) ...
    st.subheader("🚀 Strategy Parameter Optimizer")
    st.markdown(f"This tool will run many backtests with random parameters for the **MTA Crossover** strategy on **{selected_index}** to find profitable combinations.")
    st.warning(f"""
    **Target Metrics:**
    - **Sharpe Ratio:** $\geq 1.0$
    - **Win Rate:** $> 50\%$
    - **Total Trades:** $> 10$
    - **Max Drawdown:** $< 10\%$
    """)
    param_space = {
        'ema_short': (5, 15),
        'ema_long': (16, 40),
        'atr_period': (10, 30),
        'atr_tp_multiplier': (1.5, 5.0),
        'atr_sl_multiplier': (0.5, 2.0),
        'max_trades_per_day': (1, 10),
        'trade_start_time': (dt_time(9, 16), dt_time(11, 0)),
        'trade_end_time': (dt_time(13, 0), dt_time(15, 15)),
    }
    def random_time(start, end):
        start_ts = int(start.hour * 60 + start.minute)
        end_ts = int(end.hour * 60 + end.minute)
        rand_ts = random.randint(start_ts, end_ts)
        return dt_time(rand_ts // 60, rand_ts % 60)
    opt_col1, opt_col2 = st.columns(2)
    with opt_col1:
        num_iterations = st.number_input("Number of Iterations", min_value=10, max_value=1000, value=200, step=10)
    with opt_col2:
        opt_period = st.selectbox("Optimization Period", ["1mo", "60d"], index=1, key="opt_period")

    if 'optimizer_results' not in st.session_state:
        st.session_state.optimizer_results = []

    # --- MODIFIED: This is the full fix ---
    if st.button(f"🚀 RUN OPTIMIZER ({num_iterations} Iterations)", use_container_width=True, type="primary"):
        if not tester:
            st.error("Tester not initialized. Cannot run optimization.")
        else:
            # 1. SET FLAG TO STOP AUTOREFRESH
            st.session_state.optimizer_running = True
            
            log_messages = []
            progress_bar = st.progress(0, text="Optimizer starting...")
            status_text = st.empty()
            
            try:
                # 2. FETCH DATA ONCE
                status_text.text(f"Fetching {opt_period} data for {selected_index}...")
                data = tester.engine.data_manager.get_historical_data(
                    selected_index, opt_period, "5m", is_backtest_log=False
                )
                if data is None or data.empty:
                    raise Exception("No data returned for optimizer.")
                
                status_text.text(f"Data fetched ({len(data)} candles). Starting {num_iterations} iterations...")
                st.session_state.optimizer_results = [] # Clear previous results
                
                # 3. RUN LOOP (NOW SYNC AND WITHOUT NETWORK CALLS)
                for i in range(num_iterations):
                    try:
                        rand_params = {
                            'ema_short': random.randint(param_space['ema_short'][0], param_space['ema_short'][1]),
                            'ema_long': random.randint(param_space['ema_long'][0], param_space['ema_long'][1]),
                            'atr_period': random.randint(param_space['atr_period'][0], param_space['atr_period'][1]),
                            'atr_tp_multiplier': round(random.uniform(param_space['atr_tp_multiplier'][0], param_space['atr_tp_multiplier'][1]), 2),
                            'atr_sl_multiplier': round(random.uniform(param_space['atr_sl_multiplier'][0], param_space['atr_sl_multiplier'][1]), 2),
                            'max_trades_per_day': random.randint(param_space['max_trades_per_day'][0], param_space['max_trades_per_day'][1]),
                            'trade_start_time': random_time(param_space['trade_start_time'][0], param_space['trade_start_time'][1]),
                            'trade_end_time': random_time(param_space['trade_end_time'][0], param_space['trade_end_time'][1]),
                            'sl_mode': 'ATR', 
                            'initial_capital': 20000,
                        }
                        if rand_params['ema_short'] >= rand_params['ema_long']:
                            rand_params['ema_long'] = rand_params['ema_short'] + 1
                        
                        # Pass the pre-fetched 'data'
                        result = tester.engine.run_backtest(
                            strategy_name=active_strategy_key,
                            symbol=selected_index,
                            period=opt_period,
                            interval="5m",
                            silent=True, 
                            data=data.copy(), # Pass a copy
                            **rand_params
                        )
                        
                        is_good = (
                            result.sharpe_ratio >= 0.5 and
                            result.win_rate > 40 and
                            result.total_trades > 5 and
                            result.max_drawdown < 50
                        )
                        
                        if is_good:
                            log_messages.append(f"✅ Found profitable result at iteration {i+1}!")
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
                            })
                        # Optional: Log all results if you want to see them
                        # else:
                        #    log_messages.append(f"Iteration {i+1}: Sharpe {result.sharpe_ratio:.2f}, WR {result.win_rate:.1f}%, Trades {result.total_trades}, DD {result.max_drawdown:.1f}%")
                    
                    except Exception as e:
                        log_messages.append(f"❌ Iteration {i+1} failed: {e}")
                    
                    progress_bar.progress((i + 1) / num_iterations, text=f"Optimizer running... {i+1}/{num_iterations}")
                
                progress_bar.progress(1.0, text="Optimization complete!")
                status_text.empty()
                st.text_area("Optimization Log", value="\n".join(log_messages), height=300)

            # 4. ALWAYS unset the flag, even if the loop fails
            finally:
                st.session_state.optimizer_running = False
                st.rerun() # Force a rerun to update the UI and re-enable refresh
    # --- END OF FIX ---

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