import sys
import subprocess

# optional preset credentials – you can override via environment variables
# or by editing these constants directly.  storing secrets in source is not
# recommended for production, but it's convenient for a quick demo.
PRESET_API_KEY = "3201b564-a593-42e4-bbae-c02d9687c91f"
PRESET_API_SECRET = "4m1evnlcq3"


def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        __import__(package)

for pkg in ["streamlit", "yfinance", "pandas", "openpyxl", "requests"]:
    install_and_import(pkg)

import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import io
import base64
import os
from email_alert import send_email_alert

from upstox_client import UpstoxClient, PaperUpstoxClient

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

# Set page configuration
st.set_page_config(
    page_title="Enhanced Stock Screener with Foundation Candle Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_data
def get_last_friday():
    """Calculate the date of the last Friday"""
    today = datetime.now()
    offset = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=offset + 7 if offset == 0 and today.hour < 18 else offset)
    return last_friday.date()

# ----------- NEW: 1-HOUR FOUNDATION CANDLE SCANNER -----------
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
            
        # Get the most recent foundation candle
        foundation_candle = foundation_candidates.iloc[-1]
        
        # Determine foundation levels (support and resistance)
        foundation_high = float(foundation_candle['High'])
        foundation_low = float(foundation_candle['Low'])
        foundation_open = float(foundation_candle['Open'])
        foundation_close = float(foundation_candle['Close'])
        
        # Foundation zone (the body of the candle)
        foundation_zone_top = max(foundation_open, foundation_close)
        foundation_zone_bottom = min(foundation_open, foundation_close)
        
        return {
            'datetime': foundation_candle['Datetime'],
            'open': foundation_open,
            'high': foundation_high,
            'low': foundation_low,
            'close': foundation_close,
            'zone_top': foundation_zone_top,
            'zone_bottom': foundation_zone_bottom,
            'body_size': float(foundation_candle['Body_Size']),
            'volume_ratio': float(foundation_candle.get('Volume_Ratio', 1)),
            'candle_type': 'Bullish' if foundation_close > foundation_open else 'Bearish'
        }
        
    except Exception as e:
        print(f"Error finding foundation candle for {symbol}: {e}")
        return None

def scan_foundation_candle_returns(symbols, progress_bar=None):
    """
    Scan for stocks where current price has returned to the 1-hour foundation candle zone
    """
    results = []
    total_symbols = len(symbols)
    
    for i, symbol in enumerate(symbols):
        try:
            if progress_bar:
                progress_bar.progress((i + 1) / total_symbols, 
                                    text=f"Scanning foundation candles for {symbol} ({i + 1}/{total_symbols})")
            
            # Find foundation candle
            foundation = find_foundation_candle(symbol)
            if not foundation:
                continue
                
            # Get current price
            current_data = yf.download(symbol, period="1d", interval="5m", auto_adjust=True, progress=False)
            if current_data.empty:
                continue
                
            current_price = float(current_data['Close'].iloc[-1])
            current_time = current_data.index[-1]
            
            # Check if current price is within foundation zone
            tolerance = 0.5  # 0.5% tolerance
            zone_tolerance = (foundation['zone_top'] - foundation['zone_bottom']) * (tolerance / 100)
            
            extended_zone_top = foundation['zone_top'] + zone_tolerance
            extended_zone_bottom = foundation['zone_bottom'] - zone_tolerance
            
            # Determine if price is back in foundation zone
            is_in_foundation_zone = extended_zone_bottom <= current_price <= extended_zone_top
            
            if is_in_foundation_zone:
                # Calculate additional metrics
                time_since_foundation = current_time - foundation['datetime']
                hours_since = time_since_foundation.total_seconds() / 3600
                
                distance_from_zone_center = current_price - ((foundation['zone_top'] + foundation['zone_bottom']) / 2)
                distance_percentage = (distance_from_zone_center / foundation['body_size']) * 100 if foundation['body_size'] > 0 else 0
                
                # Determine signal strength
                if abs(distance_percentage) <= 25:
                    signal_strength = "Strong"
                elif abs(distance_percentage) <= 50:
                    signal_strength = "Moderate"
                else:
                    signal_strength = "Weak"
                
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Foundation Time': foundation['datetime'].strftime('%b %d, %H:%M'),
                    'Foundation Type': foundation['candle_type'],
                    'Foundation High': format_price(foundation['high']),
                    'Foundation Low': format_price(foundation['low']),
                    'Zone Top': format_price(foundation['zone_top']),
                    'Zone Bottom': format_price(foundation['zone_bottom']),
                    'Current Price': format_price(current_price),
                    'Hours Since Foundation': round(hours_since, 1),
                    'Distance from Center': f"{distance_percentage:+.1f}%",
                    'Signal Strength': signal_strength,
                    'Volume Ratio': round(foundation['volume_ratio'], 2),
                    'Setup Type': f"{foundation['candle_type']} Foundation Return"
                })
                
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    
    return pd.DataFrame(results)

# ----------- EXISTING FUNCTIONS (keeping all your original code) -----------
def get_friday_first_hour_cluster(symbol, friday_date):
    try:
        data = yf.download(symbol, start=friday_date, end=friday_date + timedelta(days=1), progress=False, auto_adjust=True)
        if data is None or len(data) == 0:
            return None, None
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        data = data.reset_index()
        data['Date'] = data['Date'].dt.date
        friday_row = data[data['Date'] == friday_date]
        if len(friday_row) == 0:
            return None, None
        friday_row = friday_row.iloc[0]
        open_price = float(friday_row['Open'])
        day_high = float(friday_row['High'])
        day_low = float(friday_row['Low'])
        one_percent_range = open_price * 0.01
        half_day_range = (day_high - day_low) * 0.5
        cluster_range = min(one_percent_range, half_day_range)
        cluster_high = open_price + cluster_range
        cluster_low = open_price - cluster_range
        cluster_high = min(cluster_high, day_high)
        cluster_low = max(cluster_low, day_low)
        return cluster_high, cluster_low
    except Exception as e:
        st.warning(f"Error getting Friday cluster for {symbol}: {e}")
        return None, None

