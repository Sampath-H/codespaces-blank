import streamlit as st
import pandas as pd
from datetime import datetime
from scanner import scan_foundation_candle_returns, scan_friday_breakout, scan_monthly_marubozu
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
        ["Foundation Candle Returns", "Friday Breakout", "Monthly Marubozu"],
        key="strategy_type"
    )
    
    if st.button("🚀 Run Strategy"):
        if not symbols:
            st.error("No symbols available for strategy")
        else:
            with st.spinner("Scanning for setups..."):
                if strategy_type == "Foundation Candle Returns":
                    setups = scan_foundation_candle_returns(symbols)
                elif strategy_type == "Friday Breakout":
                    setups = scan_friday_breakout(symbols)
                elif strategy_type == "Monthly Marubozu":
                    setups = scan_monthly_marubozu(symbols)
            
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