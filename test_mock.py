import sys
import os
import streamlit as st

# Setup mock session state
st.session_state = {'api_key': '', 'api_secret': '', 'access_token': 'MOCK_TOKEN_FOR_TESTING'}

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import run_backtest

print("Running NIFTY 1m test...")
df = run_backtest(['NIFTY'], 'Moving Average', 9, 21, 'SMA', 2.0, 1.0, 'Past 5 Days', '1m', enable_options=True, opt_type='CE', expiry_type='Weekly', strike_selection=0)

if df is not None and not df.empty:
    print(f"TRADES FOUND: {len(df)}")
    print(df.head())
else:
    print("NO TRADES RETURNED (EMPTY DF).")
