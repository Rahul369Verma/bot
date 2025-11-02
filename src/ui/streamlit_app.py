import os
import sys
import time
from datetime import datetime, timedelta, time # Import time
from zoneinfo import ZoneInfo # Import ZoneInfo
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
# --- NEW: Fix for ModuleNotFoundError: No module named 'src' ---
# Get the absolute path of the current file (streamlit_app.py)
current_file_path = os.path.abspath(__file__)
# Get the path to the 'ui' directory
ui_dir = os.path.dirname(current_file_path)
# Get the path to the 'src' directory (one level up)
src_dir = os.path.dirname(ui_dir)
# Get the path to the project root 'bot' (one level up from 'src')
project_root = os.path.dirname(src_dir)

# Add the project root to the Python path
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- END FIX ---
from src.fetcher.angel_client import AngelClient
from src.backtest.backtest import StrategyTester, CUSTOM_STRATEGY_TEMPLATE # No longer needed

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()
UNDERLYING = "BANKNIFTY"
# --- UPDATED ---
REFRESH_INTERVAL = 30  # seconds
IST = ZoneInfo('Asia/Kolkata') # Define IST Timezone

# ---------------------------
# Initialize Angel Client
# ---------------------------
@st.cache_resource
def init_angel_client():
    """Initialize Angel Client"""
    try:
        client = AngelClient(paper=True)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Angel Client: {e}")
        return None

angel = init_angel_client()

# ---------------------------
# Helper functions
# ---------------------------
def safe_dataframe_formatting(df, columns_format):
    df_formatted = df.copy()
    for col, format_func in columns_format.items():
        if col in df_formatted.columns:
            if pd.api.types.is_numeric_dtype(df_formatted[col]):
                 try: df_formatted[col] = df_formatted[col].apply(format_func)
                 except Exception: pass
    return df_formatted
def format_volume(volume):
    if pd.isna(volume): return "N/A"
    volume = float(volume)
    if volume >= 1000000: return f"{volume/1000000:.1f}M"
    elif volume >= 1000: return f"{volume/1000:.1f}K"
    else: return f"{volume:.0f}"
def highlight_atm(row, atm_strike):
    is_atm = row['strike'] == atm_strike
    style = 'background-color: #FDE7B3; color: black;'
    return [style if is_atm else '' for _ in row]

# ---------------------------
# Streamlit Layout
# ---------------------------
st.set_page_config(page_title="BankNifty Live Bot", layout="wide")
st.title(f"🎯 BankNifty Live Trading Bot {'(PAPER MODE)' if angel.paper else '(REAL MONEY MODE)'}")

if angel.paper:
    st.success("Bot is in PAPER TRADING mode. No real money will be used.")
else:
    st.error("WARNING: Bot is in REAL MONEY mode. Real trades will be placed.")

# ---------------------------
# Auto-refresh & Main Bot Loop
# ---------------------------
# Check market hours
now_ist = datetime.now(IST)
is_market_open = (now_ist.weekday() < 5) and (time(9, 15) <= now_ist.time() <= time(15, 30))

if angel:
    try:
        if is_market_open:
            # Only run trading logic if market is open
            angel.check_new_day()
            angel.check_and_close_positions()
            signals = angel.generate_continuous_signals()
        
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=REFRESH_INTERVAL * 1000, limit=None, key="refresh")
        
    except ImportError:
        if st.button("🔄 Manual Refresh Bot"):
            st.rerun()
    except Exception as e:
        # Don't show the full error, just the message
        st.error(f"Error in main bot loop: {e}")
else:
    st.error("Angel Client not initialized. Bot cannot run.")
    st.stop()


# ---------------------------
# Bot Status Dashboard
# ---------------------------
st.subheader("🤖 Bot Status & Rules")
if angel:
    daily_trend = angel.market_analyzer.daily_trend
    sl_count = angel.daily_sl_count
    skip_day = angel.skip_today

    scol1, scol2, scol3 = st.columns(3)
    with scol1:
        st.metric("Daily Trend", daily_trend)
    with scol2:
        st.metric("Stop Losses Hit Today", f"{sl_count} / 2")
    with scol3:
        if not is_market_open:
            st.info("MARKET CLOSED")
        elif sl_count >= 2:
            st.error("STOPPED: 2 SL hits.")
        elif skip_day:
            st.warning("SKIPPED: Lot cost < ₹10k.")
        elif len(angel.positions_map) > 0:
            st.success("POSITION OPEN")
        else:
            st.success("MONITORING...")

