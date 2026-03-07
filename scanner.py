import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import io
import base64
import os
from email_alert import send_email_alert

def calculate_ema(data, column='Close', period=9):
    """Calculate Exponential Moving Average (EMA)"""
    return data[column].ewm(span=period, adjust=False).mean()

def calculate_sma(data, column='Close', period=9):
    """Calculate Simple Moving Average (SMA)"""
    return data[column].rolling(window=period).mean()

def calculate_vwap(data):
    """Calculate Volume Weighted Average Price (VWAP)"""
    if 'Volume' not in data.columns:
        return None
    data['vwap'] = (data['Close'] * data['Volume']).rolling(window=20).sum() / data['Volume'].rolling(window=20).sum()
    return data['vwap']

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

def find_foundation_candle(symbol, lookback_days=5):
    """
    Find the 1-hour foundation candle for a stock.
    Foundation candle criteria:
    1. A significant 1-hour candle (large body)
    2. High volume relative to average
    3. Clear breakout or breakdown pattern
    4. Acts as support/resistance level
    """
    try:
        # Get intraday data for the lookback period
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Download 1-hour data
        data = yf.download(symbol, start=start_date, end=end_date, interval="1h", auto_adjust=True, progress=False)
        
        if data.empty or len(data) < 10:
            return None
            
        # Clean up multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
            
        data = data.reset_index()
        data['Datetime'] = pd.to_datetime(data['Datetime'])
        data['Datetime'] = pd.to_datetime(data['Datetime'])
        data['Datetime'] = pd.to_datetime(data['Datetime'])
        
        # Calculate candle properties
        data['Body_Size'] = abs(data['Close'] - data['Open'])
        data['Total_Range'] = data['High'] - data['Low']
        data['Body_Percentage'] = (data['Body_Size'] / data['Total_Range']) * 100
        
        # Calculate volume moving average (if volume data available)
        if 'Volume' in data.columns:
            data['Volume_MA'] = data['Volume'].rolling(window=20, min_periods=1).mean()
            data['Volume_Ratio'] = data['Volume'] / data['Volume_MA']
        else:
            data['Volume_Ratio'] = 1  # Default if no volume data
        
        # Foundation candle criteria
        foundation_candidates = data[
            (data['Body_Percentage'] >= 60) &  # Strong body (at least 60% of range)
            (data['Body_Size'] >= data['Body_Size'].quantile(0.8)) &  # Large body relative to recent candles
            (data['Volume_Ratio'] >= 1.2) &  # Above average volume
            (data['Total_Range'] >= data['Total_Range'].quantile(0.7))  # Significant range
        ].copy()
        
        if foundation_candidates.empty:
            return None
        
        # Return the most recent foundation candle
        return foundation_candidates.iloc[-1]
    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        return None

def scan_foundation_candle_returns(symbols, entry_ma_length=9, exit_ma_length=21, ma_type='EMA'):
    """
    Scan for foundation candle returns: stocks that have returned to the foundation candle zone.
    
    Args:
        symbols: List of symbols to scan
        entry_ma_length: Period for entry moving average
        exit_ma_length: Period for exit moving average
        ma_type: Type of moving average ('EMA', 'SMA', 'VWAP')
    """
    results = []
    for symbol in symbols:
        try:
            # Get foundation candle
            foundation = find_foundation_candle(symbol)
            if foundation is None:
                continue
            
            # Get current price
            current_data = yf.download(symbol, period="1d", interval="1m", progress=False)
            if current_data.empty:
                continue
            
            current_price = current_data['Close'].iloc[-1]
            
            # Calculate moving averages
            if ma_type == 'EMA':
                entry_ma = calculate_ema(current_data, period=entry_ma_length).iloc[-1]
                exit_ma = calculate_ema(current_data, period=exit_ma_length).iloc[-1]
            elif ma_type == 'SMA':
                entry_ma = calculate_sma(current_data, period=entry_ma_length).iloc[-1]
                exit_ma = calculate_sma(current_data, period=exit_ma_length).iloc[-1]
            else:
                entry_ma = current_price
                exit_ma = current_price
            
            # Check if price has returned to foundation zone
            foundation_high = foundation['High']
            foundation_low = foundation['Low']
            
            # Calculate return to zone
            if current_price <= foundation_high and current_price >= foundation_low:
                # Calculate rally or decline from foundation close
                foundation_close = foundation['Close']
                rally_percentage = ((current_price - foundation_close) / foundation_close) * 100
                
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Foundation Date': foundation['Datetime'].strftime('%Y-%m-%d %H:%M'),
                    'Foundation Open': round(foundation['Open'], 2),
                    'Foundation High': round(foundation_high, 2),
                    'Foundation Low': round(foundation_low, 2),
                    'Foundation Close': round(foundation_close, 2),
                    'Current Price': round(current_price, 2),
                    'Entry MA': round(entry_ma, 2),
                    'Exit MA': round(exit_ma, 2),
                    'Rally %': round(rally_percentage, 2),
                    'Setup Type': 'Bullish Return' if rally_percentage > 0 else 'Bearish Return'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)

