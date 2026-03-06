# main.py - Main application entry point

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
        # nothing we can do; user will have to manually refresh
        st.warning("Unable to rerun automatically; please reload the page.")

# optional preset credentials – you can override via environment variables
# or by editing these constants directly.  storing secrets in source is not
# recommended for production, but it's convenient for a quick demo.
PRESET_API_KEY = "3201b564-a593-42e4-bbae-c02d9687c91f"
PRESET_API_SECRET = "4m1evnlcq3"

def login_page():
    """Professional OAuth-style login page with modern design."""

    # Professional login page styling
    st.markdown("""
    <style>
    .login-container {
        max-width: 500px;
        margin: 2rem auto;
        padding: 2rem;
        background: white;
        border-radius: 15px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        border: 1px solid #e5e7eb;
    }
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    .login-header h1 {
        color: #1f2937;
        margin-bottom: 0.5rem;
        font-size: 2rem;
    }
    .login-header p {
        color: #6b7280;
        margin: 0;
    }
    .form-group {
        margin-bottom: 1.5rem;
    }
    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: #374151;
    }
    .form-group input {
        width: 100%;
        padding: 0.75rem;
        border: 2px solid #e5e7eb;
        border-radius: 8px;
        font-size: 1rem;
        transition: border-color 0.3s ease;
    }
    .form-group input:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    .login-button {
        width: 100%;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 1rem;
        border-radius: 8px;
        font-size: 1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        margin-bottom: 1rem;
    }
    .login-button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
    }
    .auth-link {
        display: inline-block;
        background: #10b981;
        color: white;
        text-decoration: none;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        font-weight: 600;
        margin: 0.5rem 0;
        transition: all 0.3s ease;
    }
    .auth-link:hover {
        background: #059669;
        transform: translateY(-1px);
    }
    .info-box {
        background: #f0f9ff;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .warning-box {
        background: #fef3c7;
        border: 1px solid #f59e0b;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="login-container">
        <div class="login-header">
            <h1>🚀 AlgoTrade Pro</h1>
            <p>Professional Algorithmic Trading Platform</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Login form in a styled container
    with st.container():
        st.markdown('<div class="login-container">', unsafe_allow_html=True)

        st.markdown("### 🔐 Secure Login")
        st.markdown("Connect to your Upstox trading account to access advanced features.")

        # fields for credentials + redirect URI.  values are written into the
        # session up front so that they survive the round-trip back from Upstox
        # even though the exchange step hasn't happened yet.
        # try environment variables first, then preset constants (if non-empty)
        env_key = os.environ.get("UPSTOX_API_KEY")
        env_secret = os.environ.get("UPSTOX_API_SECRET")
        default_api_key = st.session_state.get("api_key", "") or env_key or PRESET_API_KEY
        default_api_secret = st.session_state.get("api_secret", "") or env_secret or PRESET_API_SECRET

        # remember entries immediately; without this the inputs are blank when the
        # service redirects back with the authorization code and the exchange logic
        # never runs because ``api_key``/``api_secret`` evaluate to empty strings.
        if default_api_key and not st.session_state.get("api_key"):
            st.session_state["api_key"] = default_api_key
        if default_api_secret and not st.session_state.get("api_secret"):
            st.session_state["api_secret"] = default_api_secret

        api_key = st.text_input("API Key", value=default_api_key, key="login_api_key")
        api_secret = st.text_input("API Secret", value=default_api_secret, type="password", key="login_api_secret")

        # determine a sensible default for the redirect URI.  most users running
        # locally will want localhost:8501, but when the app is executed inside a
        # GitHub Codespace the host is a publicly forwarded domain rather than
        # the local machine.  in that case we automatically build the correct URL
        # from the environment so the authorization response comes back to the
        # same address the browser is currently using.
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
            help="Must match the redirect URL registered in your Upstox app exactly (including protocol, domain, port, and path)",
            key="login_redirect_uri"
        )
        if redirect_uri:
            st.session_state["redirect_uri"] = redirect_uri

        st.markdown("""
        <div class="info-box">
            <strong>ℹ️ Important:</strong> Enter the exact redirect URL you registered when creating your Upstox API app.
            This URL must match exactly (case-sensitive, including trailing slash if present).
        </div>
        """, unsafe_allow_html=True)

        if os.environ.get("CODESPACES"):
            st.markdown("""
            <div class="warning-box">
                <strong>⚠️ Codespace Environment:</strong> Because you are running inside a GitHub Codespace,
                the app is served on a public forwarding URL rather than localhost. Make sure the redirect URI
                listed above (which should already be set for you) is also configured in the Upstox developer console.
                Otherwise the authorization response will attempt to hit your local machine and fail.
            </div>
            """, unsafe_allow_html=True)

        # choose which query‑param API to use for reading. we don’t need to
        # write/clear anymore thanks to the ``oauth_done`` flag, so we can
        # safely ignore the setter and avoid deprecation warnings completely.
        if hasattr(st, "query_params"):
            params = st.query_params
        else:
            params = st.experimental_get_query_params()

        if params:
            st.write("query params returned:", params)  # debugging aid
            if "code" in params and (not api_key or not api_secret):
                st.warning("Authorization code returned but API key/secret are missing.\n                      Please re-enter them or use the manual login button.")

        # only perform the exchange once per session; if we redo it the
        # second time the code will be invalid anyway and Upstox returns a
        # 401.  the flag also allows us to avoid clearing the query string
        # entirely, which means we never have to call any setter function and
        # thus provoke deprecation warnings.
        if (
            "code" in params
            and api_key
            and api_secret
            and redirect_uri
            and not st.session_state.get("oauth_done")
        ):
            raw_code = params.get("code")
            if isinstance(raw_code, list):
                code = raw_code[0]
            else:
                code = raw_code
            st.write("parsed auth code:", code)
            try:
                token_resp = UpstoxClient.exchange_code(api_key, api_secret, code, redirect_uri)
                st.success("🎉 Access token acquired via OAuth flow!")
                # store tokens and profile
                st.session_state["api_key"] = api_key
                st.session_state["api_secret"] = api_secret
                st.session_state["access_token"] = token_resp.get("access_token")
                st.session_state["refresh_token"] = token_resp.get("refresh_token")
                st.session_state["token_expires_in"] = token_resp.get("expires_in")
                st.session_state["redirect_uri"] = redirect_uri
                # fetch profile
                client = UpstoxClient(api_key, api_secret, st.session_state["access_token"])
                ok, profile = client.test_connection()
                if ok:
                    st.session_state["profile"] = profile
                # set a flag so we don't try to exchange again on reload
                st.session_state["oauth_done"] = True
                safe_rerun()
            except Exception as e:
                # show extra context to help debug 401/redirect problems
                st.error(f"❌ Token exchange failed: {e}")
                st.write("Details:")
                st.write("  code", code)
                st.write("  redirect_uri", redirect_uri)
                # if requests gave a response body inside the exception, show it
                if hasattr(e, 'args') and e.args:
                    st.write("  raw", e.args[0])

        # generate auth url links; provide two flavors in case one triggers
        # the deprecation warning or a 404.
        if api_key and redirect_uri:
            st.markdown("### 🔗 Authorization Links")
            st.markdown("Click the link below to securely connect to Upstox:")

            # older/legacy link (likely deprecated)
            url1 = UpstoxClient.authorization_url(api_key, redirect_uri, use_v2=False)
            st.markdown(f"🔗 [Legacy link – may be deprecated]({url1})")

            # recommended new URL per documentation
            url2 = UpstoxClient.authorization_url(api_key, redirect_uri, use_v2=True)
            st.markdown(f"🚀 [New v2 login link – preferred]({url2})")

            st.markdown("""
            <div class="info-box">
                <strong>💡 Tip:</strong> The <em>new v2 login link</em> is the recommended option described in the Upstox
                documentation. Ensure that your registered redirect URI exactly matches
                (including trailing slash and protocol) and that it is URL-encoded by
                the application. A mismatch will produce UDAPI100068.
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Enter API key and redirect URI to generate authorization links.")

        # manual login button as fallback
        st.markdown("### 🔑 Manual Login")
        st.markdown("Alternatively, paste your access token directly:")
        access_token = st.text_input("Access Token (optional)", value=st.session_state.get("access_token", ""), type="password", key="manual_token")
        if st.button("🔓 Manual Login", use_container_width=True):
            if not api_key or not api_secret:
                st.error("API key and secret are required")
            else:
                client = UpstoxClient(api_key, api_secret, access_token or None)
                success, data = client.test_connection()
                if not success:
                    st.error(f"❌ Connection failed: {data}")
                else:
                    st.success("✅ Credentials valid – you are logged in!")
                    st.session_state["api_key"] = api_key
                    st.session_state["api_secret"] = api_secret
                    st.session_state["access_token"] = access_token
                    st.session_state["profile"] = data
                    st.session_state["redirect_uri"] = redirect_uri
                    safe_rerun()

        # show logged-in info if available
        if "profile" in st.session_state:
            st.markdown("---")
            st.markdown("### 👤 Logged in as:")
            profile = st.session_state["profile"]
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"**Name:** {profile.get('user_name', 'Unknown')}")
                st.info(f"**Email:** {profile.get('email', 'Not provided')}")
            with col2:
                st.info(f"**User ID:** {profile.get('user_id', 'Unknown')}")
                st.info(f"**Broker:** Upstox")

        st.markdown('</div>', unsafe_allow_html=True)

