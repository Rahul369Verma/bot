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
import json

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
UI_REFRESH_SECONDS = 30  # 30 seconds - aligned with bot loop for faster updates     

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

# --- Kite Login Flow Removed ---
# User switched to Fyers completely.
kite_client = None


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
# Use a named thread to prevent duplicates across sessions/reloads
BOT_THREAD_NAME = "AngelBotThread"

with threading.Lock():
    # Check if thread is already running by name
    existing_thread = None
    for t in threading.enumerate():
        if t.name == BOT_THREAD_NAME:
            existing_thread = t
            break
            
    if existing_thread and existing_thread.is_alive():
        # Re-attach to session state if missing (e.g. after hard refresh)
        if 'bot_thread' not in st.session_state or st.session_state.bot_thread != existing_thread:
            st.session_state.bot_thread = existing_thread
            print(f"🔄 Re-attached to existing bot thread: {BOT_THREAD_NAME}")
    else:
        # Start new thread
        print("🚀 Starting Bot Background Thread...")
        stop_event = threading.Event()
        st.session_state.bot_stop_event = stop_event
        if angel:
            t = threading.Thread(target=bot_loop, args=(angel, stop_event), name=BOT_THREAD_NAME, daemon=True)
            t.start()
            st.session_state.bot_thread = t
            print(f"✅ Bot background thread started: {BOT_THREAD_NAME}")
        else:
            st.error("Cannot start bot thread: Angel Client failed to initialize.")

# 5. Main Title & Status
st.title(f"🎯 {selected_index} Live Trading Bot {'(PAPER MODE)' if angel and angel.paper else '(REAL MONEY MODE)'}")

if angel and angel.paper:
    st.info("Bot is in PAPER TRADING mode (Using Fyers Data).")
else:
    st.error("WARNING: Bot is in REAL MONEY mode. Real trades will be placed via FYERS.")
    if not fyers_manager or not fyers_manager.is_authenticated():
        st.error("❌ Fyers is NOT authenticated. Please login to Fyers to trade.")
        st.stop()


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