def fetch_data(symbols, progress_bar=None, analysis_type="basic"):
    results = []
    last_friday = get_last_friday()
    start_date = last_friday - timedelta(days=7)
    end_date = datetime.now().date()
    total_symbols = len(symbols)
    for i, symbol in enumerate(symbols):
        try:
            if progress_bar:
                progress_bar.progress((i + 1) / total_symbols, 
                                    text=f"Processing {symbol} ({i + 1}/{total_symbols})")
            data = yf.download(symbol, start=start_date, end=end_date + timedelta(days=1), progress=False, auto_adjust=True)
            if data is None or len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            data = data.reset_index()
            data['Date'] = data['Date'].dt.date
            friday_mask = (data['Date'] == last_friday)
            friday_data = data[friday_mask]
            if len(friday_data) == 0:
                continue
            latest_row = data.iloc[-1]
            latest_date = latest_row['Date']
            if len(data) >= 2:
                prev_close = data.iloc[-2]['Close']
            else:
                prev_close = latest_row['Open']
            latest_close = latest_row['Close']
            chng = latest_close - prev_close
            pct_chng = (chng / prev_close) * 100 if prev_close != 0 else 0
            friday_low = friday_data['Low'].iloc[0]
            friday_high = friday_data['High'].iloc[0]
            result = {
                'Stock': symbol.replace('.NS', ''),
                'Latest Date': latest_date,
                'Open': format_price(latest_row['Open']),
                'High': format_price(latest_row['High']),
                'Low': format_price(latest_row['Low']),
                'Prev. Close': format_price(prev_close),
                'LTP': format_price(latest_close),
                'CHNG': format_price(chng),
                '%CHNG': format_price(pct_chng),
                'Friday High': format_price(friday_high),
                'Friday Low': format_price(friday_low)
            }
            if analysis_type == "cluster":
                signal, cluster_high, cluster_low = analyze_with_cluster_logic(
                    symbol, data, last_friday, friday_high, friday_low, latest_close
                )
                result['Signal'] = signal
                result['Friday Cluster High'] = format_price(cluster_high) if cluster_high else 'N/A'
                result['Friday Cluster Low'] = format_price(cluster_low) if cluster_low else 'N/A'
            else:
                if latest_close > friday_high:
                    signal = 'Bullish Confirmed'
                elif latest_close < friday_low:
                    signal = 'Bearish Confirmed'
                else:
                    signal = 'Neutral'
                result['Signal'] = signal
            results.append(result)
        except Exception as e:
            st.warning(f"Error fetching {symbol}: {e}")
            continue
    return results

def analyze_with_cluster_logic(symbol, data, friday_date, friday_high, friday_low, current_price):
    try:
        cluster_high, cluster_low = get_friday_first_hour_cluster(symbol, friday_date)
        if cluster_high is None or cluster_low is None:
            if current_price > friday_high:
                return 'Bullish Confirmed', None, None
            elif current_price < friday_low:
                return 'Bearish Confirmed', None, None
            else:
                return 'Neutral', None, None
        weekdays = get_weekdays_since_friday(friday_date)
        if not weekdays:
            return 'Neutral', cluster_high, cluster_low
        had_breakout = False
        had_breakdown = False
        for day in weekdays:
            day_data = data[data['Date'] == day]
            if len(day_data) == 0:
                continue
            day_row = day_data.iloc[0]
            day_close = float(day_row['Close'])
            if day_close > friday_high:
                had_breakout = True
            if day_close < friday_low:
                had_breakdown = True
        current_in_cluster = cluster_low <= current_price <= cluster_high
        if symbol.replace('.NS', '') in ['SUNPHARMA', 'SJVN']:
            st.write(f"Debug {symbol.replace('.NS', '')}: Current={current_price}, Friday High={friday_high}, Friday Low={friday_low}, Cluster={cluster_low}-{cluster_high}, InCluster={current_in_cluster}, Breakout={had_breakout}, Breakdown={had_breakdown}")
        if had_breakdown and current_in_cluster:
            return 'Breakdown Done but Price Returns Friday\'s Cluster', cluster_high, cluster_low
        elif had_breakout and current_in_cluster:
            return 'Breakout Done but Price Returns Friday\'s Cluster', cluster_high, cluster_low
        elif current_price > friday_high:
            return 'Bullish Confirmed', cluster_high, cluster_low
        elif current_price < friday_low:
            return 'Bearish Confirmed', cluster_high, cluster_low
        elif had_breakout or had_breakdown:
            return 'Post-Movement Consolidation', cluster_high, cluster_low
        else:
            return 'Neutral', cluster_high, cluster_low
    except Exception as e:
        st.warning(f"Cluster analysis error for {symbol}: {e}")
        if current_price > friday_high:
            return 'Bullish Confirmed', None, None
        elif current_price < friday_low:
            return 'Bearish Confirmed', None, None
        else:
            return 'Neutral', None, None

def fetch_daily_breakout_data(symbols, progress_bar=None):
    last_friday = get_last_friday()
    weekdays = get_weekdays_since_friday(last_friday)
    if not weekdays:
        return []
    start_date = last_friday - timedelta(days=7)
    end_date = datetime.now().date()
    daily_results = []
    total_symbols = len(symbols)
    for i, symbol in enumerate(symbols):
        try:
            if progress_bar:
                progress_bar.progress((i + 1) / total_symbols, 
                                    text=f"Processing daily data for {symbol} ({i + 1}/{total_symbols})")
            data = yf.download(symbol, start=start_date, end=end_date + timedelta(days=1), progress=False, auto_adjust=True)
            if data is None or len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            data = data.reset_index()
            data['Date'] = data['Date'].dt.date
            friday_mask = (data['Date'] == last_friday)
            friday_data = data[friday_mask]
            if len(friday_data) == 0:
                continue
            friday_low = friday_data['Low'].iloc[0]
            friday_high = friday_data['High'].iloc[0]
            breakout_day = None
            breakout_type = None
            for day in weekdays:
                day_mask = (data['Date'] == day)
                day_data = data[day_mask]
                if len(day_data) == 0:
                    continue
                day_high = day_data['High'].iloc[0]
                day_low = day_data['Low'].iloc[0]
                if day_high > friday_high and breakout_day is None:
                    breakout_day = day
                    breakout_type = 'Bullish'
                    break
                elif day_low < friday_low and breakout_day is None:
                    breakout_day = day
                    breakout_type = 'Bearish'
                    break
            latest_row = data.iloc[-1]
            latest_close = latest_row['Close']
            if latest_close > friday_high:
                current_signal = 'Bullish Confirmed'
            elif latest_close < friday_low:
                current_signal = 'Bearish Confirmed'
            else:
                current_signal = 'Neutral'
            daily_results.append({
                'Stock': symbol.replace('.NS', ''),
                'Friday High': format_price(friday_high),
                'Friday Low': format_price(friday_low),
                'Breakout Day': breakout_day.strftime('%A, %b %d') if breakout_day else 'No Breakout',
                'Breakout Type': breakout_type if breakout_type else 'None',
                'Current Price': format_price(latest_close),
                'Current Signal': current_signal,
                'Days Since Friday': len(weekdays) if weekdays else 0
            })
        except Exception as e:
            st.warning(f"Error fetching daily data for {symbol}: {e}")
            continue
    return daily_results

