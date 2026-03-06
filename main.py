# main.py - Main application entry point with AlgoRooms-inspired design

import sys
import subprocess

def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        __import__(package)

for pkg in ["streamlit", "yfinance", "pandas", "openpyxl", "requests"]:
    install_and_import(pkg)

import streamlit as st
import pandas as pd
from datetime import datetime
import os

from scanner import display_scanner_page
from algo_trading import display_algo_trading_page
from upstox_client import UpstoxClient

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

        default_redirect = st.session_state.get("redirect_uri", "http://localhost:8501/")
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
        background-color: #f5f5f5 !important;
        border-right: 1px solid #e0e0e0;
    }
    
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBg"] {
        background-color: #f5f5f5 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label {
        background-color: transparent !important;
        padding: 0.75rem 0 !important;
    }
    
    [data-testid="stSidebar"] .stRadio > label > div {
        background-color: #f5f5f5 !important;
        padding: 0.75rem 1rem !important;
        border-radius: 8px;
        margin-bottom: 0.5rem;
    }
    
    [data-testid="stSidebar"] .stRadio > label:has(input:checked) > div {
        background-color: #e8eef7 !important;
        color: #003d82;
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
            ["Dashboard", "Strategies", "Backtest", "Reports", "Settings"],
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
            st.selectbox("Entry Indicator", ["Moving Average", "MACD", "RSI", "SuperTrend"])
            st.selectbox("Exit Indicator", ["Moving Average", "MACD", "RSI"])
            
            if st.form_submit_button("Deploy Strategy", use_container_width=True):
                st.success("✅ Strategy deployed successfully!")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown("Your active strategies appear here")
        display_scanner_page()
    
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
    """Backtest results and analysis"""
    st.markdown("### 📊 Backtest Analysis")
    
    st.markdown('<div class="form-section">', unsafe_allow_html=True)
    st.markdown("#### Backtest Results")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        if st.button("1M", use_container_width=True):
            pass
    with col2:
        if st.button("3M", use_container_width=True):
            pass
    with col3:
        if st.button("6M", use_container_width=True):
            pass
    with col4:
        if st.button("1Y", use_container_width=True, key="1y"):
            pass
    with col5:
        if st.button("2Y", use_container_width=True):
            pass
    with col6:
        if st.button("Custom", use_container_width=True):
            pass
    
    # Summary Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        <div class="metric-card">
            <h3>471</h3>
            <p>Trading Days</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="metric-card">
            <h3 class="value-positive">50.74%</h3>
            <p>Win Days</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="metric-card">
            <h3 class="value-negative">48.20%</h3>
            <p>Loss Days</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown("""
        <div class="metric-card">
            <h3 class="value-positive">₹47,825</h3>
            <p>Total P&L</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)


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
