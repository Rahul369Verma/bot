import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from kiteconnect import KiteConnect
from fetcher.kite_client import KiteClient
from urllib.parse import urlparse, parse_qs

st.title("BankNifty Options Bot")

api_key = os.getenv("KITE_API_KEY")
api_secret = os.getenv("KITE_API_SECRET")

# Extract request_token from URL params
query_params = st.experimental_get_query_params()
request_token = query_params.get("request_token", [None])[0]

# Session state to hold token
if "access_token" not in st.session_state:
    st.session_state.access_token = os.getenv("KITE_ACCESS_TOKEN")

# Login flow
if st.session_state.access_token is None and request_token is None:
    st.warning("You are not logged in. Please login to Zerodha.")
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    st.markdown(f"[Login to Kite]({login_url})")
    st.stop()

# Generate access_token when redirected back from Kite
if request_token and (st.session_state.access_token is None or st.session_state.access_token == ""):
    try:
        kite = KiteConnect(api_key=api_key)
        data = kite.generate_session(request_token, api_secret=api_secret)
        st.session_state.access_token = data["access_token"]
        st.success("Logged in successfully ✅")
    except Exception as e:
        st.error(f"Login Failed: {e}")
        st.stop()

# Initialize our trading client
kite = KiteClient(
    api_key=api_key,
    api_secret=api_secret,
    access_token=st.session_state.access_token
)

st.success("Connected to Kite ✅")

# Fetch Holdings
st.subheader("Holdings 🧺")
holdings = kite.get_holdings()
st.dataframe(holdings)

# Fetch Positions
st.subheader("Positions 📊")
positions = kite.get_positions()
st.dataframe(positions)

# Option chain
st.subheader("BankNifty Option Chain ⚡")
expiry_date = st.text_input("Expiry (YYYY-MM-DD)", "")
option_chain = kite.get_option_chain(expiry=expiry_date or None)

for option in option_chain:
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 2])
    col1.write(option["tradingsymbol"])
    col2.write(option["type"])
    col3.write(f"{option['strike']}")
    col4.write(f"LTP: {option.get('ltp', '-')}")
    
    if col5.button("BUY", key=f"buy-{option['tradingsymbol']}"):
        kite.place_order(tradingsymbol=option['tradingsymbol'], exchange="NFO",
                         transaction_type="BUY", quantity=25)
        st.success(f"Bought {option['tradingsymbol']} ✅")
