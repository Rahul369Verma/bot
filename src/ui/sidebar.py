import streamlit as st

from utils.constants import ALL_STOCKS

def render_sidebar():
    """Renders the sidebar and returns the selected index and trading mode."""
    st.sidebar.title("⚙️ Bot Controls")
    
    # Index Selection
    # Combine Indices and Stocks
    available_instruments = ["BANKNIFTY", "NIFTY 50"] + ALL_STOCKS
    
    selected_index = st.sidebar.selectbox(
        "SELECT INSTRUMENT", 
        available_instruments,
        key="selected_index"
    )
    
    st.sidebar.divider()
    
    # Trading Mode Selection
    st.sidebar.subheader("Trading Mode")
    trading_mode = st.sidebar.radio(
        "Select Mode",
        ["Paper Trading", "Real Trading"],
        index=0,
        key="trading_mode_radio",
        help="Paper Trading: Simulated execution.\nReal Trading: Executes orders on Kite."
    )
    
    is_real_trading = (trading_mode == "Real Trading")
    
    if is_real_trading:
        st.sidebar.warning("⚠️ REAL TRADING ENABLED")
    else:
        st.sidebar.success("📝 PAPER TRADING ACTIVE")
        
    return selected_index, is_real_trading