def color_signal(val):
    if val == 'Bullish Confirmed':
        return 'background-color: #d4edda; color: #155724'
    elif val == 'Bearish Confirmed':
        return 'background-color: #f8d7da; color: #721c24'
    elif 'Breakout Done but Price Returns' in val:
        return 'background-color: #fff3cd; color: #856404'
    elif 'Breakdown Done but Price Returns' in val:
        return 'background-color: #f8d7da; color: #721c24; font-style: italic'
    elif val == 'Post-Movement Consolidation':
        return 'background-color: #cce5ff; color: #004085'
    elif 'Foundation Return' in str(val):
        return 'background-color: #e1f5fe; color: #01579b; font-weight: bold'
    else:
        return 'background-color: #e2e3e5; color: #383d41'

def format_price(price):
    try:
        price_float = float(price)
        if price_float == int(price_float):
            return str(int(price_float))
        else:
            return f"{price_float:.2f}".rstrip('0').rstrip('.')
    except:
        return str(price)

def color_change(val):
    try:
        val_float = float(val)
        if val_float > 0:
            return 'color: #28a745'
        elif val_float < 0:
            return 'color: #dc3545'
        else:
            return 'color: #6c757d'
    except:
        return ''

def create_download_link(df, filename):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Screener Results')
    excel_data = output.getvalue()
    b64 = base64.b64encode(excel_data).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">Download Excel File</a>'
    return href


def simple_backtest(symbols, lookback_days=30):
    """Very basic backtester for demonstration purposes.

    This routine scans daily price data for the past *lookback_days* and
    generates a "long the next day" trade whenever the close is above the
    open.  Exits are taken at the following day's close.  It's not a real
    strategy, just a placeholder showing how you could simulate orders.
    """
    results = []
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days)
    for sym in symbols:
        try:
            data = yf.download(sym, start=start_date, end=end_date + timedelta(days=1),
                               progress=False, auto_adjust=True)
            if data.empty:
                continue
            data = data.reset_index()
            data['Date'] = data['Date'].dt.date
            for i in range(len(data) - 1):
                today = data.iloc[i]
                tomorrow = data.iloc[i + 1]
                if today['Close'] > today['Open']:
                    pnl = tomorrow['Close'] - today['Close']
                    results.append({
                        'Stock': sym,
                        'Entry Date': today['Date'],
                        'Entry Price': today['Close'],
                        'Exit Date': tomorrow['Date'],
                        'Exit Price': tomorrow['Close'],
                        'PnL': pnl
                    })
        except Exception:
            continue
    return pd.DataFrame(results)

# ----------- MONTHLY MARUBOZU FUNCTIONS (keeping your existing code) -----------
def scan_monthly_green_open(symbols):
    results = []
    for symbol in symbols:
        try:
            data = yf.download(symbol, period="4mo", interval="1mo", auto_adjust=True, progress=False)
            if len(data) < 2:
                continue
            prev_month = data.iloc[-2]
            prev_open = float(prev_month['Open'])
            prev_high = float(prev_month['High'])
            prev_low = float(prev_month['Low'])
            prev_close = float(prev_month['Close'])
            body_size = prev_close - prev_open
            total_range = prev_high - prev_low
            if body_size <= 0 or total_range <= 0:
                continue
            body_percentage = (body_size / total_range) * 100
            upper_wick = prev_high - prev_close
            lower_wick = prev_open - prev_low
            upper_wick_percentage = (upper_wick / body_size) * 100 if body_size > 0 else 0
            lower_wick_percentage = (lower_wick / body_size) * 100 if body_size > 0 else 0
            is_green_marubozu = (
                prev_close > prev_open and
                body_percentage >= 75 and
                upper_wick_percentage <= 25 and
                lower_wick_percentage <= 25
            )
            if not is_green_marubozu:
                continue
            current_data = yf.download(symbol, period="5d", interval="1d", auto_adjust=True, progress=False)
            if current_data.empty:
                continue
            current_price = float(current_data['Close'].iloc[-1])
            tolerance_percentage = 2.0
            tolerance_range = prev_open * (tolerance_percentage / 100)
            lower_bound = prev_open - tolerance_range
            upper_bound = prev_open + tolerance_range
            if lower_bound <= current_price <= upper_bound:
                retracement_from_high = ((prev_close - current_price) / (prev_close - prev_open)) * 100
                distance_from_prev_open = ((current_price - prev_open) / prev_open) * 100
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Prev Month': prev_month.name.strftime('%b %Y'),
                    'Prev Month Open': round(prev_open, 2),
                    'Prev Month High': round(prev_high, 2),
                    'Prev Month Low': round(prev_low, 2),
                    'Prev Month Close': round(prev_close, 2),
                    'Body %': round(body_percentage, 1),
                    'Current Price': round(current_price, 2),
                    'Distance from Prev Open': f"{distance_from_prev_open:+.1f}%",
                    'Retracement %': round(retracement_from_high, 1),
                    'Setup Type': 'Bullish Retracement'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)