# ---------------------------
# Market Data Section
# ---------------------------
st.subheader("📊 Live Market Data")

if not is_market_open:
    st.warning("Market is CLOSED. Live data (LTP, OI, IV) will be unavailable or show last 'close' price.")

spot_price = 0.0 
if angel:
    try:
        spot_price = angel.get_index_ltp("BANKNIFTY")
        ema_data = angel.market_data.calculate_emas(angel.get_5m_historical_data())
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1: st.metric(f"{UNDERLYING} Spot", f"₹{spot_price:,.2f}")
        with col2: st.metric("5m EMA 9", f"₹{ema_data['ema_9']:,.2f}")
        with col3: st.metric("5m EMA 15", f"₹{ema_data['ema_15']:,.2f}")
        with col4:
            ema_diff = ema_data['ema_9'] - ema_data['ema_15']; trend = "BULLISH" if ema_diff > 0 else "BEARISH"
            st.metric("5m Trend", trend, delta=f"₹{ema_diff:,.2f}")
        with col5: st.metric("Last Update", datetime.now().strftime("%H:%M:%S"))
        
    except Exception as e:
        st.error(f"❌ Failed to load market data: {e}")
        if not is_market_open:
            st.info("This is expected as the market is closed.")


# ---------------------------
# Live Positions & P&L
# ---------------------------
st.subheader("💰 Live Portfolio (Paper)")
if angel:
    try:
        portfolio = angel.get_portfolio_value()
        positions = angel.get_positions()
        
        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Total Investment", f"₹{portfolio['total_investment']:,.2f}")
        with col2: st.metric("Current Value", f"₹{portfolio['total_current_value']:,.2f}")
        with col3: st.metric("Unrealized P&L", f"₹{portfolio['total_unrealized_pnl']:,.2f}", 
                       delta=f"{portfolio['total_unrealized_pnl']:,.2f}")
        st.metric("Today's Realized P&L", f"₹{portfolio['daily_realized_pnl']:,.2f}")
        
        if positions:
            st.write("**Current Open Positions**")
            df_positions = pd.DataFrame(positions)
            st.dataframe(df_positions[['tradingsymbol', 'qty', 'avg_price', 'current_price', 'unrealized_pnl', 'sl', 'tp']], 
                        width='stretch')
        else: st.info("No open positions.")
        
        trade_history = angel.get_trade_history()
        if trade_history:
            st.write("**Today's Closed Trades**")
            df_history = pd.DataFrame(trade_history)
            df_history['time'] = pd.to_datetime(df_history['timestamp'], unit='s').dt.strftime('%H:%M:%S')
            st.dataframe(df_history[['time', 'tradingsymbol', 'quantity', 'price', 'pnl']], width='stretch')

    except Exception as e:
        st.error(f"❌ Paper trading error: {e}")

# ---------------------------
# Real Option Chain Section
# ---------------------------
st.subheader("📋 Real Option Chain")
if angel:
    try:
        all_expiry_dates = angel.get_expiry_dates()
        
        # --- Show ALL expiries ---
        display_expiries = all_expiry_dates 
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if display_expiries:
                expiry = st.selectbox("Select Expiry", display_expiries, index=0)
                st.caption(f"Selected: {expiry}")
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
                ce_chain = atm_options[atm_options['type'] == 'CE']
                pe_chain = atm_options[atm_options['type'] == 'PE']
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**📈 CALL Options (ATM: ₹{atm_strike})**")
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
                total_oi_call = ce_chain['oi'].sum() if not ce_chain.empty else 0
                total_oi_put = pe_chain['oi'].sum() if not pe_chain.empty else 0
                pcr = total_oi_put / total_oi_call if total_oi_call > 0 else 0
                st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}")
            else:
                st.error("❌ No option chain data available for selected expiry")
    except Exception as e:
        st.error(f"❌ Failed to load option chain: {e}")
        if not is_market_open:
            st.info("This is expected as the market is closed. Expiry dates may be unavailable.")
    
