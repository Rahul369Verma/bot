import streamlit as st
import pandas as pd
import time
import threading
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from fetcher.angel_client import AngelClient
from fetcher.fyers_data import FyersDataManager
from fetcher.kite_client import KiteClient
from backtest.backtest import StrategyTester
import os

# ---------------------------
# Constants
# ---------------------------
BOT_HEARTBEAT_SECONDS = 30
IST = ZoneInfo('Asia/Kolkata')

# ---------------------------
# Helper functions
# ---------------------------
def safe_dataframe_formatting(df, columns_format):
    """Safely formats a dataframe, handling missing columns."""
    df_copy = df.copy()
    for col, func in columns_format.items():
        if col in df_copy.columns:
            try:
                df_copy[col] = df_copy[col].apply(func)
            except Exception:
                pass 
    return df_copy

def format_volume(volume):
    if volume >= 10000000: return f'{volume/10000000:.2f}Cr'
    elif volume >= 100000: return f'{volume/100000:.2f}L'
    elif volume >= 1000: return f'{volume/1000:.2f}k'
    else: return str(volume)

def highlight_atm(row, atm_strike):
    """Highlights the ATM row."""
    if row['strike'] == atm_strike:
        return ['background-color: #FFFFE0; color: black'] * len(row)
    return [''] * len(row)

# ---------------------------
# Initialization Functions
# ---------------------------
@st.cache_resource
def init_fyers_manager():
    """Initializes the Fyers Data Manager (Cached)."""
    try:
        return FyersDataManager()
    except ValueError as e:
        st.error(f"Failed to init Fyers Manager: {e}")
        return None

@st.cache_resource
def init_kite_client(api_key, api_secret, access_token, paper=False):
    """Initializes the Kite Client (Cached)."""
    try:
        return KiteClient(api_key, api_secret, access_token, paper=paper)
    except Exception as e:
        st.error(f"Failed to initialize Kite Client: {e}")
        return None

@st.cache_resource
def init_angel_client(index_name: str, _fyers_manager, _kite_client=None, paper=True):
    """Initializes the Angel One Client (Cached)."""
    try:
        # We pass kite_client to AngelClient so it can use it for execution
        client = AngelClient(paper=paper, index_name=index_name, fyers_manager=_fyers_manager, kite_client=_kite_client)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Angel Client: {e}")
        return None

def initialize_session_state(fyers_manager):
    """Initializes session state variables."""
    # --- NEW: Force Re-init for Code Updates ---
    CURRENT_TESTER_VERSION = "1.2" # Bump this to force reload
    if 'tester_version' not in st.session_state or st.session_state.tester_version != CURRENT_TESTER_VERSION:
        if 'tester' in st.session_state:
            del st.session_state.tester
        st.session_state.tester_version = CURRENT_TESTER_VERSION
        st.rerun() # Rerun to ensure clean state

    if 'tester' not in st.session_state:
        try:
            # Initialize Strategy Tester
            st.session_state.tester = StrategyTester(fyers_manager)
            print("✅ StrategyTester initialized.")
        except Exception as e:
            st.error(f"Failed to initialize StrategyTester: {e}")
            st.session_state.tester = None # Ensure tester is None on failure

    if 'optimizer_running' not in st.session_state:
        st.session_state.optimizer_running = False
    if 'backtest_running' not in st.session_state:
        st.session_state.backtest_running = False
    if 'ai_training_running' not in st.session_state:
        st.session_state.ai_training_running = False
        
    # Check Fyers Auth
    if fyers_manager and fyers_manager.is_authenticated():
        st.session_state.fyers_authenticated = True
    else:
        st.session_state.fyers_authenticated = False

# ---------------------------
# The Bot's "Heartbeat" Loop
# ---------------------------
def bot_loop(client: AngelClient, stop_event: threading.Event):
    """
    Background thread that runs the bot's core logic every 30 seconds.
    """
    print("✅ Bot background thread started. Waiting for the next 30-second mark to align...")
    while not stop_event.is_set():
        try:
            current_time = time.time()
            seconds_to_wait = BOT_HEARTBEAT_SECONDS - (current_time % BOT_HEARTBEAT_SECONDS)
            time.sleep(seconds_to_wait)
            
            now_ist = datetime.now(IST)
            print(f"[DEBUG] Bot Wakeup: {now_ist.strftime('%H:%M:%S.%f')}")
            
            # Simple market hours check (9:15 AM - 3:30 PM, Mon-Fri)
            is_market_open = (now_ist.weekday() < 5) and (dt_time(9, 15) <= now_ist.time() <= dt_time(15, 30))
            
            if is_market_open:
                # 1. Check for new day reset
                t0 = time.time()
                client.check_new_day()
                
                # 2. Check P&L / Max Trades limits
                client.check_and_close_positions()
                t1 = time.time()
                
                # 3. Generate Signals & Trade
                signals = client.generate_continuous_signals()
                t2 = time.time()
                
                # --- NEW: Explicit Logging for User ---
                last_check_str = client.last_signal_check_time.strftime("%H:%M:%S") if client.last_signal_check_time else "N/A"
                print(f"[INFO] Last Update (IST): {now_ist.strftime('%H:%M:%S')} | Last Signal Check: {last_check_str}")
                print(f"[DEBUG] Cycle Stats: Checks={t1-t0:.3f}s, Signals={t2-t1:.3f}s")
                
        except Exception as e:
            print(f"❌ CRITICAL ERROR in bot_loop: {e}")
            time.sleep(5) 