def scan_monthly_red_open(symbols):
    results = []
    for symbol in symbols:
        try:
            data = yf.download(symbol, period="4mo", interval="1mo", auto_adjust=True, progress=False)
            if len(data) < 2:
                continue
            prev_month = data.iloc[-2]
            prev_open = float(prev_month['Open'])
            prev_high = float(prev_month['High'])
            prev_low = float(prev_month['Low'])
            prev_close = float(prev_month['Close'])
            body_size = prev_open - prev_close
            total_range = prev_high - prev_low
            if body_size <= 0 or total_range <= 0:
                continue
            body_percentage = (body_size / total_range) * 100
            upper_wick = prev_high - prev_open
            lower_wick = prev_close - prev_low
            upper_wick_percentage = (upper_wick / body_size) * 100 if body_size > 0 else 0
            lower_wick_percentage = (lower_wick / body_size) * 100 if body_size > 0 else 0
            is_red_marubozu = (
                prev_open > prev_close and
                body_percentage >= 75 and
                upper_wick_percentage <= 25 and
                lower_wick_percentage <= 25
            )
            if not is_red_marubozu:
                continue
            current_data = yf.download(symbol, period="5d", interval="1d", auto_adjust=True, progress=False)
            if current_data.empty:
                continue
            current_price = float(current_data['Close'].iloc[-1])
            tolerance_percentage = 2.0
            tolerance_range = prev_open * (tolerance_percentage / 100)
            lower_bound = prev_open - tolerance_range
            upper_bound = prev_open + tolerance_range
            if lower_bound <= current_price <= upper_bound:
                rally_from_low = ((current_price - prev_close) / (prev_open - prev_close)) * 100
                distance_from_prev_open = ((current_price - prev_open) / prev_open) * 100
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Prev Month': prev_month.name.strftime('%b %Y'),
                    'Prev Month Open': round(prev_open, 2),
                    'Prev Month High': round(prev_high, 2),
                    'Prev Month Low': round(prev_low, 2),
                    'Prev Month Close': round(prev_close, 2),
                    'Body %': round(body_percentage, 1),
                    'Current Price': round(current_price, 2),
                    'Distance from Prev Open': f"{distance_from_prev_open:+.1f}%",
                    'Rally %': round(rally_from_low, 1),
                    'Setup Type': 'Bearish Retracement'
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)


# helper for re-running the app in a version-compatible way

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        # nothing we can do; user will have to manually refresh
        st.warning("Unable to rerun automatically; please reload the page.")


def login_page():
    """OAuth-style login page.

    * Enter your app credentials and redirect URL.
    * Click the provided link to visit Upstox's authorization page.
    * After authorizing you will be redirected back with ``code`` in the
      query string; that code is then exchanged automatically for an
      access token.
    """
    st.title("🔐 Login to Upstox")
    st.write("Use your Developer App credentials and redirect URI below.")

    # fields for credentials + redirect URI.  values are written into the
    # session up front so that they survive the round‑trip back from Upstox
    # even though the exchange step hasn't happened yet.
    # try environment variables first, then preset constants (if non-empty)
    env_key = os.environ.get("UPSTOX_API_KEY")
    env_secret = os.environ.get("UPSTOX_API_SECRET")
    default_api_key = st.session_state.get("api_key", "") or env_key or PRESET_API_KEY
    default_api_secret = st.session_state.get("api_secret", "") or env_secret or PRESET_API_SECRET

    # if we have defaults and the session hasn't stored them yet, write them
    if default_api_key and not st.session_state.get("api_key"):
        st.session_state["api_key"] = default_api_key
    if default_api_secret and not st.session_state.get("api_secret"):
        st.session_state["api_secret"] = default_api_secret

    api_key = st.text_input("API Key", value=default_api_key)
    api_secret = st.text_input("API Secret", value=default_api_secret, type="password")

    # remember entries immediately; without this the inputs are blank when the
    # service redirects back with the authorization code and the exchange logic
    # never runs because ``api_key``/``api_secret`` evaluate to empty strings.
    if api_key:
        st.session_state["api_key"] = api_key
    if api_secret:
        st.session_state["api_secret"] = api_secret

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
        help="Must match the redirect URL registered in your Upstox app exactly (including protocol, domain, port, and path)"
    )
    if redirect_uri:
        st.session_state["redirect_uri"] = redirect_uri

    st.info(
        "Enter the exact redirect URL you registered when creating your Upstox API app. "
        "This URL must match exactly (case-sensitive, including trailing slash if present)."
    )
    if os.environ.get("CODESPACES"):
        st.warning(
            "Because you are running inside a GitHub Codespace, the app is served on a \
            public forwarding URL rather than localhost. Make sure the redirect URI listed \
            above (which should already be set for you) is also configured in the Upstox \
            developer console. Otherwise the authorization response will attempt to hit \
            your local machine and fail."
        )


    # if authorization code is present in query params, handle exchange
    # decide up front whether to use the stable or experimental API. we must
    # use the same one for both read and write or Streamlit will complain.
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
            st.success("Access token acquired via OAuth flow")
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
            st.error(f"Token exchange failed: {e}")
            st.write("Details:")
            st.write("  code", code)
            st.write("  redirect_uri", redirect_uri)
            # if requests gave a response body inside the exception, show it
            if hasattr(e, 'args') and e.args:
                st.write("  raw", e.args[0])

    # generate auth url links; provide two flavors in case one triggers
    # the deprecation warning or a 404.
    if api_key and redirect_uri:
        st.write("**Authorization links (make sure redirect URI exactly matches registration!)**")
        # older/legacy link (likely deprecated)
        url1 = UpstoxClient.authorization_url(api_key, redirect_uri, use_v2=False)
        st.markdown(f"- [Legacy link – may be deprecated]({url1})")
        # recommended new URL per documentation
        url2 = UpstoxClient.authorization_url(api_key, redirect_uri, use_v2=True)
        st.markdown(f"- [New v2 login link – preferred]({url2})")
        st.info(
            """
The *new v2 login link* is the one described in the Upstox
documentation. Ensure that your registered redirect URI exactly matches
(including trailing slash and protocol) and that it is URL-encoded by
the application. A mismatch will produce UDAPI100068.
"""
        )
    else:
        st.info("Enter API key and redirect URI to generate authorization links.")

    # manual login button as fallback
    access_token = st.text_input("Access Token (optional)", value=st.session_state.get("access_token", ""), type="password")
    if st.button("Manual Login"):
        if not api_key or not api_secret:
            st.error("API key and secret are required")
        else:
            client = UpstoxClient(api_key, api_secret, access_token or None)
            success, data = client.test_connection()
            if not success:
                st.error(f"Connection failed: {data}")
            else:
                st.success("Credentials valid – you are logged in!")
                st.session_state["api_key"] = api_key
                st.session_state["api_secret"] = api_secret
                st.session_state["access_token"] = access_token
                st.session_state["profile"] = data
                st.session_state["redirect_uri"] = redirect_uri
                safe_rerun()

    # show logged-in info if available
    if "profile" in st.session_state:
        st.markdown("---")
        st.write("**Logged in as:**")
        st.json(st.session_state["profile"])