# --- REMOVED BACKTESTING SECTION ---

# ---------------------------
# Backtesting Section - UPDATED
# ---------------------------
st.subheader("🧪 5m/15m EMA Daily Trend Strategy") 

if 'strategy_tester' not in st.session_state:
    try:
        st.session_state.strategy_tester = StrategyTester()
    except Exception as e:
         st.error(f"Failed to initialize StrategyTester: {e}")
         st.stop()

tester = st.session_state.strategy_tester

st.warning("""
**⚠️ REALISTIC INTRADAY BACKTEST (5m Data)**
1.  **Data Source**: Uses **real 5m historical data** from `yfinance` (Max 60 days).
2.  **Strategy**: Locks in 15m trend for the day, takes 5m alignment signals.
3.  **Sizing**: Trades **1 Lot (35 Units)** *only if* the simulated cost is **> ₹10,000**.
4.  **Risk**: **Stops trading for the day after 2 stop-loss hits.**
5.  **Trades the Index**: P&L is based on *index points*. "Simulated Option" is for reference.
""")

# --- Configuration ---
backtest_interval = "5m"
st.info(f"Using **{backtest_interval}** data interval for signals (Max 60 days).")

period_options = ["1d", "5d", "1mo", "60d"]
default_index = 3 # "60d"
backtest_period = st.selectbox(
    "Test Period (Max 60d)",
    period_options,
    index=default_index
)
# --- End Configuration ---

# --- UPDATED Risk Management ---
st.markdown("#### 🛡️ Risk & Sizing")
strategy_params = {} 

# --- RE-ADDED Starting Capital ---
strategy_params['initial_capital'] = st.number_input("Starting Capital (₹)", value=100000, min_value=10000, 
                                                   help="Used for P&L tracking and equity curve. Does not affect trade size.")

# Lot Size & Min Investment
rcol1, rcol2, rcol3 = st.columns(3)
with rcol1:
    strategy_params['lot_size'] = st.number_input("Lot Size", value=35, min_value=1, help="BankNifty Lot Size (35)")
with rcol2:
    strategy_params['min_investment'] = st.number_input("Min. Invest (₹)", value=10000, min_value=1000)
with rcol3:
    strategy_params['simulated_premium_pct'] = st.number_input("Sim. Premium (%)", value=0.8, min_value=0.1, max_value=5.0, step=0.1, format="%.1f") / 100.0 

# --- RE-ADDED SL Method Choice ---
sl_method_choice = st.selectbox(
    "Stop-Loss Method",
    ["Invested Value (%)", "ATR"], # Give choice
    index=0,
    help="**Invested Value (%):** SL = 5% of (Simulated Premium * Quantity). **ATR:** Dynamic SL/TP based on 5m ATR."
)
strategy_params['sl_mode'] = sl_method_choice

if sl_method_choice == "Invested Value (%)":
    st.info("SL based on % of calculated Invested Value | TP = SL Amount x Multiplier")
    iv_col1, iv_col2 = st.columns(2)
    with iv_col1:
        sl_pct = st.number_input("SL (% of Invested Value)", value=5.0, min_value=0.5, step=0.5)
        strategy_params['invested_value_sl_pct'] = sl_pct
    with iv_col2:
        tp_mult = st.number_input("TP (Multiplier of SL Amount)", value=2.0, min_value=1.0, step=0.5)
        strategy_params['tp_sl_ratio'] = tp_mult

