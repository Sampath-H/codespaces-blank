# main.py - Main application entry point with AlgoRooms-inspired design

import sys
import subprocess

def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
    except ImportError:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        __import__(import_name)

for pkg in ["streamlit", "yfinance", "pandas", "openpyxl", "requests"]:
    install_and_import(pkg)

# Specific packages with different module names
install_and_import("upstox-python-sdk", "upstox_client")
install_and_import("protobuf", "google.protobuf")

import streamlit as st
import pandas as pd
import time
import os
import yfinance as yf
from datetime import datetime, timedelta, date

import pytz

# ---------------------------------------------------------------------------
# Backtesting Engine
# ---------------------------------------------------------------------------
def get_historical_market_days(lookback_selection):
    """Calculate the start and end dates based on the dropdown selection, skipping weekends."""
    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist)
    end_date = today
    
    if lookback_selection == "Today":
        start_date = today
    elif lookback_selection == "Yesterday":
        start_date = today - timedelta(days=1)
        while start_date.weekday() >= 5: # Skip weekends
            start_date -= timedelta(days=1)
    elif "Past" in lookback_selection:
        days_to_look_back = int(lookback_selection.split(" ")[1])
        start_date = today
        days_counted = 0
        while days_counted < days_to_look_back:
            start_date -= timedelta(days=1)
            if start_date.weekday() < 5: # Mon-Fri
                days_counted += 1
    else:
        start_date = today - timedelta(days=30)
        
    return start_date, end_date

