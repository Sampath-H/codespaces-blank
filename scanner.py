import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import io
import base64
import os
from email_alert import send_email_alert

def get_weekdays_since_friday(friday_date):
    """Return a list of weekdays (dates) since the given Friday up to today (excluding weekends)."""
    today = datetime.now().date()
    days = []
    current = friday_date + timedelta(days=1)
    while current <= today:
        if current.weekday() < 5:  # Monday=0, ..., Friday=4
            days.append(current)
        current += timedelta(days=1)
    return days

@st.cache_data
def get_last_friday():
    """Calculate the date of the last Friday"""
    today = datetime.now()
    offset = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=offset + 7 if offset == 0 and today.hour < 18 else offset)
    return last_friday.date()



def scan_friday_breakout(symbols):
    """
    Scan for Friday breakout patterns.
    """
    results = []
    last_friday = get_last_friday()
    
    for symbol in symbols:
        try:
            # Get Friday data
            friday_data = yf.download(symbol, start=last_friday, end=last_friday + timedelta(days=1), progress=False)
            if friday_data.empty:
                continue
            
            friday_high = friday_data['High'].max()
            friday_low = friday_data['Low'].min()
            
            # Get current price
            current_data = yf.download(symbol, period="1d", interval="1m", progress=False)
            if current_data.empty:
                continue
            
            current_price = current_data['Close'].iloc[-1]
            
            # Check for breakout
            if current_price > friday_high:
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Friday High': round(friday_high, 2),
                    'Friday Low': round(friday_low, 2),
                    'Current Price': round(current_price, 2),
                    'Breakout %': round(((current_price - friday_high) / friday_high) * 100, 2),
                    'Setup Type': 'Bullish Breakout'
                })
            elif current_price < friday_low:
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Friday High': round(friday_high, 2),
                    'Friday Low': round(friday_low, 2),
                    'Current Price': round(current_price, 2),
                    'Breakout %': round(((friday_low - current_price) / friday_low) * 100, 2),
                    'Setup Type': 'Bearish Breakdown'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)

def scan_monthly_marubozu(symbols):
    """
    Scan for monthly Marubozu patterns.
    """
    results = []
    
    for symbol in symbols:
        try:
            # Get monthly data for the last 3 months
            monthly_data = yf.download(symbol, period="3mo", interval="1mo", progress=False)
            if monthly_data.empty or len(monthly_data) < 2:
                continue
            
            # Get the most recent month
            recent_month = monthly_data.iloc[-1]
            
            # Marubozu criteria: very small wicks relative to body
            body_size = abs(recent_month['Close'] - recent_month['Open'])
            total_range = recent_month['High'] - recent_month['Low']
            upper_wick = recent_month['High'] - max(recent_month['Open'], recent_month['Close'])
            lower_wick = min(recent_month['Open'], recent_month['Close']) - recent_month['Low']
            
            # Marubozu: wicks less than 10% of total range
            if upper_wick / total_range < 0.1 and lower_wick / total_range < 0.1:
                # Get current price
                current_data = yf.download(symbol, period="1d", interval="1m", progress=False)
                if current_data.empty:
                    continue
                
                current_price = current_data['Close'].iloc[-1]
                
                # Calculate retracement or rally
                marubozu_close = recent_month['Close']
                change_percentage = ((current_price - marubozu_close) / marubozu_close) * 100
                
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Marubozu Month': recent_month.name.strftime('%b %Y'),
                    'Marubozu Open': round(recent_month['Open'], 2),
                    'Marubozu High': round(recent_month['High'], 2),
                    'Marubozu Low': round(recent_month['Low'], 2),
                    'Marubozu Close': round(marubozu_close, 2),
                    'Current Price': round(current_price, 2),
                    'Change %': round(change_percentage, 2),
                    'Setup Type': 'Bullish Marubozu' if recent_month['Close'] > recent_month['Open'] else 'Bearish Marubozu'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)

def display_scanner_page():
    """Main scanner page UI"""
    st.title("📊 Stock Scanner")
    st.markdown("---")
    
    # Stock Universe Selection
    st.sidebar.title("Configuration")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📂 Stock Universe")
    stock_universe = st.sidebar.radio(
        "Select Stock Universe",
        ["Nifty 500", "F&O Stocks"],
        index=0
    )
    
    uploaded_file = st.sidebar.file_uploader(
        "Upload CSV file with stock symbols",
        type=['csv'],
        help="Upload a CSV file with a 'Symbol' column containing stock symbols"
    )
    
    if uploaded_file is not None:
        try:
            symbols_df = pd.read_csv(uploaded_file)
            symbol_col = None
            for col in symbols_df.columns:
                if col.lower() in ['symbol', 'symbols']:
                    symbol_col = col
                    break
            if symbol_col is None:
                st.sidebar.error("CSV file must contain a 'Symbol' or 'SYMBOL' column")
                return
            symbols = symbols_df[symbol_col].tolist()
        except Exception as e:
            st.sidebar.error(f"Error reading CSV: {e}")
            return
    else:
        # Load default universe
        if stock_universe == "Nifty 500":
            try:
                symbols_df = pd.read_csv("stocks_500.csv")
                symbols = symbols_df['Symbol'].tolist()
            except:
                st.error("Could not load Nifty 500 stocks. Please upload a CSV file.")
                return
        else:
            try:
                symbols_df = pd.read_csv("NSE_FO_Stocks_NS.csv")
                symbols = symbols_df['Symbol'].tolist()
            except:
                st.error("Could not load F&O stocks. Please upload a CSV file.")
                return
    
    # Add .NS suffix if not present
    symbols = [s + '.NS' if not s.endswith('.NS') else s for s in symbols]
    
    # Scanner Selection
    st.sidebar.markdown("### 🔍 Scanner Type")
    scanner_type = st.sidebar.selectbox(
        "Choose Scanner",
        ["Friday Breakout", "Monthly Marubozu"]
    )
    
    if st.sidebar.button("🔍 Run Scan"):
        with st.spinner("Scanning stocks..."):
            if scanner_type == "Friday Breakout":
                results = scan_friday_breakout(symbols)
            elif scanner_type == "Monthly Marubozu":
                results = scan_monthly_marubozu(symbols)
            
            if not results.empty:
                st.success(f"Found {len(results)} setups")
                
                # Display results
                st.dataframe(results, use_container_width=True)
                
                # Export functionality
                csv = results.to_csv(index=False)
                b64 = base64.b64encode(csv.encode()).decode()
                href = f'<a href="data:file/csv;base64,{b64}" download="scan_results.csv">Download CSV</a>'
                st.markdown(href, unsafe_allow_html=True)
                
                # Email alerts
                if st.button("📧 Send Email Alert"):
                    try:
                        send_email_alert("Stock Scan Results", results.to_string())
                        st.success("Email sent successfully!")
                    except Exception as e:
                        st.error(f"Failed to send email: {e}")
            else:
                st.warning("No setups found matching the criteria.")
    