elif sl_method_choice == "ATR":
    st.info("Using dynamic ATR-based Take Profit and Stop Loss.")
    atr_col1, atr_col2, atr_col3 = st.columns(3)
    with atr_col1: strategy_params['atr_period'] = st.number_input("ATR Period", value=14, min_value=1)
    with atr_col2: strategy_params['atr_tp_multiplier'] = st.number_input("ATR TP Multiplier", value=0.5, min_value=0.1, step=0.1, format="%.1f")
    with atr_col3: strategy_params['atr_sl_multiplier'] = st.number_input("ATR SL Multiplier", value=0.5, min_value=0.1, step=0.1, format="%.1f")

# --- End Risk Management ---


# Run Backtest
if st.button("🚀 RUN INTRADAY BACKTEST", use_container_width=True, type="primary"):
    with st.spinner(f"Fetching {backtest_period} of real {backtest_interval} data..."):
        try:
            # --- RE-ADDED initial_capital to the engine ---
            tester.engine.initial_capital = strategy_params['initial_capital']
            
            result = tester.engine.run_backtest(
                strategy_name="ema_daily_trend", 
                symbol="BANKNIFTY",
                period=backtest_period,
                interval=backtest_interval, 
                **strategy_params
            )

            st.session_state.backtest_result = result
            st.success(f"✅ Backtest completed! {result.total_trades} trades analyzed on REAL 5m data.")

        except Exception as e:
            st.error(f"❌ Backtest failed: {e}")
            st.exception(e)

# Display Results
if 'backtest_result' in st.session_state:
    result = st.session_state.backtest_result
    st.markdown("---")
    st.subheader("📊 BACKTEST RESULTS (ON REAL 5m DATA)")
    
    # ... (Metrics display as before) ...
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Total P&L", f"₹{result.total_pnl:,.0f}")
    with col1: st.metric("Win Rate", f"{result.win_rate:.1f}%")
    with col2: st.metric("Total Trades", result.total_trades)
    with col2: st.metric("Profit Factor", f"{result.profit_factor:.2f}")
    with col3: st.metric("Max Drawdown", f"{result.max_drawdown:.1f}%")
    with col3: st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    with col4: st.metric("Best Trade", f"₹{result.best_trade:,.0f}")
    with col4: st.metric("Worst Trade", f"₹{result.worst_trade:,.0f}")

    # Equity Curve
    st.markdown("#### 📈 Portfolio Growth")
    if result.equity_curve is not None and not result.equity_curve.empty:
        if isinstance(result.equity_curve.index, pd.DatetimeIndex): chart_data = result.equity_curve['equity']
        else: st.warning("Equity curve index is not timestamp."); chart_data = result.equity_curve['equity']
        st.line_chart(chart_data)
    else: st.info("No equity data to plot.")

    # Trade Analysis
    if result.trade_details:
        st.markdown("#### 📋 Full Trade Log")
        trades_df = pd.DataFrame(result.trade_details)
        all_trades = trades_df.copy()
        all_trades['entry_time'] = pd.to_datetime(all_trades['entry_time'], errors='coerce').dt.strftime('%m/%d %H:%M')
        all_trades['exit_time'] = pd.to_datetime(all_trades['exit_time'], errors='coerce').dt.strftime('%m/%d %H:%M')
        all_trades['invested_amount_fmt'] = all_trades['invested_amount'].apply(lambda x: f"₹{x:,.0f}" if pd.notna(x) else 'N/A')
        all_trades['entry_price_fmt'] = all_trades['entry_price'].apply(lambda x: f"₹{x:,.2f}" if pd.notna(x) else 'N/A')
        all_trades['exit_price_fmt'] = all_trades['exit_price'].apply(lambda x: f"₹{x:,.2f}" if pd.notna(x) else 'N/A')
        all_trades['pnl_fmt'] = all_trades['pnl'].apply(lambda x: f"₹{x:,.2f}" if pd.notna(x) else 'N/A')
        
        display_columns = [
            'entry_time', 'simulated_option', 'quantity', 'invested_amount_fmt',
            'entry_price_fmt', 'exit_time', 'exit_price_fmt', 'pnl_fmt', 'exit_reason'
        ]
        display_columns = [col for col in display_columns if col in all_trades.columns]
        
        st.dataframe(all_trades[display_columns], use_container_width=True, height=400)
    else: st.info("No trades were executed during this backtest period.")