def run_backtest(symbols, strategy, fast_ma, slow_ma, ma_type, target_pct, sl_pct, lookback, timeframe="5m", enable_options=False, opt_type=None, expiry_type=None, strike_selection=None, allow_carryover=False):
    """
    Simulates the strategy over the specified period and timeframe.
    Returns a dataframe of closed trades and summary metrics.
    """
    from upstox_api import UpstoxClient, PaperUpstoxClient
    
    start_time, end_time = get_historical_market_days(lookback)
    
    # Dates for Upstox (YYYY-MM-DD)
    # Pad by 30 days so long MAs (e.g. 200 EMA) can calculate before the simulation starts!
    start_str_base = (start_time - timedelta(days=30)).strftime("%Y-%m-%d")
    end_str_base = (end_time + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Map timeframe to Upstox supported natively
    if timeframe in ["1m", "5m", "15m"]:
        upstox_tf = "1minute"
    elif timeframe in ["30m", "1h"]:
        upstox_tf = "30minute"
    elif timeframe in ["1d"]:
        upstox_tf = "day"
    elif timeframe in ["1wk"]:
        upstox_tf = "week"
    elif timeframe in ["1mo"]:
        upstox_tf = "month"
    else:
        upstox_tf = "day"
    
    # Initialize Upstox Client (using Paper client for simulation since it falls back to yfinance when no active token, but can hit real api if logged in)
    api_key = st.session_state.get("api_key", "")
    api_secret = st.session_state.get("api_secret", "")
    access_token = st.session_state.get("access_token", "MOCK_TOKEN_FOR_TESTING")
    
    client = PaperUpstoxClient(api_key, api_secret, access_token)
    
    all_trades = []
    
    for symbol in symbols:
        try:
            sym_start_str = start_str_base
            sym_end_str = end_str_base
            
            # 1. FETCH SPOT DATA
            if symbol == "NIFTY":
                instrument = "NSE_INDEX|Nifty 50"
            elif symbol == "BANKNIFTY":
                instrument = "NSE_INDEX|Nifty Bank"
            elif symbol == "SENSEX":
                instrument = "BSE_INDEX|SENSEX"
            else:
                instrument = client.get_equity_instrument_token(symbol)
                if not instrument:
                    st.error(f"❌ Cannot find Upstox Master Contract for {symbol}. Is the ticker name exactly right?")
                    continue
                
            resp = client.get_historical_candle(instrument, upstox_tf, sym_end_str, sym_start_str)
            
            # Upstox might return empty candles if the market just opened, or it's a holiday, or API is delayed.
            # Instead of failing immediately, just try fetching the previous trading day's data up to 5 times.
            max_retries = 5
            attempt = 0
            while attempt < max_retries and (resp.get('status') != 'success' or not resp.get('data', {}).get('candles')):
                attempt += 1
                # Shift both dates backward by 1 day
                end_time_dt = datetime.strptime(sym_end_str, "%Y-%m-%d") - timedelta(days=1)
                start_time_dt = datetime.strptime(sym_start_str, "%Y-%m-%d") - timedelta(days=1)
                sym_end_str = end_time_dt.strftime("%Y-%m-%d")
                sym_start_str = start_time_dt.strftime("%Y-%m-%d")
                resp = client.get_historical_candle(instrument, upstox_tf, sym_end_str, sym_start_str)
            
            if resp.get('status') != 'success' or not resp['data']['candles']:
                st.error(f"❌ Upstox API Error for {symbol} after {max_retries} offset attempts: {resp.get('message', 'No data returned. Check your Upstox Login status or market holidays.')}")
                continue
                
            # Upstox returns oldest last. Reverse it so chronological.
            candles = resp['data']['candles'][::-1]
            df = pd.DataFrame(candles, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI'])
            
            # Convert timezone safely
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            # If the index already has timezone info (like +05:30), just convert its representation to Asia/Kolkata
            # If it's timezone-naive, assume it is ALREADY IST (because Upstox mock/real API returns IST), so just localize it
            if df.index.tz is not None:
                df.index = df.index.tz_convert('Asia/Kolkata')
            else:
                df.index = df.index.tz_localize('Asia/Kolkata')
            
            # Convert cols to float
            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = df[col].astype(float)
            
            # 1b. RESAMPLE IF NEEDED (since Upstox only gives 1m, 30m, day strictly)
            if timeframe in ["5m", "15m"]:
                rule = "5T" if timeframe == "5m" else "15T"
                df = df.resample(rule).agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum', 'OI': 'last'}).dropna()
            elif timeframe == "1h":
                df = df.resample('1H').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum', 'OI': 'last'}).dropna()
                
            
            # 2. RUN INDICATORS ON SPOT DATA
            if ma_type == "EMA":
                df['fast_ma'] = df['Close'].ewm(span=fast_ma, adjust=False).mean()
                df['slow_ma'] = df['Close'].ewm(span=slow_ma, adjust=False).mean()
            else:
                df['fast_ma'] = df['Close'].rolling(window=fast_ma).mean()
                df['slow_ma'] = df['Close'].rolling(window=slow_ma).mean()
                
            df.dropna(inplace=True)
            
            # Filter strictly to simulation window
            df = df[df.index.date >= start_time.date()]
            if df.empty: 
                st.warning(f"⚠️ No market data found for {symbol} within the selected timeframe ({start_time.date()} to {end_time.date()}).")
                continue
            
            in_position = False
            trade_side = ""
            entry_price = 0
            entry_time = None
            target = 0
            sl = 0
            
            # Options specific
            lot_size = 1
            option_symbol = ""
            premium_df = None
            
            # 3. RUN SIMULATION LOOP
            for i in range(1, len(df)):
                current = df.iloc[i]
                prev = df.iloc[i-1]
                
                # A) NOT IN POSITION -> LOOK FOR ENTRY ON SPOT
                if not in_position:
                    # Check Golden Cross vs Death Cross on Spot
                    signal = ""
                    if current['fast_ma'] > current['slow_ma'] and prev['fast_ma'] <= prev['slow_ma']:
                        signal = "BUY"
                    elif current['fast_ma'] < current['slow_ma'] and prev['fast_ma'] >= prev['slow_ma']:
                        signal = "SELL"
                        
                    if signal:
                        in_position = True
                        entry_time = df.index[i]
                        spot_price = float(current['Close'])
                        
                        if enable_options:
                            # Resolve the Option Contract!
                            st.toast(f"Resolving Option Contract for {symbol} at Spot ₹{spot_price}...")
                            opt_data = client.resolve_options_contract(symbol, spot_price, entry_time, expiry_type, opt_type, strike_selection)
                            
                            if not opt_data:
                                st.warning(f"Could not resolve option contract for {symbol} on {entry_time.date()}")
                                in_position = False
                                continue
                                
                            option_symbol = opt_data['trading_symbol']
                            lot_size = opt_data['lot_size']
                            
                            # Fetch 1m Premium History for exact execution
                            prem_resp = client.get_historical_candle(opt_data['instrument_token'], "1minute", end_str, entry_time.strftime("%Y-%m-%d"))
                            if prem_resp.get('status') == 'success' and prem_resp['data']['candles']:
                                p_candles = prem_resp['data']['candles'][::-1]
                                premium_df = pd.DataFrame(p_candles, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI'])
                                premium_df['timestamp'] = pd.to_datetime(premium_df['timestamp'])
                                premium_df.set_index('timestamp', inplace=True)
                                
                                # Find premium at exact entry time
                                entry_idx = premium_df[premium_df.index >= entry_time]
                                if not entry_idx.empty:
                                    entry_price = float(entry_idx.iloc[0]['Close'])
                                else:
                                    entry_price = float(premium_df.iloc[-1]['Close'])
                            else:
                                st.warning(f"No historical premium data available for {option_symbol}")
                                in_position = False
                                continue
                                
                            # Since we buy an Option, we always go LONG on the premium!
                            trade_side = "BUY"
                            target = entry_price * (1 + (target_pct / 100))
                            sl = entry_price * (1 - (sl_pct / 100))
                            
                        else:
                            # Standard Spot Equity execution
                            trade_side = signal
                            entry_price = round(spot_price, 2)
                            lot_size = 1
                            option_symbol = symbol
                            
                            if trade_side == "BUY":
                                target = entry_price * (1 + (target_pct / 100))
                                sl = entry_price * (1 - (sl_pct / 100))
                            else:
                                target = entry_price * (1 - (target_pct / 100))
                                sl = entry_price * (1 + (sl_pct / 100))
                
                # B) IN POSITION -> CHECK FOR EXIT
                else:
                    exit_price = 0
                    reason = ""
                    exit_time = current.name
                    
                    if enable_options and premium_df is not None:
                        # Scan 1-min premium chart from entry time to current loop time
                        active_premiums = premium_df[(premium_df.index > entry_time) & (premium_df.index <= current.name)]
                        for p_idx, p_row in active_premiums.iterrows():
                            high = float(p_row['High'])
                            low = float(p_row['Low'])
                            
                            if high >= target:
                                exit_price = round(target, 2)
                                reason = "Target Hit"
                                exit_time = p_idx
                                break
                            elif low <= sl:
                                exit_price = round(sl, 2)
                                reason = "Stop Loss Hit"
                                exit_time = p_idx
                                break
                    else:
                        # Standard Equity scan
                        high = float(current['High'])
                        low = float(current['Low'])
                        
                        if trade_side == "BUY":
                            if high >= target:
                                exit_price = round(target, 2)
                                reason = "Target Hit"
                            elif low <= sl:
                                exit_price = round(sl, 2)
                                reason = "Stop Loss Hit"
                        else: # SELL
                            if low <= target:
                                exit_price = round(target, 2)
                                reason = "Target Hit"
                            elif high >= sl:
                                exit_price = round(sl, 2)
                                reason = "Stop Loss Hit"
                        
                    # Force Intraday exit if not holding
                    if "minute" in upstox_tf and not allow_carryover:
                        if current.name.hour == 15 and current.name.minute >= 25:
                            if exit_price == 0: # Not hit yet
                                if enable_options and premium_df is not None:
                                    last_p = premium_df[premium_df.index <= current.name]
                                    exit_price = round(float(last_p.iloc[-1]['Close']), 2) if not last_p.empty else entry_price
                                else:
                                    exit_price = round(float(current['Close']), 2)
                                reason = "EOD Square-off"
                                exit_time = current.name
                        
                    if exit_price > 0:
                        if trade_side == "BUY":
                            pnl = round((exit_price - entry_price) * lot_size, 2)
                        else:
                            pnl = round((entry_price - exit_price) * lot_size, 2)
                            
                        pnl_pct = round((pnl / (entry_price * lot_size)) * 100, 2)
                        
                        all_trades.append({
                            "Symbol": option_symbol,
                            "Side": trade_side,
                            "Entry Time": entry_time.strftime("%Y-%m-%d %H:%M"),
                            "Exit Time": exit_time.strftime("%Y-%m-%d %H:%M"),
                            "Lot Size": lot_size,
                            "Entry Price": entry_price,
                            "Exit Price": exit_price,
                            "Reason": reason,
                            "P&L (₹)": pnl,
                            "P&L (%)": f"{pnl_pct}%"
                        })
                        in_position = False
                        
        except Exception as e:
            st.error(f"Error backtesting {symbol}: {e}")
            continue
            
    return pd.DataFrame(all_trades)
import os

from scanner import display_scanner_page
from algo_trading import display_algo_trading_page
from upstox_api import UpstoxClient

# helper for re-running the app in a version-compatible way

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.warning("Unable to rerun automatically; please reload the page.")

# optional preset credentials
PRESET_API_KEY = "3201b564-a593-42e4-bbae-c02d9687c91f"
PRESET_API_SECRET = "4m1evnlcq3"

def login_page():
    """Professional OAuth-style login page with AlgoRooms design."""

    # Auto-login trigger for "hardcoded auth"
    if PRESET_API_KEY and PRESET_API_SECRET:
        if "api_key" not in st.session_state:
            st.session_state["api_key"] = PRESET_API_KEY
            st.session_state["api_secret"] = PRESET_API_SECRET
            st.session_state["access_token"] = "MOCK_TOKEN_FOR_TESTING"
            st.session_state["profile"] = {"user_name": "Demo User (Auto-Login)", "email": "demo@example.com"}
            st.session_state["oauth_done"] = True
            safe_rerun()
            return

    # Professional login page styling
    st.markdown("""
    <style>
    .login-container {
        max-width: 500px;
        margin: 4rem auto;
        padding: 2rem;
        background: white;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        border: 1px solid #e5e7eb;
    }
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    .login-header h1 {
        color: #0a1e3f;
        margin-bottom: 0.5rem;
        font-size: 2.2rem;
        font-weight: 700;
    }
    .login-header p {
        color: #6b7280;
        margin: 0;
        font-size: 0.95rem;
    }
    .form-group {
        margin-bottom: 1.5rem;
    }
    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: #374151;
        font-size: 0.9rem;
    }
    .form-input {
        width: 100%;
        padding: 0.75rem;
        border: 2px solid #e5e7eb;
        border-radius: 8px;
        font-size: 0.95rem;
        transition: border-color 0.3s ease;
        box-sizing: border-box;
    }
    .form-input:focus {
        outline: none;
        border-color: #003d82;
        box-shadow: 0 0 0 3px rgba(0, 61, 130, 0.1);
    }
    .login-button {
        width: 100%;
        background-color: #003d82;
        color: white;
        border: none;
        padding: 1rem;
        border-radius: 8px;
        font-size: 0.95rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        margin-bottom: 1rem;
    }
    .login-button:hover {
        background-color: #002654;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 61, 130, 0.3);
    }
    .info-box {
        background: #f0f9ff;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    .warning-box {
        background: #fef3c7;
        border: 1px solid #f59e0b;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="login-container">
        <div class="login-header">
            <h1>📊 AlgoTrade</h1>
            <p>Professional Trading Platform</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Login form in a styled container
    with st.container():
        st.markdown('<div class="login-container">', unsafe_allow_html=True)

        st.markdown("### 🔐 Secure Login")
        st.markdown("Connect your Upstox trading account")

        env_key = os.environ.get("UPSTOX_API_KEY")
        env_secret = os.environ.get("UPSTOX_API_SECRET")
        default_api_key = st.session_state.get("api_key", "") or env_key or PRESET_API_KEY
        default_api_secret = st.session_state.get("api_secret", "") or env_secret or PRESET_API_SECRET

        if default_api_key and not st.session_state.get("api_key"):
            st.session_state["api_key"] = default_api_key
        if default_api_secret and not st.session_state.get("api_secret"):
            st.session_state["api_secret"] = default_api_secret

        api_key = st.text_input("API Key", value=default_api_key, key="login_api_key")
        api_secret = st.text_input("API Secret", value=default_api_secret, type="password", key="login_api_secret")

        default_redirect = st.session_state.get("redirect_uri", "https://codespaces-blank-9j75hn7qzwbp4maugggafc.streamlit.app/")
        if os.environ.get("CODESPACES"):
            cs = os.environ.get("CODESPACE_NAME")
            domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
            if cs and domain:
                default_redirect = f"https://{cs}-8501.{domain}/"
                st.session_state["redirect_uri"] = default_redirect

        redirect_uri = st.text_input(
            "Redirect URI",
            value=default_redirect,
            key="login_redirect_uri"
        )
        if redirect_uri:
            st.session_state["redirect_uri"] = redirect_uri

        st.markdown("""
        <div class="info-box">
            <strong>ℹ️ Important:</strong> Redirect URI must match exactly with your Upstox app settings.
        </div>
        """, unsafe_allow_html=True)

        if hasattr(st, "query_params"):
            params = st.query_params
        else:
            params = st.experimental_get_query_params()

        if (
            "code" in params
            and api_key
            and api_secret
            and redirect_uri
            and not st.session_state.get("oauth_done")
        ):
            raw_code = params.get("code")
            code = raw_code[0] if isinstance(raw_code, list) else raw_code
            try:
                token_resp = UpstoxClient.exchange_code(api_key, api_secret, code, redirect_uri)
                st.success("✅ Access token acquired via OAuth!")
                st.session_state["api_key"] = api_key
                st.session_state["api_secret"] = api_secret
                st.session_state["access_token"] = token_resp.get("access_token")
                st.session_state["refresh_token"] = token_resp.get("refresh_token")
                st.session_state["token_expires_in"] = token_resp.get("expires_in")
                st.session_state["redirect_uri"] = redirect_uri
                client = UpstoxClient(api_key, api_secret, st.session_state["access_token"])
                ok, profile = client.test_connection()
                if ok:
                    st.session_state["profile"] = profile
                st.session_state["oauth_done"] = True
                safe_rerun()
            except Exception as e:
                st.error(f"❌ Token exchange failed: {e}")

        if api_key and redirect_uri:
            st.markdown("### 🔗 Authorization")
            url2 = UpstoxClient.authorization_url(api_key, redirect_uri, use_v2=True)
            st.markdown(f"[🚀 Click here to authorize]({{ {url2} }})")

        st.markdown("### 🔑 Manual Login")
        access_token = st.text_input("Access Token (optional)", type="password", key="manual_token")
        if st.button("Login", use_container_width=True, key="manual_login"):
            if not api_key or not api_secret:
                st.error("API key and secret are required")
            else:
                client = UpstoxClient(api_key, api_secret, access_token or None)
                success, data = client.test_connection()
                if not success:
                    st.error(f"❌ Connection failed: {data}")
                else:
                    st.success("✅ Logged in successfully!")
                    st.session_state["api_key"] = api_key
                    st.session_state["api_secret"] = api_secret
                    st.session_state["access_token"] = access_token
                    st.session_state["profile"] = data
                    st.session_state["redirect_uri"] = redirect_uri
                    safe_rerun()

        st.markdown('</div>', unsafe_allow_html=True)


def main():
    # Set page configuration
    st.set_page_config(
        page_title="AlgoTrade Pro",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # AlgoRooms Professional Styling
    st.markdown("""
    <style>
    * {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    body, .main {
        background-color: #ffffff;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #1a1a2e !important;
        border-right: 1px solid #2d2d44;
    }
    
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBg"] {
        background-color: #1a1a2e !important;
    }
    
    /* Force sidebar text to be visible */
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label {
        background-color: transparent !important;
        padding: 0.75rem 0 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label > div {
        background-color: #252540 !important;
        padding: 0.75rem 1rem !important;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        color: #e0e0e0 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label > div:hover {
        background-color: #2d2d50 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label:has(input:checked) > div {
        background-color: #003d82 !important;
        color: #ffffff !important;
    }
    
    [data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {
        color: #ffffff !important;
    }
    
    [data-testid="stSidebar"] .stButton > button {
        background-color: #ef4444 !important;
        color: white !important;
        border: none !important;
    }
    
    /* Header */
    .header-container {
        background-color: #0a1e3f;
        color: white;
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    
    .header-container h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
    }
    
    .header-container p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
        font-size: 0.95rem;
    }
    
    /* Metric Card - Yellow Highlight */
    .metric-card {
        background-color: #fef08a;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        border-left: 4px solid #f59e0b;
        margin-bottom: 1rem;
        text-align: center;
    }
    
    .metric-card h3 {
        color: #1f2937;
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
    }
    
    .metric-card p {
        color: #666;
        margin: 0.5rem 0 0 0;
        font-size: 0.9rem;
    }
    
    /* Form Section */
    .form-section {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        border: 1px solid #e5e7eb;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    
    .form-section h3 {
        color: #1f2937;
        margin-bottom: 1rem;
        font-size: 1.1rem;
        font-weight: 600;
    }
    
    /* Selection Buttons */
    .button-group {
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        margin-bottom: 1rem;
    }
    
    .selection-button {
        padding: 0.5rem 1.25rem;
        border: 2px solid #d1d5db;
        background-color: white;
        border-radius: 6px;
        cursor: pointer;
        font-weight: 500;
        color: #374151;
        transition: all 0.3s ease;
        font-size: 0.9rem;
    }
    
    .selection-button:hover {
        border-color: #003d82;
        background-color: #f0f4ff;
    }
    
    .selection-button.active {
        background-color: #fef08a;
        border-color: #f59e0b;
        color: #1f2937;
    }
    
    /* Primary Button */
    .primary-btn {
        background-color: #003d82;
        color: white;
        padding: 0.75rem 1.5rem;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    
    .primary-btn:hover {
        background-color: #002654;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 61, 130, 0.3);
    }
    
    /* Dashboard Card */
    .dashboard-card {
        background: linear-gradient(135deg, #0a1e3f 0%, #1a3a5f 100%);
        color: white;
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }
    
    /* Status Indicators */
    .status-online {
        display: inline-block;
        width: 8px;
        height: 8px;
        background-color: #10b981;
        border-radius: 50%;
        margin-right: 0.5rem;
    }
    
    .status-offline {
        display: inline-block;
        width: 8px;
        height: 8px;
        background-color: #ef4444;
        border-radius: 50%;
        margin-right: 0.5rem;
    }
    
    /* Value Colors */
    .value-positive {
        color: #10b981;
        font-weight: 600;
    }
    
    .value-negative {
        color: #ef4444;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)

    # Require login
    if "api_key" not in st.session_state or "api_secret" not in st.session_state:
        login_page()
        return

    # Sidebar Navigation
    with st.sidebar:
        st.markdown("### 📊 AlgoTrade")
        st.markdown("---")
        
        page = st.radio(
            "Navigation",
            ["Dashboard", "📊 Scanner", "🤖 Algo Trading", "Strategies", "Backtest", "Reports", "Settings"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # User Info
        st.markdown("### 👤 Account")
        if "profile" in st.session_state:
            profile = st.session_state["profile"]
            st.markdown(f"**{profile.get('user_name', 'User')}**")
            st.caption(profile.get('email', 'user@example.com'))
        
        # Logout
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            safe_rerun()

    # Header
    st.markdown("""
    <div class="header-container">
        <h1>📊 AlgoTrade Pro</h1>
        <p>Professional Algorithmic Trading Platform</p>
    </div>
    """, unsafe_allow_html=True)

    # Page Routing
    if page == "Dashboard":
        display_dashboard()
    elif page == "📊 Scanner":
        display_scanner_page()
    elif page == "🤖 Algo Trading":
        display_algo_trading_page()
    elif page == "Strategies":
        display_strategies_page()
    elif page == "Backtest":
        display_backtest_page()
    elif page == "Reports":
        display_reports_page()
    elif page == "Settings":
        display_settings_page()


def display_dashboard():
    """Dashboard with key metrics and overview"""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        <div class="metric-card">
            <h3>₹2,45,000</h3>
            <p>Portfolio Value</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="metric-card">
            <h3>+₹5,200</h3>
            <p>Today's P&L</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="metric-card">
            <h3>12</h3>
            <p>Active Positions</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown("""
        <div class="metric-card">
            <h3>8</h3>
            <p>Strategies Running</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Dashboard Overview Card
    st.markdown("""
    <div class="dashboard-card">
        <h2>💼 Portfolio Overview</h2>
        <p>Your trading portfolio is performing well. All strategies are active and monitoring market conditions.</p>
        <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; margin-top: 1.5rem;">
            <div>
                <p><strong>✅ Terminal:</strong> <span class="status-online"></span>Connected</p>
                <p><strong>🤖 Trading Engine:</strong> <span class="status-online"></span>Active</p>
            </div>
            <div>
                <p><strong>📊 Strategy Templates</strong></p>
                <p style="font-size: 0.9rem;">3 ready-to-deploy templates available</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Strategy Performance
    st.markdown("### 📈 Strategy Performance")
    strategy_data = pd.DataFrame({
        'Strategy': ['Foundation Candle', 'Friday Breakout', 'Monthly Marubozu'],
        'Status': ['Active', 'Active', 'Paused'],
        'P&L': ['+₹1,250', '+₹820', '-₹150'],
        'Win Rate': ['62.5%', '58.3%', '45.2%']
    })
    st.dataframe(strategy_data, use_container_width=True, hide_index=True)


def display_strategies_page():
    """Strategies creation and management"""
    st.markdown("### 🔧 Strategy Management")
    
    tab1, tab2, tab3 = st.tabs(["Create", "My Strategies", "Templates"])
    
    with tab1:
        st.markdown('<div class="form-section">', unsafe_allow_html=True)
        st.markdown("#### Create New Strategy")
        
        with st.form("create_strategy", clear_on_submit=False):
            st.markdown("**Instrument Selection**")
            instrument_type = st.radio(
                "Type",
                ["Options", "Equity", "Futures", "Indices"],
                horizontal=True,
                label_visibility="collapsed"
            )
            
            instrument = st.selectbox("Select Instrument", ["NIFTY 50", "BANK NIFTY", "SENSEX"])
            
            st.markdown("**Strategy Parameters**")
            col1, col2 = st.columns(2)
            with col1:
                order_type = st.radio("Order Type", ["MIS", "CNC", "BTST"], horizontal=True)
            with col2:
                st.time_input("Start Time", value=datetime.now().time())
            
            st.markdown("**Conditions**")
            entry_ind = st.selectbox("Entry Indicator", ["Moving Average", "MACD", "RSI", "SuperTrend"], key="entry_ind")
            if entry_ind == "Moving Average":
                ecol1, ecol2 = st.columns(2)
                with ecol1:
                    st.number_input("Entry MA Length", min_value=1, value=9, key="entry_ma_len")
                with ecol2:
                    st.selectbox("Entry MA Type", ["SMA", "EMA", "WMA"], index=1, key="entry_ma_type")
            elif entry_ind == "MACD":
                ecol1, ecol2, ecol3 = st.columns(3)
                with ecol1:
                    st.number_input("Fast Length", min_value=1, value=12, key="entry_macd_fast")
                with ecol2:
                    st.number_input("Slow Length", min_value=1, value=26, key="entry_macd_slow")
                with ecol3:
                    st.number_input("Signal Length", min_value=1, value=9, key="entry_macd_sig")
            elif entry_ind == "RSI":
                ecol1, ecol2, ecol3 = st.columns(3)
                with ecol1:
                    st.number_input("RSI Length", min_value=1, value=14, key="entry_rsi_len")
                with ecol2:
                    st.number_input("Overbought", min_value=1, value=70, key="entry_rsi_ob")
                with ecol3:
                    st.number_input("Oversold", min_value=1, value=30, key="entry_rsi_os")
                    
            exit_ind = st.selectbox("Exit Indicator", ["Moving Average", "MACD", "RSI"], key="exit_ind")
            if exit_ind == "Moving Average":
                xcol1, xcol2 = st.columns(2)
                with xcol1:
                    st.number_input("Exit MA Length", min_value=1, value=21, key="exit_ma_len")
                with xcol2:
                    st.selectbox("Exit MA Type", ["SMA", "EMA", "WMA"], index=1, key="exit_ma_type")
            elif exit_ind == "RSI":
                st.number_input("Exit RSI Level", min_value=1, value=50, key="exit_rsi_level")
            
            if st.form_submit_button("Deploy Strategy", use_container_width=True):
                st.success("✅ Strategy deployed successfully!")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown("Your active strategies appear here")
        st.info("Go to **📊 Scanner** page from the sidebar to scan for trading setups.")
    
    with tab3:
        st.markdown("Pre-built strategy templates")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            <div class="form-section">
                <h4>Moving Average Crossover</h4>
                <p>A classic trend-following strategy</p>
                <button class="primary-btn" onclick="alert('Template loaded')">Load Template</button>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown("""
            <div class="form-section">
                <h4>Bollinger Bands Breakout</h4>
                <p>Trades breakouts from Bollinger Bands</p>
                <button class="primary-btn" onclick="alert('Template loaded')">Load Template</button>
            </div>
            """, unsafe_allow_html=True)


def display_backtest_page():
    """Backtest execution and simulated analysis"""
    st.markdown("### 📊 Engine Backtester")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown('<div class="form-section">', unsafe_allow_html=True)
        st.markdown("#### Setup Strategy")
        
        strategy = st.selectbox("Strategy to Backtest", ["Moving Average Crossover"])
        lookback = st.selectbox("Historical Horizon", ["Today", "Yesterday", "Past 3 Days", "Past 5 Days", "Past 10 Days", "Past 30 Days", "Past 90 Days"])
        timeframe = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"], index=1)
        
        st.markdown("**Parameters**")
        fast_len = st.number_input("Fast MA Length", 1, 200, 9)
        slow_len = st.number_input("Slow MA Length", 1, 200, 21)
        ma_type = st.selectbox("MA Type", ["SMA", "EMA"])
        
        st.markdown("**Risk Management**")
        tp_pct = st.number_input("Target Profit (%)", 0.1, 10.0, 2.0, step=0.1)
        sl_pct = st.number_input("Stop Loss (%)", 0.1, 10.0, 1.0, step=0.1)
        # Options UI Removed per user request
        opt_type, expiry_type, strike_selection, enable_options = None, None, None, False
        
        allow_carryover = st.checkbox("Allow Multi-Day Carryover (Ignore 3:25 PM Exit)", value=True, help="If enabled, intraday trades won't be forcefully closed at the end of the day, allowing them to ride big swing trends.")
            
        run_btn = st.button("▶️ Run Backtest", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        strategy_universe = st.radio(
            "Backtest Universe",
            ["Nifty 500", "F&O Stocks", "Indices", "Custom"],
            index=2,
            key="backtest_universe",
            horizontal=True
        )
        
        if strategy_universe == "Indices":
            index_choice = st.radio("Select Index", ["NIFTY", "BANKNIFTY", "SENSEX"], horizontal=True)
            symbols = [index_choice]
        elif strategy_universe == "Custom":
            symbols_str = st.text_area("Stock Universe (comma separated)", "RELIANCE.NS, SBIN.NS, TCS.NS", height=100)
            symbols = [s.strip() for s in symbols_str.split(",")]
        else:
            # Load from files
            try:
                if strategy_universe == "Nifty 500":
                    symbols_df = pd.read_csv("stocks_500.csv")
                else:
                    symbols_df = pd.read_csv("NSE_FO_Stocks_NS.csv")
                    
                col_name = 'Symbol' if 'Symbol' in symbols_df.columns else 'SYMBOL'
                symbols = symbols_df[col_name].tolist()
                symbols = [s + '.NS' if not s.endswith('.NS') else s for s in symbols]
            except Exception as e:
                st.error(f"Could not load stock universe: {e}")
                symbols = []
                
    with col2:
        if run_btn:
            with st.spinner(f"Simulating {timeframe} Trades for {lookback}..."):
                results_df = run_backtest(
                    symbols, strategy, fast_len, slow_len, ma_type, tp_pct, sl_pct, lookback, timeframe,
                    enable_options, opt_type, expiry_type, strike_selection, allow_carryover
                )
                
            if results_df.empty:
                st.warning(f"No completed trades found during {lookback}.")
            else:
                total_trades = len(results_df)
                winners = len(results_df[results_df['P&L (₹)'] > 0])
                losers = len(results_df[results_df['P&L (₹)'] <= 0])
                win_rate = round((winners / total_trades) * 100, 2)
                total_pnl = round(results_df['P&L (₹)'].sum(), 2)
                
                # To calculate real Total P&L %, we sum all PNL and divide by the sum of all Entry Prices (factoring lot size)
                if 'Lot Size' in results_df.columns:
                    total_entry_cost = (results_df['Entry Price'] * results_df['Lot Size']).sum()
                else:
                    total_entry_cost = results_df['Entry Price'].sum()
                    
                total_pnl_pct = round((total_pnl / total_entry_cost) * 100, 2) if total_entry_cost > 0 else 0
                
                # Summary Dashboard
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Trades", total_trades)
                m2.metric("Win Rate", f"{win_rate}%")
                m3.metric("Total Trade Wins", winners)
                m4.metric("Total Trades Lost", losers)
                
                if total_pnl > 0:
                    st.success(f"**Gross Strategy P&L:** +₹{total_pnl}   |   **Total P&L %:** +{total_pnl_pct}%")
                else:
                    st.error(f"**Gross Strategy P&L:** ₹{total_pnl}   |   **Total P&L %:** {total_pnl_pct}%")
                
                st.markdown("#### Detailed Trade Log")
                
                # Apply green/red styling to dataframe P&L
                def color_pnl(val):
                    color = '#28a745' if val > 0 else '#dc3545'
                    return f'color: {color}; font-weight: bold;'
                
                styled_df = results_df.style.applymap(color_pnl, subset=['P&L (₹)'])
                st.dataframe(styled_df, use_container_width=True, hide_index=True)
        else:
            st.info("Configure your strategy on the left and click **Run Backtest** to simulate historical P&L.")


def display_reports_page():
    """Trading reports and analytics"""
    st.markdown("### 📋 Trading Reports")
    
    st.markdown("#### Recent Trades")
    trades_data = pd.DataFrame({
        'Symbol': ['NIFTY', 'BANKNIFTY', 'SENSEX'],
        'Entry': ['09:15', '10:30', '11:45'],
        'Exit': ['09:45', '11:00', '12:15'],
        'Quantity': [1, 2, 1],
        'P&L': ['+₹250', '+₹400', '-₹150'],
        'Status': ['✅ Closed', '✅ Closed', '✅ Closed']
    })
    st.dataframe(trades_data, use_container_width=True, hide_index=True)


def display_settings_page():
    """Settings and configuration"""
    st.markdown("### ⚙️ Settings")
    
    tab1, tab2, tab3 = st.tabs(["Trading", "Alerts", "Account"])
    
    with tab1:
        st.markdown('<div class="form-section">', unsafe_allow_html=True)
        st.markdown("#### Trading Preferences")
        st.number_input("Max Position Size", value=10, min_value=1)
        st.number_input("Max Daily Loss", value=-5000, step=100)
        st.selectbox("Default Order Type", ["MIS", "CNC", "BTST"])
        if st.button("Save Settings", use_container_width=True):
            st.success("✅ Settings saved!")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown("Email and notification preferences")
    
    with tab3:
        st.markdown("Account information and profile settings")


if __name__ == "__main__":
    main()
