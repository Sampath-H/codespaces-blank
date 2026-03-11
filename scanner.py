import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import io
import base64
import os


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def format_price(price):
    """Format a price value for clean display."""
    try:
        price_float = float(price)
        if price_float == int(price_float):
            return str(int(price_float))
        else:
            return f"{price_float:.2f}".rstrip('0').rstrip('.')
    except Exception:
        return str(price)


def color_signal(val):
    """Return CSS style string for a signal value."""
    if val == 'Bullish Confirmed':
        return 'background-color: #d4edda; color: #155724'
    elif val == 'Bearish Confirmed':
        return 'background-color: #f8d7da; color: #721c24'
    elif 'Breakout Done but Price Returns' in str(val):
        return 'background-color: #fff3cd; color: #856404'
    elif 'Breakdown Done but Price Returns' in str(val):
        return 'background-color: #f8d7da; color: #721c24; font-style: italic'
    elif val == 'Post-Movement Consolidation':
        return 'background-color: #cce5ff; color: #004085'
    else:
        return 'background-color: #e2e3e5; color: #383d41'


def color_change(val):
    """Return CSS colour for positive/negative numbers."""
    try:
        val_float = float(val)
        if val_float > 0:
            return 'color: #28a745'
        elif val_float < 0:
            return 'color: #dc3545'
        else:
            return 'color: #6c757d'
    except Exception:
        return ''


def create_download_link(df, filename):
    """Create an HTML download link for a DataFrame as Excel file."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Screener Results')
    excel_data = output.getvalue()
    b64 = base64.b64encode(excel_data).decode()
    href = (
        f'<a href="data:application/vnd.openxmlformats-officedocument'
        f'.spreadsheetml.sheet;base64,{b64}" download="{filename}">'
        f'📥 Download Excel File</a>'
    )
    return href


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

@st.cache_data
def get_last_friday():
    """Calculate the date of the last Friday."""
    today = datetime.now()
    offset = (today.weekday() - 4) % 7
    last_friday = today - timedelta(
        days=offset + 7 if offset == 0 and today.hour < 18 else offset
    )
    return last_friday.date()


def get_weekdays_since_friday(friday_date):
    """Return a list of weekdays since the given Friday up to today."""
    today = datetime.now().date()
    days = []
    current = friday_date + timedelta(days=1)
    while current <= today:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Friday cluster analysis
# ---------------------------------------------------------------------------

def get_friday_first_hour_cluster(symbol, friday_date):
    """Approximate Friday's first-hour cluster zone around the open."""
    try:
        data = yf.download(
            symbol, start=friday_date,
            end=friday_date + timedelta(days=1),
            progress=False, auto_adjust=True,
        )
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
        cluster_high = min(open_price + cluster_range, day_high)
        cluster_low = max(open_price - cluster_range, day_low)
        return cluster_high, cluster_low
    except Exception as e:
        st.warning(f"Error getting Friday cluster for {symbol}: {e}")
        return None, None


def analyze_with_cluster_logic(symbol, data, friday_date, friday_high,
                               friday_low, current_price):
    """Analyse whether a stock has broken out and returned to the cluster."""
    try:
        cluster_high, cluster_low = get_friday_first_hour_cluster(
            symbol, friday_date
        )
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
            day_close = float(day_data.iloc[0]['Close'])
            if day_close > friday_high:
                had_breakout = True
            if day_close < friday_low:
                had_breakdown = True

        current_in_cluster = cluster_low <= current_price <= cluster_high

        if had_breakdown and current_in_cluster:
            return ("Breakdown Done but Price Returns Friday's Cluster",
                    cluster_high, cluster_low)
        elif had_breakout and current_in_cluster:
            return ("Breakout Done but Price Returns Friday's Cluster",
                    cluster_high, cluster_low)
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


# ---------------------------------------------------------------------------
# Scanner functions
# ---------------------------------------------------------------------------