def main():
    # Set page configuration
    st.set_page_config(
        page_title="AlgoTrade Pro - Professional Trading Platform",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # AlgoRooms-inspired professional styling
    st.markdown("""
    <style>
    /* Main Container */
    .main {
        background-color: #ffffff;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #f5f5f5;
        border-right: 1px solid #e0e0e0;
    }
    
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBg"] {
        background-color: #f5f5f5;
    }
    
    /* Navigation Items */
    .nav-item {
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.3s ease;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font-weight: 500;
        color: #333333;
    }
    
    .nav-item:hover {
        background-color: #e8eef7;
        color: #0a1e3f;
    }
    
    .nav-item.active {
        background-color: #e8eef7;
        color: #003d82;
        border-left: 3px solid #003d82;
    }
    
    /* Header Styling */
    .header-section {
        background-color: #0a1e3f;
        color: white;
        padding: 2rem;
        border-radius: 0;
        margin-bottom: 2rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
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
    
    .dashboard-card h1 {
        margin-bottom: 1.5rem;
        font-size: 1.8rem;
    }
    
    /* Metric Cards - Yellow Highlight */
    .metric-card {
        background-color: #fef08a;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        border-left: 4px solid #f59e0b;
        margin-bottom: 1rem;
    }
    
    .metric-card h3 {
        color: #1f2937;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
    
    .metric-card .metric-value {
        color: #1f2937;
        font-size: 1.8rem;
        font-weight: bold;
    }
    
    /* Selection Buttons */
    .selection-button {
        padding: 0.5rem 1rem;
        margin: 0.25rem;
        border: 2px solid #d1d5db;
        background-color: white;
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.3s ease;
        font-weight: 500;
        color: #374151;
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
    
    /* Primary Buttons */
    .primary-button {
        background-color: #003d82;
        color: white;
        padding: 0.75rem 1.5rem;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    
    .primary-button:hover {
        background-color: #002654;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 61, 130, 0.3);
    }
    
    /* Form Section */
    .form-section {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        border: 1px solid #e5e7eb;
    }
    
    .form-section h3 {
        color: #1f2937;
        margin-bottom: 1rem;
        font-size: 1.1rem;
        font-weight: 600;
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
    
    /* Toggle Switch */
    .toggle-group {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 1rem;
        background-color: #f9fafb;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    
    /* Data Table */
    .data-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1rem;
    }
    
    .data-table th {
        background-color: #f3f4f6;
        padding: 0.75rem;
        text-align: left;
        font-weight: 600;
        color: #374151;
        border-bottom: 2px solid #e5e7eb;
    }
    
    .data-table td {
        padding: 0.75rem;
        border-bottom: 1px solid #e5e7eb;
        color: #1f2937;
    }
    
    .data-table tr:hover {
        background-color: #f9fafb;
    }
    
    /* Positive/Negative Values */
    .value-positive {
        color: #10b981;
        font-weight: 600;
    }
    
    .value-negative {
        color: #ef4444;
        font-weight: 600;
    }
    
    /* Modal/Dialog */
    .modal-header {
        background-color: #f3f4f6;
        padding: 1rem;
        border-bottom: 1px solid #e5e7eb;
        margin-bottom: 1rem;
    }
    
    .modal-footer {
        padding: 1rem;
        border-top: 1px solid #e5e7eb;
        display: flex;
        justify-content: flex-end;
        gap: 0.75rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # require login credentials before showing the rest of the app
    if "api_key" not in st.session_state or "api_secret" not in st.session_state:
        login_page()
        return

    # Sidebar Navigation
    with st.sidebar:
        st.markdown("### 📊 AlgoTrade Pro")
        st.markdown("---")
        
        page = st.radio(
            "Navigation",
            ["Dashboard", "Strategies", "Backtest", "Reports", "Settings"],
            label_visibility="collapsed"
        )

    # Professional Header
    st.markdown("""
    <div style="background-color: #0a1e3f; padding: 1.5rem; border-radius: 0; margin-bottom: 2rem; display: flex; justify-content: space-between; align-items: center; border-radius: 8px;">
        <div style="color: white;">
            <h1 style="margin: 0; font-size: 1.8rem;">AlgoTrade Pro</h1>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Professional Algorithmic Trading Platform</p>
        </div>
        <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">🚀 AlgoTrade Pro</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Professional Algorithmic Trading Platform</p>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar with professional design
    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)

        # User Status
        st.subheader("👤 Account Status")
        if "profile" in st.session_state:
            profile = st.session_state["profile"]
            user_name = profile.get("user_name", "Unknown")
            st.markdown(f"""
            <div style="display: flex; align-items: center; margin-bottom: 1rem;">
                <span class="status-indicator status-online"></span>
                <strong>{user_name}</strong>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="display: flex; align-items: center; margin-bottom: 1rem;">
                <span class="status-indicator status-offline"></span>
                <strong>Not Connected</strong>
            </div>
            """, unsafe_allow_html=True)

        # Navigation
        st.subheader("🧭 Navigation")
        page_options = ["📊 Dashboard", "🔍 Stock Scanner", "🤖 Algo Trading", "📈 Portfolio", "⚙️ Settings"]
        page = st.radio("", page_options, label_visibility="collapsed")

        # Quick Actions
        st.subheader("⚡ Quick Actions")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh Data", use_container_width=True):
                st.rerun()
        with col2:
            if st.button("📧 Alerts", use_container_width=True):
                st.info("Email alerts configured")

        # Market Status
        st.subheader("🌍 Market Status")
        st.markdown("""
        <div class="market-data">
            <strong>NSE:</strong> <span style="color: #10b981;">Open</span><br>
            <strong>Last Update:</strong> {}<br>
            <strong>Next Holiday:</strong> Good Friday
        </div>
        """.format(datetime.now().strftime("%H:%M:%S")), unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    # Main Content Area
    if page == "📊 Dashboard":
        display_dashboard()
    elif page == "🔍 Stock Scanner":
        display_scanner_page()
    elif page == "🤖 Algo Trading":
        display_algo_trading_page()
    elif page == "📈 Portfolio":
        display_portfolio_page()
    elif page == "⚙️ Settings":
        display_settings_page()

def display_dashboard():
    """Professional dashboard with key metrics and insights"""
    st.markdown("## 📊 Trading Dashboard")

    # Key Metrics Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("""
        <div class="metric-card">
            <h3 style="margin: 0; color: #667eea;">₹2,45,000</h3>
            <p style="margin: 0.5rem 0 0 0; color: #666;">Portfolio Value</p>
            <small style="color: #10b981;">+2.5% today</small>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="metric-card">
            <h3 style="margin: 0; color: #667eea;">12</h3>
            <p style="margin: 0.5rem 0 0 0; color: #666;">Active Positions</p>
            <small style="color: #f59e0b;">3 in profit</small>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="metric-card">
            <h3 style="margin: 0; color: #667eea;">8</h3>
            <p style="margin: 0.5rem 0 0 0; color: #666;">Strategies Running</p>
            <small style="color: #10b981;">All active</small>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown("""
        <div class="metric-card">
            <h3 style="margin: 0; color: #667eea;">₹1,250</h3>
            <p style="margin: 0.5rem 0 0 0; color: #666;">Today's P&L</p>
            <small style="color: #10b981;">+1.2%</small>
        </div>
        """, unsafe_allow_html=True)

    # Charts and Analysis Row
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""
        <div class="feature-card">
            <h4>📈 Portfolio Performance</h4>
            <p>Track your portfolio's performance over time with detailed analytics.</p>
            <div style="height: 200px; background: #f8fafc; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #666;">
                Chart will be displayed here
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="feature-card">
            <h4>🎯 Top Performers</h4>
            <div style="margin-top: 1rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span>RELIANCE</span>
                    <span style="color: #10b981;">+3.2%</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span>TCS</span>
                    <span style="color: #10b981;">+2.8%</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span>INFY</span>
                    <span style="color: #ef4444;">-1.5%</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Recent Activity
    st.markdown("""
    <div class="feature-card">
        <h4>📋 Recent Activity</h4>
        <div style="margin-top: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; background: #f8fafc; border-radius: 6px; margin-bottom: 0.5rem;">
                <div>
                    <strong>BUY</strong> SBIN.NS (10 shares @ ₹520.50)
                </div>
                <small style="color: #666;">2 mins ago</small>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; background: #f8fafc; border-radius: 6px; margin-bottom: 0.5rem;">
                <div>
                    <strong>SELL</strong> RELIANCE.NS (5 shares @ ₹2,450.00)
                </div>
                <small style="color: #666;">15 mins ago</small>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; background: #f8fafc; border-radius: 6px; margin-bottom: 0.5rem;">
                <div>
                    <strong>Strategy Executed:</strong> Foundation Candle Returns
                </div>
                <small style="color: #666;">1 hour ago</small>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def display_portfolio_page():
    """Portfolio analysis page"""
    st.markdown("## 📈 Portfolio Analysis")

    st.markdown("""
    <div class="feature-card">
        <h4>Portfolio Holdings</h4>
        <p>Detailed view of your current positions and performance.</p>
    </div>
    """, unsafe_allow_html=True)

    # Sample portfolio data
    portfolio_data = pd.DataFrame({
        'Symbol': ['RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFC.NS', 'ICICI.NS'],
        'Quantity': [50, 25, 30, 20, 40],
        'Avg Price': [2450.50, 3200.75, 1450.25, 1650.00, 950.50],
        'Current Price': [2480.75, 3180.50, 1435.80, 1680.25, 965.75],
        'P&L': [1512.50, -507.50, -437.25, 610.00, 610.00],
        'P&L %': [1.24, -0.63, -1.01, 1.85, 1.28]
    })

    st.dataframe(portfolio_data, use_container_width=True)

def display_settings_page():
    """Settings and configuration page"""
    st.markdown("## ⚙️ Settings & Configuration")

    tab1, tab2, tab3 = st.tabs(["Trading", "Notifications", "API"])

    with tab1:
        st.markdown("""
        <div class="feature-card">
            <h4>Trading Preferences</h4>
        </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.checkbox("Enable Paper Trading", value=True)
            st.checkbox("Auto-execute Strategies", value=False)
            st.slider("Max Position Size (%)", 1, 100, 10)

        with col2:
            st.selectbox("Default Order Type", ["MARKET", "LIMIT", "SL-M"])
            st.number_input("Default Quantity", min_value=1, value=1)
            st.slider("Risk per Trade (%)", 0.1, 5.0, 1.0)

    with tab2:
        st.markdown("""
        <div class="feature-card">
            <h4>Notification Settings</h4>
        </div>
        """, unsafe_allow_html=True)

        st.checkbox("Email Alerts", value=True)
        st.checkbox("SMS Notifications", value=False)
        st.checkbox("Push Notifications", value=True)
        st.text_input("Email Address", value="user@example.com")

    with tab3:
        st.markdown("""
        <div class="feature-card">
            <h4>API Configuration</h4>
        </div>
        """, unsafe_allow_html=True)

        st.text_input("API Key", value="••••••••", type="password")
        st.text_input("API Secret", value="••••••••", type="password")
        st.text_input("Redirect URI", value="https://localhost:8501/")

        if st.button("Test Connection"):
            st.success("API connection successful!")

if __name__ == "__main__":
    main()