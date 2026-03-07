import streamlit as st
import pandas as pd
from datetime import datetime
from scanner import fetch_data, fetch_daily_breakout_data, scan_monthly_green_open, scan_monthly_red_open
from upstox_client import UpstoxClient, PaperUpstoxClient

# helper for re-running the app in a version-compatible way
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        # nothing we can do; user will have to manually refresh
        st.warning("Unable to rerun automatically; please reload the page.")

def display_algo_trading_page():
    """Main algo trading page UI"""
    st.title("🤖 Algo Trading")
    st.markdown("---")
    
    # Check if logged in
    if "api_key" not in st.session_state or "api_secret" not in st.session_state:
        st.error("Please login first from the main page.")
        return
    
    api_key = st.session_state["api_key"]
    api_secret = st.session_state["api_secret"]
    access_token = st.session_state.get("access_token")
    
    # Trading Mode Toggle
    st.sidebar.title("Trading Configuration")
    st.sidebar.markdown("---")
    paper_mode = st.sidebar.checkbox("Paper Trading Mode", value=True)
    st.sidebar.markdown("---")
    
    if paper_mode:
        st.sidebar.success("📝 Paper Trading: Orders will be simulated")
    else:
        st.sidebar.warning("💰 Live Trading: Orders will be placed on real account")
    
    # Connection Test
    st.subheader("🔗 Connection Status")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Test Connection"):
            client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
            client = client_cls(api_key, api_secret, access_token)
            success, data = client.test_connection()
            if success:
                st.success("Connection successful!")
                st.json(data)
            else:
                st.error(f"Connection failed: {data}")
    
    with col2:
        if st.button("Refresh Token"):
            if not access_token:
                st.error("No access token to refresh")
            else:
                try:
                    refresh_token = st.session_state.get("refresh_token")
                    if not refresh_token:
                        st.error("No refresh token available")
                    else:
                        token_resp = UpstoxClient.refresh_token(api_key, api_secret, refresh_token)
                        st.session_state["access_token"] = token_resp.get("access_token")
                        st.session_state["refresh_token"] = token_resp.get("refresh_token")
                        st.session_state["token_expires_in"] = token_resp.get("expires_in")
                        st.success("Token refreshed successfully!")
                        safe_rerun()
                except Exception as e:
                    st.error(f"Token refresh failed: {e}")
    
    with col3:
        if st.button("Clear Session"):
            for key in ["api_key", "api_secret", "access_token", "refresh_token", "profile", "oauth_done"]:
                st.session_state.pop(key, None)
            st.success("Session cleared!")
            st.experimental_rerun()
    
    st.markdown("---")
    
    # Manual Order Placement
    st.subheader("📝 Manual Order")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        order_symbol = st.text_input("Symbol", value="SBIN", key="manual_symbol")
    with col2:
        order_qty = st.number_input("Quantity", min_value=1, value=1, key="manual_qty")
    with col3:
        order_side = st.selectbox("Side", ["BUY", "SELL"], key="manual_side")
    with col4:
        order_type = st.selectbox("Type", ["MARKET", "LIMIT"], key="manual_type")
    with col5:
        order_price = st.text_input("Price (for LIMIT)", value="", key="manual_price")
    
    if st.button("📨 Place Order"):
        if not api_key or not api_secret or not access_token:
            st.error("Credentials not available")
        else:
            client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
            client = client_cls(api_key, api_secret, access_token)
            try:
                price_val = float(order_price) if order_price and order_type == "LIMIT" else None
                result = client.place_order(
                    symbol=order_symbol,
                    quantity=int(order_qty),
                    transaction_type=order_side,
                    order_type=order_type,
                    price=price_val,
                )
                st.success("Order placed successfully!")
                st.json(result)
                
                # Store in session for display
                if paper_mode:
                    orders = st.session_state.get("paper_orders", [])
                    orders.append(result)
                    st.session_state["paper_orders"] = orders
            except Exception as ex:
                st.error(f"Order failed: {ex}")
    
    # Strategy Execution
    st.markdown("---")
    st.subheader("⚙️ Strategy Execution")
    
    # Stock Universe for Strategy
    strategy_universe = st.selectbox(
        "Strategy Universe",
        ["Nifty 500", "F&O Stocks", "Custom"],
        key="strategy_universe"
    )
    
    if strategy_universe == "Custom":
        strategy_symbols = st.text_area("Enter symbols (comma-separated)", "SBIN.NS, RELIANCE.NS, TCS.NS")
        symbols = [s.strip() for s in strategy_symbols.split(",")]
    else:
        # Load from files
        try:
            if strategy_universe == "Nifty 500":
                symbols_df = pd.read_csv("stocks_500.csv")
            else:
                symbols_df = pd.read_csv("NSE_FO_Stocks_NS.csv")
            symbols = symbols_df['Symbol'].tolist()
            symbols = [s + '.NS' if not s.endswith('.NS') else s for s in symbols]
        except:
            st.error("Could not load stock universe")
            symbols = []
    
    strategy_type = st.selectbox(
        "Select Strategy",
        ["Current Signals", "Current Signals with Cluster Analysis", "Monthly Marubozu"],
        key="strategy_type"
    )
    
    if st.button("🚀 Run Strategy"):
        if not symbols:
            st.error("No symbols available for strategy")
        else:
            with st.spinner("Scanning for setups..."):
                if strategy_type == "Current Signals":
                    results = fetch_data(symbols, analysis_type="basic")
                    setups = pd.DataFrame(results) if results else pd.DataFrame()
                elif strategy_type == "Current Signals with Cluster Analysis":
                    results = fetch_data(symbols, analysis_type="cluster")
                    setups = pd.DataFrame(results) if results else pd.DataFrame()
                elif strategy_type == "Monthly Marubozu":
                    setups = scan_monthly_green_open(symbols)
            
            if setups.empty:
                st.warning("No setups found")
            else:
                st.success(f"Found {len(setups)} setups")
                st.dataframe(setups, use_container_width=True)
                
                # Execute orders
                if st.button("✅ Execute All Orders"):
                    client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
                    client = client_cls(api_key, api_secret, access_token)
                    
                    executed_orders = []
                    for _, row in setups.iterrows():
                        try:
                            # Determine side based on setup type
                            if "Bullish" in row.get('Setup Type', ''):
                                side = "BUY"
                            elif "Bearish" in row.get('Setup Type', ''):
                                side = "SELL"
                            else:
                                continue
                            
                            result = client.place_order(
                                symbol=row['Stock'] + '.NS',
                                quantity=1,  # Default quantity
                                transaction_type=side
                            )
                            executed_orders.append(result)
                            
                            if paper_mode:
                                orders = st.session_state.get("paper_orders", [])
                                orders.append(result)
                                st.session_state["paper_orders"] = orders
                                
                        except Exception as ex:
                            st.error(f"Order failed for {row['Stock']}: {ex}")
                    
                    if executed_orders:
                        st.success(f"Executed {len(executed_orders)} orders")
                        st.json(executed_orders)
    
    # Live Market Data
    st.markdown("---")
    st.subheader("📡 Live Market Data (OHLC)")
    st.info("Fetch real-time Open, High, Low, Close (OHLC) data directly from the Upstox API.")
    
    col1, col2 = st.columns(2)
    with col1:
        ohlc_symbols = st.text_input("Symbols (comma-separated)", value="RELIANCE.NS, SBIN.NS", help="Example: RELIANCE.NS, SBIN.NS")
    with col2:
        ohlc_interval = st.selectbox("Interval", ["1d", "I1", "I30"], help="1d: Daily (returns live_ohlc), I1: 1-min, I30: 30-min")
        
    if st.button("Fetch Live OHLC"):
        if not api_key or not access_token:
            st.error("Please provide API credentials and authenticate first.")
        elif not ohlc_symbols:
            st.warning("Please enter at least one instrument key.")
        else:
            # We use the real UpstoxClient even in paper mode to fetch real market data if token is valid
            client = UpstoxClient(api_key, api_secret, access_token)
            with st.spinner("Fetching live data..."):
                try:
                    ohlc_data = client.get_market_quote_ohlc(ohlc_symbols, ohlc_interval)
                    if ohlc_data and ohlc_data.get("status") == "success" and "data" in ohlc_data:
                        display_data = []
                        for key, value in ohlc_data["data"].items():
                            row = {"Instrument": key.split('|')[-1]}
                            # Based on interval, API returns 'ohlc' or 'live_ohlc' (or both)
                            if "ohlc" in value:
                                row.update(value["ohlc"])
                            elif "live_ohlc" in value:
                                row.update(value["live_ohlc"])  # '1d' typically returns live_ohlc
                            
                            # Add last_price if available
                            if "last_price" in value:
                                row["Last Price"] = value["last_price"]
                                
                            display_data.append(row)
                        
                        st.dataframe(pd.DataFrame(display_data), use_container_width=True)
                        with st.expander("View Raw JSON Response"):
                            st.json(ohlc_data)
                    else:
                        st.warning("No data returned or unexpected format.")
                        st.json(ohlc_data)
                except Exception as e:
                    st.error(f"Failed to fetch OHLC data: {e}")

    # WebSocket Live Stream
    st.markdown("---")
    st.subheader("⚡ WebSocket Live Stream & Strategy")
    st.info("Stream real-time tick data using Upstox WebSocket API v3. Data updates automatically without refreshing the page.")
    
    # Needs Upstox SDK
    try:
        from websocket_client import UpstoxStreamerManager, HAS_UPSTOX_SDK
    except ImportError:
        HAS_UPSTOX_SDK = False
        
    if not HAS_UPSTOX_SDK:
        st.warning("⚠️ `upstox-python-sdk` is required for WebSockets. Please deploy with the updated requirements.txt.")
    else:
        streamer_mgr = UpstoxStreamerManager()
        
        col1, col2 = st.columns([3, 1])
        with col1:
            ws_symbols = st.text_input("Stream Symbols (comma-separated)", value="RELIANCE.NS, TCS.NS", key="ws_symbols")
        with col2:
            st.write("Status:")
            st.write(f"**{st.session_state.get('streamer_status', 'Disconnected 🔴')}**")
            
        col3, col4, col5 = st.columns(3)
        with col3:
            if st.button("🔌 Connect Stream"):
                if not api_key or not access_token:
                    st.error("API credentials required.")
                else:
                    streamer_mgr.initialize(api_key, access_token)
                    keys = [k.strip() for k in ws_symbols.split(",")]
                    streamer_mgr.subscribe(keys)
                    safe_rerun()
        with col4:
            if st.button("🔄 Update Subscriptions"):
                keys = [k.strip() for k in ws_symbols.split(",")]
                streamer_mgr.subscribe(keys)
                st.success("Subscriptions updated.")
        with col5:
            if st.button("🛑 Disconnect"):
                streamer_mgr.stop()
                st.session_state["streamer_status"] = "Disconnected 🔴"
                safe_rerun()
                
        # Sample Real-time Strategy: Breakout Catcher
        st.markdown("#### 🚀 Demo Strategy: Real-time Breakout Catcher")
        st.write("Enable to trigger alerts if Last Traded Price (LTP) moves sharply while streaming.")
        enable_alerts = st.toggle("Enable Live Alerts")
        
        if enable_alerts:
            # We store the "last alerted price" to avoid spamming
            if "alert_history" not in st.session_state:
                st.session_state["alert_history"] = {}
                
            def check_breakout(tick):
                inst = tick['instrument']
                ltp = tick['ltp']
                history = st.session_state["alert_history"]
                
                # Dummy logic: if price changes by > 0.5% from the first seen price
                if inst not in history:
                    history[inst] = {'initial_price': ltp, 'last_alert_time': 0}
                else:
                    initial = history[inst]['initial_price']
                    change_pct = ((ltp - initial) / initial) * 100
                    
                    if abs(change_pct) >= 0.5:
                        now = time.time()
                        if now - history[inst]['last_alert_time'] > 60: # Max 1 alert per minute
                            history[inst]['last_alert_time'] = now
                            side = "BULLISH 🟢" if change_pct > 0 else "BEARISH 🔴"
                            st.toast(f"🚨 {side} BREAKOUT on {inst}! Price: ₹{ltp} ({change_pct:+.2f}%)")
            
            streamer_mgr.set_callback(check_breakout)
        else:
            streamer_mgr.set_callback(None)

        # Autorefreshing UI Fragment for Live Data
        # Using Streamlit forms/fragments or a simple auto-refresh toggle
        auto_refresh = st.checkbox("🔄 Auto-refresh Live Table (every 2s)")
        
        live_data = streamer_mgr.get_live_data()
        
        if live_data:
            df_live = pd.DataFrame(list(live_data.values()))
            if 'timestamp' in df_live.columns:
                df_live['Time'] = pd.to_datetime(df_live['timestamp'], unit='s', utc=True)
                df_live['Time'] = df_live['Time'].dt.tz_convert('Asia/Kolkata').dt.strftime('%H:%M:%S')
                df_live.drop(columns=['timestamp'], inplace=True)
            
            # Format columns
            st.dataframe(df_live, use_container_width=True)
            
            if auto_refresh:
                time.sleep(2)
                safe_rerun()
        else:
            st.info("No live data received yet. Connect the stream and wait for market updates.")

    # Order History / Paper Orders
    st.markdown("---")
    st.subheader("📋 Order History")
    
    if paper_mode and st.session_state.get("paper_orders"):
        st.write("**Paper Orders:**")
        orders_df = pd.DataFrame(st.session_state["paper_orders"])
        st.dataframe(orders_df, use_container_width=True)
        
        if st.button("Clear Paper Orders"):
            st.session_state["paper_orders"] = []
            st.success("Paper orders cleared!")
            safe_rerun()
    else:
        st.info("No orders to display. Place some orders or run a strategy.")
    
    # Account Summary
    st.markdown("---")
    st.subheader("📊 Account Summary")
    
    client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
    client = client_cls(api_key, api_secret, access_token)
    
    try:
        # Get positions
        positions = client.get_positions()
        if positions:
            st.write("**Positions:**")
            positions_df = pd.DataFrame(positions)
            st.dataframe(positions_df, use_container_width=True)
        else:
            st.info("No positions found")
        
        # Get orders
        orders = client.get_orders()
        if orders:
            st.write("**Open Orders:**")
            orders_df = pd.DataFrame(orders)
            st.dataframe(orders_df, use_container_width=True)
        else:
            st.info("No open orders")
            
    except Exception as e:
        st.error(f"Failed to fetch account data: {e}")
    
    # Backtesting Section
    st.markdown("---")
    st.subheader("📈 Backtesting")
    
    backtest_symbol = st.text_input("Symbol for Backtest", "SBIN.NS")
    backtest_days = st.slider("Lookback Days", 30, 365, 90)
    
    if st.button("Run Backtest"):
        try:
            # Simple momentum backtest
            data = pd.DataFrame()  # Placeholder - implement actual backtest logic
            st.info("Backtesting feature - to be implemented")
            st.write("This would show historical performance of the strategy")
        except Exception as e:
            st.error(f"Backtest failed: {e}")