def fetch_data(symbols, progress_bar=None, analysis_type="basic"):
    """Fetch current signals for each symbol (basic or cluster mode)."""
    results = []
    last_friday = get_last_friday()
    start_date = last_friday - timedelta(days=7)
    end_date = datetime.now().date()
    total_symbols = len(symbols)

    for i, symbol in enumerate(symbols):
        try:
            if progress_bar:
                progress_bar.progress(
                    (i + 1) / total_symbols,
                    text=f"Processing {symbol} ({i + 1}/{total_symbols})",
                )
            data = yf.download(
                symbol, start=start_date,
                end=end_date + timedelta(days=1),
                progress=False, auto_adjust=True,
            )
            if data is None or len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            data = data.reset_index()
            data['Date'] = data['Date'].dt.date

            friday_data = data[data['Date'] == last_friday]
            if len(friday_data) == 0:
                continue

            latest_row = data.iloc[-1]
            prev_close = data.iloc[-2]['Close'] if len(data) >= 2 else latest_row['Open']
            latest_close = latest_row['Close']
            chng = latest_close - prev_close
            pct_chng = (chng / prev_close) * 100 if prev_close != 0 else 0
            friday_low = friday_data['Low'].iloc[0]
            friday_high = friday_data['High'].iloc[0]

            result = {
                'Stock': symbol.replace('.NS', ''),
                'Latest Date': latest_row['Date'],
                'Open': format_price(latest_row['Open']),
                'High': format_price(latest_row['High']),
                'Low': format_price(latest_row['Low']),
                'Prev. Close': format_price(prev_close),
                'LTP': format_price(latest_close),
                'CHNG': format_price(chng),
                '%CHNG': format_price(pct_chng),
                'Friday High': format_price(friday_high),
                'Friday Low': format_price(friday_low),
            }

            if analysis_type == "cluster":
                signal, cluster_high, cluster_low = analyze_with_cluster_logic(
                    symbol, data, last_friday, friday_high, friday_low,
                    latest_close,
                )
                result['Signal'] = signal
                result['Friday Cluster High'] = (
                    format_price(cluster_high) if cluster_high else 'N/A'
                )
                result['Friday Cluster Low'] = (
                    format_price(cluster_low) if cluster_low else 'N/A'
                )
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


def fetch_daily_breakout_data(symbols, progress_bar=None):
    """Track day-by-day breakout history since last Friday."""
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
                progress_bar.progress(
                    (i + 1) / total_symbols,
                    text=f"Processing daily data for {symbol} ({i + 1}/{total_symbols})",
                )
            data = yf.download(
                symbol, start=start_date,
                end=end_date + timedelta(days=1),
                progress=False, auto_adjust=True,
            )
            if data is None or len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            data = data.reset_index()
            data['Date'] = data['Date'].dt.date

            friday_data = data[data['Date'] == last_friday]
            if len(friday_data) == 0:
                continue

            friday_low = friday_data['Low'].iloc[0]
            friday_high = friday_data['High'].iloc[0]

            breakout_day = None
            breakout_type = None
            for day in weekdays:
                day_data = data[data['Date'] == day]
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

            latest_close = data.iloc[-1]['Close']
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
                'Breakout Day': (breakout_day.strftime('%A, %b %d')
                                 if breakout_day else 'No Breakout'),
                'Breakout Type': breakout_type if breakout_type else 'None',
                'Current Price': format_price(latest_close),
                'Current Signal': current_signal,
                'Days Since Friday': len(weekdays) if weekdays else 0,
            })
        except Exception as e:
            st.warning(f"Error fetching daily data for {symbol}: {e}")
            continue
    return daily_results


# ---------------------------------------------------------------------------
# Monthly Marubozu scanners
# ---------------------------------------------------------------------------

