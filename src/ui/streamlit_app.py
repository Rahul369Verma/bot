# Modified: src/ui/streamlit_app.py
# Refactored into modular components.

import os
import sys
import time
import threading
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import streamlit as st
from dotenv import load_dotenv

# --- Path Setup ---
current_file_path = os.path.abspath(__file__)
ui_dir = os.path.dirname(current_file_path)
src_dir = os.path.dirname(ui_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# --- Imports from new modules ---
try:
    from ui.ui_utils import (
        init_fyers_manager, 
        init_fyers_manager, 
        init_angel_client, 
        init_kite_client,
        initialize_session_state, 
        bot_loop, 
        BOT_HEARTBEAT_SECONDS, 
        IST
    )
    from ui.sidebar import render_sidebar
    from ui.tabs.live_dashboard import render_live_dashboard
    from ui.tabs.backtest import render_backtest_tab
    from ui.tabs.optimizer import render_optimizer_tab
    from ui.tabs.ai_prediction import render_ai_prediction_tab
    from ui.tabs.settings import render_settings_tab
except ImportError as e:
    st.error(f"CRITICAL IMPORT ERROR: {e}")
    st.error(f"Failed to load modules. Is 'src' directory correctly added to path? Path being added: {src_dir}")
    st.stop()

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()
UI_REFRESH_SECONDS = 300  # 5 minutes - aligned with signal generation to reduce API calls     

# ---------------------------
# Clean up old logs (24h+)
# ---------------------------
if 'log_cleanup_done' not in st.session_state:
    print("🧹 Starting Log Cleanup...")
    try:
        from utils.log_utils import cleanup_old_logs
        cleanup_old_logs(max_age_hours=24)
        print("✅ Log Cleanup Finished.")
        st.session_state.log_cleanup_done = True
    except ImportError as e:
        print(f"❌ Log Cleanup Failed (ImportError): {e}")
        st.session_state.log_cleanup_done = True
    except Exception as e:
        print(f"❌ Log Cleanup Failed: {e}")
        st.session_state.log_cleanup_done = True 

# ---------------------------
# Main App Logic
# ---------------------------
st.set_page_config(page_title="Index Trading Bot", layout="wide")

# 1. Render Sidebar
selected_index, is_real_trading = render_sidebar()

# 2. Initialize Core Components
active_strategy_key = "mta_ema_crossover"
strategy_name_map = {
    'mta_ema_crossover': "MTA Crossover (EMA)"
}

fyers_manager = init_fyers_manager()

# --- Fyers Login Flow ---
# Check for auth_code in URL (callback from Fyers)
query_params = st.query_params
auth_code = query_params.get("auth_code")
fyers_status = query_params.get("s") # 'ok' or 'error'

if auth_code and fyers_status == "ok":
    if fyers_manager:
        st.info("🔄 Processing Fyers Login...")
        try:
            if fyers_manager.generate_and_save_token(auth_code):
                st.success("✅ Fyers Login Successful! Token generated.")
                # Clear query params to avoid re-processing
                st.query_params.clear()
                # Force reload to pick up new token
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Failed to generate Fyers token. Check logs.")
        except Exception as e:
            st.error(f"❌ Error during Fyers login: {e}")
    else:
        st.error("Fyers Manager not initialized.")

# --- Kite Login Flow (ALWAYS AVAILABLE) ---
# We allow Kite login even in Paper Mode to enable "Smart Exit" and fast data.
kite_client = None
kite_api_key = os.getenv("KITE_API_KEY")
kite_api_secret = os.getenv("KITE_API_SECRET")

if 'kite_access_token' not in st.session_state:
    st.session_state.kite_access_token = None

# Check for request_token in URL (callback from Kite)
query_params = st.query_params
request_token = query_params.get("request_token")

if st.session_state.kite_access_token is None:
    if request_token:
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=kite_api_key)
            data = kite.generate_session(request_token, api_secret=kite_api_secret)
            st.session_state.kite_access_token = data["access_token"]
            st.success("✅ Logged in to Kite successfully!")
            # Clear query params to avoid re-login on reload
            st.query_params.clear()
        except Exception as e:
            st.error(f"Kite Login Failed: {e}")
    else:
        # Only show login link if Real Trading OR if user wants to connect for Paper Mode data
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={kite_api_key}"
        if is_real_trading:
            st.warning("⚠️ Real Trading Enabled but not logged in.")
            st.markdown(f"[👉 Click here to Login to Kite]({login_url})")
            st.stop() # Stop execution until logged in for Real Mode
        else:
            # In Paper Mode, show optional login
            st.sidebar.markdown(f"[👉 Login to Kite (Optional)]({login_url})")
        
if st.session_state.kite_access_token:
    kite_client = init_kite_client(kite_api_key, kite_api_secret, st.session_state.kite_access_token, paper=False)
    if kite_client:
        if 'kite_toast_shown' not in st.session_state:
            st.session_state.kite_toast_shown = False
        
        if not st.session_state.kite_toast_shown:
            st.toast("Connected to Kite", icon="🚀")
            st.session_state.kite_toast_shown = True

# Initialize Angel Client (Inject Kite Client if available)
angel = init_angel_client(
    index_name=selected_index, 
    _fyers_manager=fyers_manager, 
    _kite_client=kite_client,
    paper=not is_real_trading
)

# 3. Initialize Session State
initialize_session_state(fyers_manager)
tester = st.session_state.tester

# 4. Start Bot Thread
with threading.Lock():
    if 'bot_thread' not in st.session_state or not st.session_state.bot_thread.is_alive():
        print("🚀 Starting Bot Background Thread...")
        stop_event = threading.Event()
        st.session_state.bot_stop_event = stop_event
        if angel:
            t = threading.Thread(target=bot_loop, args=(angel, stop_event), daemon=True)
            t.start()
            st.session_state.bot_thread = t
            print("✅ Bot background thread is now running.")
        else:
            st.error("Cannot start bot thread: Angel Client failed to initialize.")
    else:
        pass # Bot thread is already running

# 5. Main Title & Status
st.title(f"🎯 {selected_index} Live Trading Bot {'(PAPER MODE)' if angel and angel.paper else '(REAL MONEY MODE)'}")

if angel and angel.paper:
    if kite_client:
        st.success("Bot is in PAPER TRADING mode (Using Kite Data & Smart Exit).")
    else:
        st.info("Bot is in PAPER TRADING mode (Using Standard Data). Login to Kite for Smart Exit.")
else:
    st.error("WARNING: Bot is in REAL MONEY mode. Real trades will be placed.")

now_ist = datetime.now(IST)
is_market_open = (now_ist.weekday() < 5) and (dt_time(9, 15) <= now_ist.time() <= dt_time(15, 30))

# 6. Render Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Live Dashboard", "Single Backtest", "Optimizer", "AI Prediction", "Settings"])

with tab1:
    render_live_dashboard(angel, selected_index, active_strategy_key, strategy_name_map, is_market_open, now_ist, UI_REFRESH_SECONDS)

with tab2:
    render_backtest_tab(tester, selected_index, fyers_manager)

with tab3:
    render_optimizer_tab(tester, selected_index, fyers_manager, active_strategy_key)

with tab4:
    render_ai_prediction_tab(tester)

with tab5:
    render_settings_tab(fyers_manager)