def main():
    # require login credentials before showing the rest of the app
    if "api_key" not in st.session_state or "api_secret" not in st.session_state:
        login_page()
        return

    st.title("📈 Enhanced Stock Screener with Foundation Candle Scanner")
    st.markdown("---")
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
            st.sidebar.success(f"Loaded {len(symbols)} symbols from uploaded file")
        except Exception as e:
            st.sidebar.error(f"Error reading CSV file: {e}")
            return
    else:
        try:
            if stock_universe == "Nifty 500":
                symbols_df = pd.read_csv('stocks.csv')
                symbols = symbols_df['Symbol'].tolist()
                st.sidebar.info(f"Using default Nifty 500 symbols ({len(symbols)} stocks)")
            else:
                symbols_df = pd.read_csv('NSE_FO_Stocks_NS.csv')
                symbol_col = None
                for col in symbols_df.columns:
                    if col.lower() in ['symbol', 'symbols']:
                        symbol_col = col
                        break
                if symbol_col is None:
                    st.sidebar.error("F&O CSV file must contain a 'Symbol' or 'SYMBOL' column")
                    return
                symbols = symbols_df[symbol_col].tolist()
                st.sidebar.info(f"Using default F&O symbols ({len(symbols)} stocks)")
        except FileNotFoundError:
            st.sidebar.error("Default stocks file not found. Please upload a CSV file.")
            return
        except Exception as e:
            st.sidebar.error(f"Error reading default stocks file: {e}")
            return

    analysis_type = st.sidebar.selectbox(
        "Select Analysis Type",
        ["Current Signals", 
         "Current Signals with Cluster Analysis", 
         "Daily Breakout Tracking", 
         "Both", 
         "Monthly Marubozu Open Scan",
         "1-Hour Foundation Candle Scanner",
         "Upstox Algo"]
    )

    # upstox api credentials page
    if analysis_type == "Upstox Algo":
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🔑 Upstox API Credentials")
        api_key = st.sidebar.text_input("API Key")
        api_secret = st.sidebar.text_input("API Secret", type="password")
        access_token = st.sidebar.text_input("Access Token", type="password")
    else:
        api_key = api_secret = access_token = None

    # Foundation candle specific settings
    if analysis_type == "1-Hour Foundation Candle Scanner":
        st.sidebar.markdown("---")
        st.sidebar.markdown("### ⚙️ Foundation Candle Settings")
        lookback_days = st.sidebar.slider("Lookback Days", min_value=3, max_value=10, value=5, 
                                         help="Number of days to look back for foundation candles")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📧 Email Alert Settings")
    enable_email_alert = st.sidebar.checkbox("Enable Email Alert when price returns to Friday's cluster")
    user_email = None
    if enable_email_alert:
        user_email = st.sidebar.text_input("Enter your Gmail address for alerts", value="sampathskh@gmail.com")
        st.sidebar.info("You will receive an email alert if any stock returns to Friday's cluster.")

    analysis_method = "basic"
    if analysis_type in ["Current Signals with Cluster Analysis", "Both"]:
        analysis_method = "cluster"

    if analysis_method == "cluster" or analysis_type == "1-Hour Foundation Candle Scanner":
        if analysis_type == "1-Hour Foundation Candle Scanner":
            signal_options = [
                "Bullish Foundation Return",
                "Bearish Foundation Return",
                "Strong",
                "Moderate", 
                "Weak"
            ]
            default_signals = ["Bullish Foundation Return", "Bearish Foundation Return"]
        else:
            signal_options = [
                "Bullish Confirmed", 
                "Bearish Confirmed", 
                "Breakout Done but Price Returns Friday's Cluster",
                "Breakdown Done but Price Returns Friday's Cluster",
                "Post-Movement Consolidation",
                "Neutral"
            ]
            default_signals = [
                "Bullish Confirmed", 
                "Bearish Confirmed",
                "Breakout Done but Price Returns Friday's Cluster",
                "Breakdown Done but Price Returns Friday's Cluster"
            ]
    else:
        signal_options = ["Bullish Confirmed", "Bearish Confirmed", "Neutral"]
        default_signals = ["Bullish Confirmed", "Bearish Confirmed", "Neutral"]

    signal_filter = []
    if analysis_type != "Upstox Algo":
        signal_filter = st.sidebar.multiselect(
            "Filter by Signal",
            signal_options,
            default=default_signals
        )

    last_friday = get_last_friday()
    weekdays = get_weekdays_since_friday(last_friday)
    if analysis_type != "Upstox Algo":
        st.info(f"📅 Reference Friday: {last_friday.strftime('%A, %B %d, %Y')} | Trading days since: {len(weekdays)}")
    else:
        st.info("🤖 Upstox algorithmic trading configuration page")
    
    if st.sidebar.button("🚀 Run Analysis", type="primary"):
        # when using Upstox Algo page we don't require stock symbols
        if analysis_type != "Upstox Algo" and not symbols:
            st.error("No symbols to analyze")
            return

        if analysis_type == "Upstox Algo":
            st.subheader("🤖 Upstox Algorithmic Trading")
            st.markdown("""
            This page will integrate with the Upstox Open API to execute
            algorithmic orders based on the signals generated elsewhere in the
            application. Enter your credentials on the sidebar and press
            **Test Connection** to verify.
            """)
            st.write("**API Key:**", api_key or "(not provided)")
            st.write("**API Secret:**", "***" if api_secret else "(not provided)")
            st.write("**Access Token:**", "***" if access_token else "(not provided)")
            # paper mode toggle displayed before connection test
            paper_mode = st.checkbox("Enable paper/demo trading", value=False)
            if st.button("🔗 Test Upstox Connection"):
                if not api_key or not api_secret or not access_token:
                    st.error("Please provide all three credentials before testing.")
                else:
                    client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
                    client = client_cls(api_key, api_secret, access_token)
                    success, data = client.test_connection()
                    if success:
                        st.success("Connection successful!")
                        st.json(data)
                    else:
                        st.error(f"Connection failed: {data}")
            st.markdown("---")
            st.write("### 📝 Place an example order")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                order_symbol = st.text_input("Symbol", value="SBIN")
            with col2:
                order_qty = st.number_input("Quantity", min_value=1, value=1)
            with col3:
                order_side = st.selectbox("Side", ["BUY", "SELL"])
            with col4:
                order_price = st.text_input("Price (limit)")
            if st.button("📨 Send Test Order"):
                if not api_key or not api_secret or not access_token:
                    st.error("Enter credentials first")
                else:
                    client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
                    client = client_cls(api_key, api_secret, access_token)
                    try:
                        price_val = float(order_price) if order_price else None
                        result = client.place_order(
                            symbol=order_symbol,
                            quantity=int(order_qty),
                            transaction_type=order_side,
                            price=price_val,
                        )
                        st.success("Order placed")
                        st.json(result)
                        # store in session for later display
                        if paper_mode:
                            orders = st.session_state.get("paper_orders", [])
                            orders.append(result)
                            st.session_state["paper_orders"] = orders
                    except Exception as ex:
                        st.error(f"Order failed: {ex}")

            # display paper order log if any
            if paper_mode and st.session_state.get("paper_orders"):
                st.markdown("---")
                st.write("### 🗂️ Paper Order Log")
                st.table(pd.DataFrame(st.session_state.get("paper_orders")))

            # strategy execution section
            st.markdown("---")
            st.write("### ⚙️ Execute Strategy")
            if st.button("Run Strategy Using Foundation Candle Returns"):
                if not symbols:
                    st.error("No symbols available for strategy")
                else:
                    client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
                    client = client_cls(api_key, api_secret, access_token)
                    try:
                        strat_df = scan_foundation_candle_returns(symbols)
                        executed = []
                        for _, row in strat_df.iterrows():
                            sym = row['Stock']
                            side = 'BUY' if row.get('Setup Type','').startswith('Bullish') else 'SELL'
                            try:
                                ord = client.place_order(symbol=sym, quantity=1, transaction_type=side)
                                executed.append(ord)
                                if paper_mode:
                                    orders = st.session_state.get("paper_orders", [])
                                    orders.append(ord)
                                    st.session_state["paper_orders"] = orders
                            except Exception as ex:
                                st.error(f"Order for {sym} failed: {ex}")
                        st.write(f"Executed {len(executed)} orders")
                        st.json(executed)
                    except Exception as ex:
                        st.error(f"Strategy error: {ex}")

            # show current positions / orders
            st.markdown("---")
            st.write("### 📁 Account Summary")
            client_cls = PaperUpstoxClient if paper_mode else UpstoxClient
            client = client_cls(api_key, api_secret, access_token)
            try:
                pos = client.get_positions()
                st.write("**Positions**")
                st.json(pos)
            except Exception as e:
                st.warning(f"Could not fetch positions: {e}")

            # token refresh UI
            if st.session_state.get("refresh_token") and not paper_mode:
                if st.button("🔄 Refresh Access Token"):
                    try:
                        token_resp = UpstoxClient.refresh_token(
                            api_key, api_secret, st.session_state["refresh_token"]
                        )
                        st.session_state["access_token"] = token_resp.get("access_token")
                        st.session_state["refresh_token"] = token_resp.get("refresh_token")
                        st.session_state["token_expires_in"] = token_resp.get("expires_in")
                        st.success("Token refreshed")
                    except Exception as e:
                        st.error(f"Refresh failed: {e}")
            try:
                if paper_mode:
                    orders = st.session_state.get("paper_orders", [])
                    if orders:
                        st.write("**Paper order history**")
                        st.json(orders)
                else:
                    ords = client.get_orders()
                    st.write("**Live order history**")
                    st.json(ords)
            except Exception as e:
                st.warning(f"Could not fetch orders: {e}")

            # quick backtest demo using simple daily momentum rule
            st.markdown("---")
            st.write("### 📊 Demo Backtest")
            if st.button("Run Simple Backtest (last 30 days)"):
                # we only backtest symbols if they are available
                bt_symbols = symbols if symbols else [order['symbol'] for order in st.session_state.get('paper_orders', [])]
                df_bt = simple_backtest(bt_symbols)
                if df_bt.empty:
                    st.info("No trades generated during backtest period")
                else:
                    st.dataframe(df_bt)
                    st.metric("Total P&L", df_bt['PnL'].sum())
            return

        if analysis_type == "1-Hour Foundation Candle Scanner":
            st.subheader("🕐 1-Hour Foundation Candle Scanner")
            st.markdown("""
            **Foundation Candle Logic**: 
            - Identifies significant 1-hour candles with large bodies and high volume
            - Detects when current price returns to the foundation candle's body zone
            - Perfect for intraday support/resistance level trading
            """)
            
            with st.expander("🔍 Foundation Candle Criteria"):
                st.markdown("""
                **A 1-hour candle qualifies as a Foundation Candle if:**
                1. **Large Body**: Body size ≥ 60% of total candle range
                2. **Significant Size**: Body in top 80% percentile of recent candles
                3. **High Volume**: Volume ≥ 120% of 20-period average (if available)
                4. **Good Range**: Total range in top 70% percentile
                
                **Foundation Zone**: The body of the foundation candle (between open and close)
                
                **Return Signal**: Current price trades back within the foundation zone (±0.5% tolerance)
                """)
            
            progress_bar = st.progress(0, text="Scanning for foundation candle returns...")
            foundation_results = scan_foundation_candle_returns(symbols, progress_bar)
            progress_bar.empty()
            
            if not foundation_results.empty:
                # Filter results
                if signal_filter:
                    # Filter by setup type or signal strength
                    filtered_df = foundation_results[
                        (foundation_results['Setup Type'].isin([f for f in signal_filter if 'Foundation Return' in f])) |
                        (foundation_results['Signal Strength'].isin(signal_filter))
                    ]
                else:
                    filtered_df = foundation_results
                
                # Search functionality
                search_term = st.text_input("🔍 Search stocks", placeholder="Enter stock symbol or name...")
                if search_term:
                    filtered_df = filtered_df[filtered_df['Stock'].str.contains(search_term.upper(), na=False)]
                
                if not filtered_df.empty:
                    # Display metrics
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Foundation Returns", len(filtered_df))
                    with col2:
                        bullish_count = len(filtered_df[filtered_df['Foundation Type'] == 'Bullish'])
                        st.metric("Bullish Foundations", bullish_count)
                    with col3:
                        bearish_count = len(filtered_df[filtered_df['Foundation Type'] == 'Bearish'])
                        st.metric("Bearish Foundations", bearish_count)
                    with col4:
                        strong_signals = len(filtered_df[filtered_df['Signal Strength'] == 'Strong'])
                        st.metric("Strong Signals", strong_signals)
                    
                    # Display results with styling
                    styled_df = filtered_df.style.map(color_signal, subset=['Setup Type', 'Signal Strength'])
                    st.dataframe(styled_df, use_container_width=True)
                    
                    # Download link
                    filename = f"foundation_candle_returns_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.markdown(create_download_link(filtered_df, filename), unsafe_allow_html=True)
                    
                    # Show some example alerts
                    st.subheader("🚨 Top Foundation Return Opportunities")
                    top_opportunities = filtered_df.nsmallest(5, 'Hours Since Foundation')
                    for _, row in top_opportunities.iterrows():
                        with st.expander(f"🎯 {row['Stock']} - {row['Setup Type']} ({row['Signal Strength']} Signal)"):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"**Foundation Time:** {row['Foundation Time']}")
                                st.write(f"**Current Price:** ₹{row['Current Price']}")
                                st.write(f"**Hours Since Foundation:** {row['Hours Since Foundation']}")
                            with col2:
                                st.write(f"**Foundation Zone:** ₹{row['Zone Bottom']} - ₹{row['Zone Top']}")
                                st.write(f"**Distance from Center:** {row['Distance from Center']}")
                                st.write(f"**Volume Ratio:** {row['Volume Ratio']}x")
                
                else:
                    st.warning("No foundation candle returns found matching your filters.")
            else:
                st.warning("No foundation candle returns detected in the current scan.")
            
            return  # Exit here for foundation candle analysis

        if analysis_type == "Monthly Marubozu Open Scan":
            st.subheader("📊 Monthly Marubozu Open Scan")
            
            # Create tabs for bullish and bearish scans
            tab1, tab2 = st.tabs(["🟢 Bullish Setup (Green Candle)", "🔴 Bearish Setup (Red Candle)"])
            
            with tab1:
                st.markdown("**Bullish Setup**: Stocks where previous month was a Green Marubozu and current price is retracing to previous month's open level")
                progress_bar_bullish = st.progress(0, text="Scanning monthly green candle open...")
                df_green_open = scan_monthly_green_open(symbols)
                progress_bar_bullish.empty()
                
                if not df_green_open.empty:
                    st.dataframe(df_green_open, use_container_width=True)
                    filename_bullish = f"monthly_green_open_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.markdown(create_download_link(df_green_open, filename_bullish), unsafe_allow_html=True)
                else:
                    st.warning("No stocks found where current price is retracing to previous month's green candle open.")
            
            with tab2:
                st.markdown("**Bearish Setup**: Stocks where previous month was a Red Marubozu and current price is rallying to previous month's open level")
                progress_bar_bearish = st.progress(0, text="Scanning monthly red candle open...")
                df_red_open = scan_monthly_red_open(symbols)
                progress_bar_bearish.empty()
                
                if not df_red_open.empty:
                    st.dataframe(df_red_open, use_container_width=True)
                    filename_bearish = f"monthly_red_open_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.markdown(create_download_link(df_red_open, filename_bearish), unsafe_allow_html=True)
                else:
                    st.warning("No stocks found where current price is rallying to previous month's red candle open.")
            
            return  # Exit here since this is a different analysis type

        if analysis_type in ["Current Signals", "Current Signals with Cluster Analysis", "Both"]:
            if analysis_method == "cluster":
                st.subheader("📊 Current Trading Signals with Friday Cluster Analysis")
                st.info("🔍 This analysis detects when stocks return to Friday's first-hour trading cluster after initial breakouts/breakdowns.")
                with st.expander("📋 Signal Meanings"):
                    st.markdown("""
                    **Signal Types:**
                    - **Bullish Confirmed**: Price above Friday's high and staying strong
                    - **Bearish Confirmed**: Price below Friday's low and staying weak  
                    - **Breakout Done but Returns Friday's Cluster**: Stock broke above Friday's high during the week but current price has returned to Friday's first-hour trading range
                    - **Breakdown Done but Returns Friday's Cluster**: Stock broke below Friday's low during the week but current price has returned to Friday's first-hour trading range
                    - **Post-Movement Consolidation**: Had significant movement during week but now consolidating in middle zones
                    - **Neutral**: No significant breakout or breakdown occurred during the week

                    **Friday's Cluster**: Approximated as the first-hour trading range around Friday's opening price, representing the initial price discovery zone.
                    """)
            else:
                st.subheader("📊 Current Trading Signals")

            progress_bar = st.progress(0, text="Initializing...")
            results = fetch_data(symbols, progress_bar, analysis_method)
            progress_bar.empty()
            alert_sent = False
            if enable_email_alert and user_email:
                for res in results:
                    if res.get('Signal') in [
                        "Breakout Done but Price Returns Friday's Cluster",
                        "Breakdown Done but Price Returns Friday's Cluster"
                    ]:
                        send_email_alert(user_email, res['Stock'], res['Signal'], res.get('LTP'), res.get('Friday Cluster High'), res.get('Friday Cluster Low'))
                        alert_sent = True
                if alert_sent:
                    st.success(f"Email alert sent to {user_email} for stocks returning to Friday's cluster.")
                else:
                    st.info("No stocks triggered the alert condition.")

            if results:
                df = pd.DataFrame(results)
                if signal_filter:
                    df = df[df['Signal'].isin(signal_filter)]
                search_term = st.text_input("🔍 Search stocks", placeholder="Enter stock symbol or name...")
                if search_term:
                    df = df[df['Stock'].str.contains(search_term.upper(), na=False)]
                if not df.empty:
                    if analysis_method == "cluster":
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Stocks", len(df))
                        with col2:
                            cluster_return_count = len(df[df['Signal'].str.contains('Returns Friday\'s Cluster', na=False)])
                            st.metric("Cluster Returns", cluster_return_count)
                        with col3:
                            confirmed_count = len(df[df['Signal'].isin(['Bullish Confirmed', 'Bearish Confirmed'])])
                            st.metric("Strong Moves", confirmed_count)
                        col4, col5, col6, col7 = st.columns(4)
                        with col4:
                            bullish_count = len(df[df['Signal'] == 'Bullish Confirmed'])
                            st.metric("Bullish", bullish_count)
                        with col5:
                            bearish_count = len(df[df['Signal'] == 'Bearish Confirmed'])
                            st.metric("Bearish", bearish_count)
                        with col6:
                            breakout_return_count = len(df[df['Signal'] == 'Breakout Done but Price Returns Friday\'s Cluster'])
                            st.metric("Breakout Returns", breakout_return_count)
                        with col7:
                            breakdown_return_count = len(df[df['Signal'] == 'Breakdown Done but Price Returns Friday\'s Cluster'])
                            st.metric("Breakdown Returns", breakdown_return_count)
                    else:
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Total Stocks", len(df))
                        with col2:
                            bullish_count = len(df[df['Signal'] == 'Bullish Confirmed'])
                            st.metric("Bullish Signals", bullish_count)
                        with col3:
                            bearish_count = len(df[df['Signal'] == 'Bearish Confirmed'])
                            st.metric("Bearish Signals", bearish_count)
                        with col4:
                            neutral_count = len(df[df['Signal'] == 'Neutral'])
                            st.metric("Neutral", neutral_count)
                    styled_df = df.style.map(color_signal, subset=['Signal']) \
                                      .map(color_change, subset=['CHNG', '%CHNG'])
                    st.dataframe(styled_df, use_container_width=True)
                    filename = f"friday_breakout_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.markdown(create_download_link(df, filename), unsafe_allow_html=True)
                else:
                    st.warning("No stocks match the current filters")
            else:
                st.error("No data could be fetched. Please check your internet connection and try again.")
        
        if analysis_type in ["Daily Breakout Tracking", "Both"]:
            st.subheader("📈 Daily Breakout Tracking")
            progress_bar = st.progress(0, text="Fetching daily breakout data...")
            daily_results = fetch_daily_breakout_data(symbols, progress_bar)
            progress_bar.empty()
            if daily_results:
                daily_df = pd.DataFrame(daily_results)
                if signal_filter:
                    daily_df = daily_df[daily_df['Current Signal'].isin(signal_filter)]
                search_term_daily = st.text_input("🔍 Search stocks (Daily)", 
                                                placeholder="Enter stock symbol or name...", 
                                                key="daily_search")
                if search_term_daily:
                    daily_df = daily_df[daily_df['Stock'].str.contains(search_term_daily.upper(), na=False)]
                if not daily_df.empty:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        bullish_breakouts = len(daily_df[daily_df['Breakout Type'] == 'Bullish'])
                        st.metric("Bullish Breakouts", bullish_breakouts)
                    with col2:
                        bearish_breakouts = len(daily_df[daily_df['Breakout Type'] == 'Bearish'])
                        st.metric("Bearish Breakouts", bearish_breakouts)
                    with col3:
                        no_breakouts = len(daily_df[daily_df['Breakout Type'] == 'None'])
                        st.metric("No Breakouts", no_breakouts)
                    styled_daily_df = daily_df.style.map(color_signal, subset=['Current Signal'])
                    st.dataframe(styled_daily_df, use_container_width=True)
                    daily_filename = f"daily_breakout_tracking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.markdown(create_download_link(daily_df, daily_filename), unsafe_allow_html=True)
                else:
                    st.warning("No stocks match the current filters for daily tracking")
            else:
                st.error("No daily breakout data could be fetched")
    
    with st.expander("ℹ️ How Friday Breakout Analysis Works"):
        st.markdown("""
        **Friday Breakout Strategy:**
        
        1. **Reference Point**: Every Friday's high and low prices serve as key levels
        2. **Bullish Signal**: When stock price breaks above Friday's high
        3. **Bearish Signal**: When stock price breaks below Friday's low
        4. **Neutral**: Price remains between Friday's high and low
        
        **Signal Types:**
        - 🟢 **Bullish Confirmed**: Current price > Friday High
        - 🔴 **Bearish Confirmed**: Current price < Friday Low  
        - ⚪ **Neutral**: Friday Low ≤ Current price ≤ Friday High
        
        **Daily Tracking**: Shows the exact day when breakout occurred since last Friday
        
        **Monthly Marubozu Open Scan:**
        - **Bullish Setup**: Previous month green marubozu + current price retracing to previous month's open
        - **Bearish Setup**: Previous month red marubozu + current price rallying to previous month's open
        - **Marubozu Criteria**: Body ≥ 75% of total range, minimal wicks (≤ 25% of body each)
        """)

    # Additional info section
    with st.expander("📊 About Monthly Marubozu Open Scan"):
        st.markdown("""
        **What is a Marubozu Candle?**
        - A candlestick pattern with very small or no wicks
        - The body represents most of the price range (≥ 75%)
        - Green Marubozu: Close > Open with minimal wicks
        - Red Marubozu: Open > Close with minimal wicks
        
        **Trading Logic:**
        - **Green Marubozu + Retracement**: Strong monthly bullish momentum followed by a pullback to the monthly open level creates a potential buying opportunity
        - **Red Marubozu + Rally**: Strong monthly bearish momentum followed by a bounce to the monthly open level creates a potential shorting opportunity
        - The monthly open acts as a key support/resistance level
        
        **Scan Parameters:**
        - Tolerance: ±2% from previous month's open price
        - Minimum body size: 75% of total monthly range
        - Maximum wick size: 25% of body size each (upper and lower)
        """)

    # NEW: Foundation Candle explanation
    with st.expander("🕐 About 1-Hour Foundation Candle Scanner"):
        st.markdown("""
        **What is a Foundation Candle?**
        - A significant 1-hour candle that establishes a key support/resistance level
        - Must have a large body (≥60% of total range) indicating strong momentum
        - Should have above-average volume showing institutional participation
        - Acts as a "foundation" for future price action
        
        **Trading Logic:**
        - **Foundation Establishment**: A strong 1-hour candle creates a significant level
        - **Price Return**: When price comes back to the foundation zone, it often provides:
          - **Support** (for bullish foundation candles)
          - **Resistance** (for bearish foundation candles)
        - **Trading Opportunity**: The foundation zone becomes a key level for entry/exit decisions
        
        **Scanner Benefits:**
        - **Intraday Focus**: Perfect for day trading and swing trading setups
        - **High Probability**: Foundation levels often act as strong support/resistance
        - **Time-Sensitive**: Captures opportunities as they develop in real-time
        - **Volume Confirmation**: Includes volume analysis for better signal quality
        
        **How to Use Results:**
        - **Bullish Foundation Return**: Consider long positions with stop below foundation low
        - **Bearish Foundation Return**: Consider short positions with stop above foundation high
        - **Strong Signals**: Price very close to foundation center - highest probability
        - **Recent Foundations**: More relevant (hours since foundation matters)
        """)

if __name__ == "__main__":
    main()