def scan_monthly_green_open(symbols):
    """Scan for bullish Marubozu retracement to previous month's open."""
    results = []
    for symbol in symbols:
        try:
            data = yf.download(
                symbol, period="4mo", interval="1mo",
                auto_adjust=True, progress=False,
            )
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
            upper_wick_pct = (upper_wick / body_size) * 100 if body_size > 0 else 0
            lower_wick_pct = (lower_wick / body_size) * 100 if body_size > 0 else 0
            is_green_marubozu = (
                prev_close > prev_open
                and body_percentage >= 75
                and upper_wick_pct <= 25
                and lower_wick_pct <= 25
            )
            if not is_green_marubozu:
                continue
            current_data = yf.download(
                symbol, period="5d", interval="1d",
                auto_adjust=True, progress=False,
            )
            if current_data.empty:
                continue
            current_price = float(current_data['Close'].iloc[-1])
            tolerance_pct = 2.0
            tolerance_range = prev_open * (tolerance_pct / 100)
            if prev_open - tolerance_range <= current_price <= prev_open + tolerance_range:
                retracement = ((prev_close - current_price) / (prev_close - prev_open)) * 100
                distance = ((current_price - prev_open) / prev_open) * 100
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Prev Month': prev_month.name.strftime('%b %Y'),
                    'Prev Month Open': round(prev_open, 2),
                    'Prev Month High': round(prev_high, 2),
                    'Prev Month Low': round(prev_low, 2),
                    'Prev Month Close': round(prev_close, 2),
                    'Body %': round(body_percentage, 1),
                    'Current Price': round(current_price, 2),
                    'Distance from Prev Open': f"{distance:+.1f}%",
                    'Retracement %': round(retracement, 1),
                    'Setup Type': 'Bullish Retracement',
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)


def scan_monthly_red_open(symbols):
    """Scan for bearish Marubozu rally to previous month's open."""
    results = []
    for symbol in symbols:
        try:
            data = yf.download(
                symbol, period="4mo", interval="1mo",
                auto_adjust=True, progress=False,
            )
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
            upper_wick_pct = (upper_wick / body_size) * 100 if body_size > 0 else 0
            lower_wick_pct = (lower_wick / body_size) * 100 if body_size > 0 else 0
            is_red_marubozu = (
                prev_open > prev_close
                and body_percentage >= 75
                and upper_wick_pct <= 25
                and lower_wick_pct <= 25
            )
            if not is_red_marubozu:
                continue
            current_data = yf.download(
                symbol, period="5d", interval="1d",
                auto_adjust=True, progress=False,
            )
            if current_data.empty:
                continue
            current_price = float(current_data['Close'].iloc[-1])
            tolerance_pct = 2.0
            tolerance_range = prev_open * (tolerance_pct / 100)
            if prev_open - tolerance_range <= current_price <= prev_open + tolerance_range:
                rally = ((current_price - prev_close) / (prev_open - prev_close)) * 100
                distance = ((current_price - prev_open) / prev_open) * 100
                results.append({
                    'Stock': symbol.replace('.NS', ''),
                    'Prev Month': prev_month.name.strftime('%b %Y'),
                    'Prev Month Open': round(prev_open, 2),
                    'Prev Month High': round(prev_high, 2),
                    'Prev Month Low': round(prev_low, 2),
                    'Prev Month Close': round(prev_close, 2),
                    'Body %': round(body_percentage, 1),
                    'Current Price': round(current_price, 2),
                    'Distance from Prev Open': f"{distance:+.1f}%",
                    'Rally %': round(rally, 1),
                    'Setup Type': 'Bearish Retracement',
                })
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Scanner page UI
# ---------------------------------------------------------------------------