def scan_friday_breakout(symbols, entry_ma_length=9, exit_ma_length=21, ma_type='EMA'):
    """
    Scan for Friday breakout patterns.
    
    Args:
        symbols: List of symbols to scan
        entry_ma_length: Period for entry moving average
        exit_ma_length: Period for exit moving average
        ma_type: Type of moving average ('EMA', 'SMA', 'VWAP')
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
            
            # Calculate moving averages
            if ma_type == 'EMA':
                entry_ma = calculate_ema(current_data, period=entry_ma_length).iloc[-1]
                exit_ma = calculate_ema(current_data, period=exit_ma_length).iloc[-1]
            elif ma_type == 'SMA':
                entry_ma = calculate_sma(current_data, period=entry_ma_length).iloc[-1]
                exit_ma = calculate_sma(current_data, period=exit_ma_length).iloc[-1]
            else:
                entry_ma = current_price
                exit_ma = current_price
            
            # Check for breakout
            if current_price > friday_high:
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Friday High': round(friday_high, 2),
                    'Friday Low': round(friday_low, 2),
                    'Current Price': round(current_price, 2),
                    'Entry MA': round(entry_ma, 2),
                    'Exit MA': round(exit_ma, 2),
                    'Breakout %': round(((current_price - friday_high) / friday_high) * 100, 2),
                    'Setup Type': 'Bullish Breakout'
                })
            elif current_price < friday_low:
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Friday High': round(friday_high, 2),
                    'Friday Low': round(friday_low, 2),
                    'Current Price': round(current_price, 2),
                    'Entry MA': round(entry_ma, 2),
                    'Exit MA': round(exit_ma, 2),
                    'Breakout %': round(((friday_low - current_price) / friday_low) * 100, 2),
                    'Setup Type': 'Bearish Breakdown'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)

def scan_monthly_marubozu(symbols, entry_ma_length=9, exit_ma_length=21, ma_type='EMA'):
    """
    Scan for monthly Marubozu patterns.
    
    Args:
        symbols: List of symbols to scan
        entry_ma_length: Period for entry moving average
        exit_ma_length: Period for exit moving average
        ma_type: Type of moving average ('EMA', 'SMA', 'VWAP')
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
                
                # Calculate moving averages
                if ma_type == 'EMA':
                    entry_ma = calculate_ema(current_data, period=entry_ma_length).iloc[-1]
                    exit_ma = calculate_ema(current_data, period=exit_ma_length).iloc[-1]
                elif ma_type == 'SMA':
                    entry_ma = calculate_sma(current_data, period=entry_ma_length).iloc[-1]
                    exit_ma = calculate_sma(current_data, period=exit_ma_length).iloc[-1]
                else:
                    entry_ma = current_price
                    exit_ma = current_price
                
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
                    'Entry MA': round(entry_ma, 2),
                    'Exit MA': round(exit_ma, 2),
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
        ["Foundation Candle Returns", "Friday Breakout", "Monthly Marubozu"]
    )
    
    # Scan Parameters
    st.sidebar.markdown("### ⚙️ Parameters")
    lookback_days = st.sidebar.slider("Lookback Days", 1, 30, 5)
    
    if st.sidebar.button("🔍 Run Scan"):
        with st.spinner("Scanning stocks..."):
            if scanner_type == "Foundation Candle Returns":
                results = scan_foundation_candle_returns(symbols)
            elif scanner_type == "Friday Breakout":
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
    
    # Individual Stock Analysis
    st.markdown("---")
    st.subheader("🔬 Individual Stock Analysis")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        analysis_symbol = st.text_input("Enter Symbol", "SBIN.NS")
    with col2:
        if st.button("Analyze"):
            if analysis_symbol:
                foundation = find_foundation_candle(analysis_symbol)
                if foundation is not None:
                    st.write("**Foundation Candle Found:**")
                    st.json({
                        'Date': foundation['Datetime'].strftime('%Y-%m-%d %H:%M'),
                        'Open': round(foundation['Open'], 2),
                        'High': round(foundation['High'], 2),
                        'Low': round(foundation['Low'], 2),
                        'Close': round(foundation['Close'], 2),
                        'Volume': foundation.get('Volume', 'N/A'),
                        'Body %': round(foundation['Body_Percentage'], 1)
                    })
                else:
                    st.warning("No foundation candle found for this symbol.")