def display_scanner_page():
    """Main scanner page UI — full-featured port from trade.py."""

    # ── Handle tile-click filter via query params ──────────────────────────
    qp = st.query_params
    if 'sf' in qp:
        val = qp['sf']
        if val == 'All':
            st.session_state['scanner_filter'] = 'All'
        else:
            st.session_state['scanner_filter'] = val
        st.query_params.clear()
        st.rerun()

    # ---- Sidebar: Stock Universe ----
    st.sidebar.markdown("""
    <div style="font-size:0.65rem;font-weight:700;color:#f59e0b;
         letter-spacing:0.15em;text-transform:uppercase;margin-bottom:0.6rem;">
    ⚙️ Configuration
    </div>
    """, unsafe_allow_html=True)
    st.sidebar.markdown("### 📂 Stock Universe")
    stock_universe = st.sidebar.radio(
        "Select Stock Universe",
        ["Nifty 500", "F&O Stocks"],
        index=0,
    )

    uploaded_file = st.sidebar.file_uploader(
        "Upload CSV file with stock symbols",
        type=['csv'],
        help="Upload a CSV file with a 'Symbol' column containing stock symbols",
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
                symbols_df = pd.read_csv("stocks_500.csv")
                symbols = symbols_df['Symbol'].tolist()
                st.sidebar.info(f"Using Nifty 500 ({len(symbols)} stocks)")
            else:
                symbols_df = pd.read_csv("NSE_FO_Stocks_NS.csv")
                symbol_col = None
                for col in symbols_df.columns:
                    if col.lower() in ['symbol', 'symbols']:
                        symbol_col = col
                        break
                if symbol_col is None:
                    st.sidebar.error("F&O CSV must contain a 'Symbol' or 'SYMBOL' column")
                    return
                symbols = symbols_df[symbol_col].tolist()
                st.sidebar.info(f"Using F&O Stocks ({len(symbols)} stocks)")
        except FileNotFoundError:
            st.sidebar.error("Default stocks file not found. Please upload a CSV file.")
            return
        except Exception as e:
            st.sidebar.error(f"Error reading default stocks file: {e}")
            return

    # Add .NS suffix if not present
    symbols = [s + '.NS' if not s.endswith('.NS') else s for s in symbols]

    # ---- Sidebar: Analysis Type ----
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔍 Scanner Type")
    analysis_type = st.sidebar.radio(
        "Choose Scanner",
        [
            "Current Signals",
            "Current Signals with Cluster Analysis",
            "Daily Breakout Tracking",
            "Both",
            "Monthly Marubozu Open Scan",
        ],
        label_visibility="collapsed",
    )

    analysis_method = "basic"
    if analysis_type in ["Current Signals with Cluster Analysis", "Both"]:
        analysis_method = "cluster"

    # ---- Info bar ----
    last_friday = get_last_friday()
    weekdays = get_weekdays_since_friday(last_friday)
    st.info(
        f"📅 Reference Friday: {last_friday.strftime('%A, %B %d, %Y')} "
        f"| Trading days since: {len(weekdays)}"
    )

    # ---- Run analysis button ----
    # Only scan when the button is pressed — save results to session_state
    if st.sidebar.button("\U0001f680 Run Analysis", type="primary"):
        if not symbols:
            st.error("No symbols to analyze")
            return

        # Reset filter on fresh scan
        st.session_state['scanner_filter'] = 'All'
        st.session_state.pop('scanner_df', None)

        # ===== Monthly Marubozu Open Scan =====
        if analysis_type == "Monthly Marubozu Open Scan":
            st.subheader("\U0001f4ca Monthly Marubozu Open Scan")
            tab1, tab2 = st.tabs(["\U0001f7e2 Bullish Setup (Green Candle)", "\U0001f534 Bearish Setup (Red Candle)"])
            with tab1:
                progress_bar = st.progress(0, text="Scanning monthly green candle open...")
                df_green = scan_monthly_green_open(symbols)
                progress_bar.empty()
                if not df_green.empty:
                    st.dataframe(df_green, use_container_width=True)
                    st.markdown(create_download_link(df_green, f"monthly_green_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"), unsafe_allow_html=True)
                else:
                    st.warning("No stocks found retracing to green candle open.")
            with tab2:
                progress_bar = st.progress(0, text="Scanning monthly red candle open...")
                df_red = scan_monthly_red_open(symbols)
                progress_bar.empty()
                if not df_red.empty:
                    st.dataframe(df_red, use_container_width=True)
                    st.markdown(create_download_link(df_red, f"monthly_red_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"), unsafe_allow_html=True)
                else:
                    st.warning("No stocks found rallying to red candle open.")
            return

        # ===== Current Signals scan (save to session_state) =====
        if analysis_type in ["Current Signals", "Current Signals with Cluster Analysis", "Both"]:
            method = "cluster" if analysis_type in ["Current Signals with Cluster Analysis", "Both"] else "basic"
            progress_bar = st.progress(0, text="Scanning...")
            results = fetch_data(symbols, progress_bar, method)
            progress_bar.empty()
            if results:
                st.session_state['scanner_df']     = pd.DataFrame(results)
                st.session_state['scanner_method'] = method
            else:
                st.warning("No data found for the selected symbols.")
                return

        # ===== Daily Breakout scan (save to session_state) =====
        if analysis_type in ["Daily Breakout Tracking", "Both"]:
            progress_bar = st.progress(0, text="Tracking daily breakouts...")
            daily_results = fetch_daily_breakout_data(symbols, progress_bar)
            progress_bar.empty()
            if daily_results:
                st.session_state['scanner_daily_df'] = pd.DataFrame(daily_results)
            else:
                st.session_state.pop('scanner_daily_df', None)

    # ===========================================================================
    # DISPLAY SECTION — runs on EVERY rerun (scan OR filter click OR page load)
    # This is intentionally OUTSIDE the button block so filter clicks work!
    # ===========================================================================

    # ── Current Signals display ──────────────────────────────────────────────
    if 'scanner_df' in st.session_state and analysis_type in [
        "Current Signals", "Current Signals with Cluster Analysis", "Both"
    ]:
        df              = st.session_state['scanner_df']
        analysis_method = st.session_state.get('scanner_method', 'basic')

        if analysis_method == "cluster":
            with st.expander("\U0001f4cb Signal Meanings"):
                st.markdown("""
- **Bullish Confirmed**: Price above Friday high, staying strong
- **Bearish Confirmed**: Price below Friday low, staying weak
- **Breakout Done but Returns**: Broke out above Friday high, now back in cluster
- **Breakdown Done but Returns**: Broke down below Friday low, now back in cluster
- **Post-Movement Consolidation**: Had big move, now ranging
- **Neutral**: No breakout/breakdown yet
                """)

        # Header + Search
        st.markdown("""
        <div style="background:linear-gradient(135deg,#0a1628 0%,#0f2040 100%);
             border-radius:14px;padding:1.5rem 1.8rem;margin-bottom:1.2rem;
             border:1px solid rgba(255,255,255,0.07);
             box-shadow:0 4px 24px rgba(0,0,0,0.4);">
          <div style="font-size:1.5rem;font-weight:800;color:#fff;margin-bottom:0.2rem;">
            📊 Stock Scanner
          </div>
          <div style="color:#8899bb;font-size:0.85rem;">
            Friday cluster analysis &amp; signal detection
          </div>
        </div>
        """, unsafe_allow_html=True)
        search_term = st.text_input("", placeholder="🔍  Search by stock symbol...", key="scanner_search",
                                    label_visibility="collapsed")
        df_search   = df[df['Stock'].str.contains(search_term.upper(), na=False)] if search_term else df

        if df_search.empty:
            st.warning("No stocks matched the search.")
        else:
            if 'scanner_filter' not in st.session_state:
                st.session_state['scanner_filter'] = 'All'

            # ── Counts ──────────────────────────────────────────────────────
            cnt_total    = len(df_search)
            cnt_bullish  = len(df_search[df_search['Signal'] == 'Bullish Confirmed'])
            cnt_bearish  = len(df_search[df_search['Signal'] == 'Bearish Confirmed'])
            if analysis_method == 'cluster':
                cnt_cluster   = len(df_search[df_search['Signal'].str.contains("Returns Friday", na=False)])
                cnt_strong    = len(df_search[df_search['Signal'].isin(['Bullish Confirmed','Bearish Confirmed'])])
                cnt_breakout  = len(df_search[df_search['Signal'].str.contains('Breakout Done', na=False)])
                cnt_breakdown = len(df_search[df_search['Signal'].str.contains('Breakdown Done', na=False)])

            # ── Colour map ──────────────────────────────────────────────────
            NUM_COLORS = {
                'All':       ('#ffffff', '#1a1a2e'),
                'Cluster':   ('#3b82f6', '#0a1628'),
                'Strong':    ('#f59e0b', '#1a1200'),
                'Bullish':   ('#10b981', '#002d1a'),
                'Bearish':   ('#ef4444', '#2d0000'),
                'Breakout':  ('#10b981', '#002d1a'),
                'Breakdown': ('#ef4444', '#2d0000'),
            }

            # -- Tile grid: HTML visual + invisible st.button overlay --
            active = st.session_state.get('scanner_filter', 'All')

            TILE_CFG = {
                'All':       {'num': '#e2e8f0', 'bg': '#0f172a', 'ba': '#f59e0b', 'label': 'Total Stocks'},
                'Cluster':   {'num': '#38bdf8', 'bg': '#071828', 'ba': '#38bdf8', 'label': 'Cluster Returns'},
                'Strong':    {'num': '#fbbf24', 'bg': '#130d00', 'ba': '#fbbf24', 'label': 'Strong Moves'},
                'Bullish':   {'num': '#34d399', 'bg': '#021a0e', 'ba': '#34d399', 'label': 'Bullish'},
                'Bearish':   {'num': '#f87171', 'bg': '#1a0404', 'ba': '#f87171', 'label': 'Bearish'},
                'Breakout':  {'num': '#34d399', 'bg': '#021a0e', 'ba': '#34d399', 'label': 'Breakout Returns'},
                'Breakdown': {'num': '#f87171', 'bg': '#1a0404', 'ba': '#f87171', 'label': 'Breakdown Returns'},
            }
            TILE_COUNTS = {
                'All':       cnt_total,
                'Cluster':   cnt_cluster   if analysis_method == 'cluster' else 0,
                'Strong':    cnt_strong    if analysis_method == 'cluster' else 0,
                'Bullish':   cnt_bullish,
                'Bearish':   cnt_bearish,
                'Breakout':  cnt_breakout  if analysis_method == 'cluster' else 0,
                'Breakdown': cnt_breakdown if analysis_method == 'cluster' else 0,
            }

            # ── CSS: hide the button div entirely, JS onclick on tile triggers it ──
            st.markdown(
                "<style>"
                # Collapse the stButton wrapper + button inside tile columns
                "div[data-testid='stVerticalBlock']:has([data-stile])"
                " div[data-testid='stButton']{height:0!important;min-height:0!important;"
                "overflow:hidden!important;margin:0!important;padding:0!important;}"
                "div[data-testid='stVerticalBlock']:has([data-stile])"
                " div[data-testid='stButton'] button{display:none!important;}"
                "</style>",
                unsafe_allow_html=True
            )

            def render_tile_row(keys):
                cols = st.columns(len(keys))
                for col, key in zip(cols, keys):
                    cfg    = TILE_CFG[key]
                    is_act = (active == key)
                    num    = cfg['num']
                    bg     = '#1e0d00' if is_act else cfg['bg']
                    border = cfg['ba']  if is_act else 'rgba(255,255,255,0.08)'
                    glow   = num + '50' if is_act else num + '18'
                    arrow  = '\u25b6 '  if is_act else ''
                    cnt_v  = str(TILE_COUNTS[key])
                    lbl    = cfg['label'].upper()
                    # JS: traverse up to stVerticalBlock, find the button, click it
                    js = ("var vb=this.closest('[data-testid=\"stVerticalBlock\"]');"
                          "if(vb){var b=vb.querySelector('button');if(b)b.click();}")
                    visual = (
                        '<div data-stile="' + key + '" onclick="' + js + '" style="'
                        'background:' + bg + ';border:2px solid ' + border + ';'
                        'border-radius:16px;height:115px;'
                        'padding:1.3rem 0.5rem 0;text-align:center;'
                        'box-shadow:0 4px 28px ' + glow + ';'
                        'position:relative;overflow:hidden;cursor:pointer;">'
                        '<div style="position:absolute;top:-32px;left:50%;transform:translateX(-50%);'
                        'width:80%;height:64px;pointer-events:none;'
                        'background:radial-gradient(ellipse,' + num + '1a 0%,transparent 70%);"></div>'
                        '<div style="font-size:2.6rem;font-weight:900;color:' + num + ';'
                        'line-height:1;letter-spacing:-0.04em;'
                        'font-family:Consolas,monospace;">' + cnt_v + '</div>'
                        '<div style="font-size:0.62rem;color:rgba(255,255,255,0.4);'
                        'text-transform:uppercase;letter-spacing:0.13em;'
                        'margin-top:0.38rem;font-weight:700;">' + arrow + lbl + '</div>'
                        '</div>'
                    )
                    with col:
                        st.markdown(visual, unsafe_allow_html=True)
                        # Hidden button (zero height via CSS above) - clicked by JS onclick
                        if st.button('\u200b', key='tile_' + key,
                                     use_container_width=True):
                            st.session_state['scanner_filter'] = 'All' if is_act else key
                            st.rerun()

            if analysis_method == 'cluster':
                render_tile_row(['All', 'Cluster', 'Strong'])
                st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
                render_tile_row(['Bullish', 'Bearish', 'Breakout', 'Breakdown'])
            else:
                render_tile_row(['All', 'Bullish', 'Bearish'])

            st.markdown(
                '<div style="margin:0.8rem 0 0.4rem;'
                'border-top:1px solid rgba(255,255,255,0.06);"></div>',
                unsafe_allow_html=True
            )

            active = st.session_state.get('scanner_filter', 'All')
            FILTER_MAP = {
                'All':       df_search,
                'Bullish':   df_search[df_search['Signal'] == 'Bullish Confirmed'],
                'Bearish':   df_search[df_search['Signal'] == 'Bearish Confirmed'],
                'Cluster':   df_search[df_search['Signal'].str.contains("Returns Friday", na=False)],
                'Strong':    df_search[df_search['Signal'].isin(['Bullish Confirmed','Bearish Confirmed'])],
                'Breakout':  df_search[df_search['Signal'].str.contains('Breakout Done', na=False)],
                'Breakdown': df_search[df_search['Signal'].str.contains('Breakdown Done', na=False)],
            }
            df_filtered = FILTER_MAP.get(active, df_search)

            # ── Active filter banner + Back button ───────────────────────
            if active != 'All':
                num_col_active = TILE_CFG.get(active, {}).get('num', '#f59e0b')
                count_active   = len(df_filtered)
                bb1, bb2 = st.columns([4, 1])
                with bb1:
                    st.markdown(
                        '<div style="background:linear-gradient(135deg,#1c1000,#0d0a00);'
                        'border:1.5px solid #f59e0b;border-radius:14px;'
                        'padding:0.7rem 1.4rem;margin:0.3rem 0 0.6rem;">'
                        '<div style="color:#777;font-size:0.6rem;letter-spacing:0.15em;'
                        'text-transform:uppercase;font-weight:700;">Filtered View</div>'
                        '<div style="margin-top:0.15rem;">'
                        '<span style="color:' + num_col_active + ';font-size:1.3rem;font-weight:900;">'
                        + active + '</span>'
                        '<span style="color:#999;font-size:0.88rem;"> — </span>'
                        '<span style="color:#fff;font-size:1.05rem;font-weight:700;">' + str(count_active) + '</span>'
                        '<span style="color:#777;font-size:0.8rem;"> stocks</span>'
                        '</div></div>',
                        unsafe_allow_html=True
                    )
                with bb2:
                    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
                    if st.button('← All Results', key='back_to_all', use_container_width=True):
                        st.session_state['scanner_filter'] = 'All'
                        st.rerun()

            # ── Styled table ─────────────────────────────────────────────
            styled_df = df_filtered.style.map(color_signal, subset=['Signal'])
            if '%CHNG' in df_filtered.columns:
                styled_df = styled_df.map(color_change, subset=['%CHNG', 'CHNG'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            filename = f"screener_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.markdown(create_download_link(df_filtered, filename), unsafe_allow_html=True)

    elif analysis_type in ["Current Signals", "Current Signals with Cluster Analysis", "Both"]:
        st.info("\U0001f448 Click **Run Analysis** in the sidebar to start scanning.")

    # ── Daily Breakout display ───────────────────────────────────────────────
    if 'scanner_daily_df' in st.session_state and analysis_type in ["Daily Breakout Tracking", "Both"]:
        st.markdown("---")
        st.subheader("\U0001f4c8 Daily Breakout Tracking")
        df_daily = st.session_state['scanner_daily_df']
        if not df_daily.empty:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Stocks",      len(df_daily))
            col2.metric("Bullish Breakouts", len(df_daily[df_daily['Breakout Type'] == 'Bullish']))
            col3.metric("Bearish Breakdowns",len(df_daily[df_daily['Breakout Type'] == 'Bearish']))
            col4.metric("No Breakout",       len(df_daily[df_daily['Breakout Type'] == 'None']))
            st.dataframe(df_daily.style.map(color_signal, subset=['Current Signal']), use_container_width=True)
            st.markdown(create_download_link(df_daily, f"daily_breakout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"), unsafe_allow_html=True)
        else:
            st.warning("No daily breakout data found.")
