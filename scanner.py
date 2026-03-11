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

    # ============================================================
    # SIDEBAR: Full scanner configuration (styled like reference UI)
    # ============================================================

    def _load_symbols(df):
        for col in df.columns:
            if col.strip().lower() in ['symbol', 'symbols']:
                return df[col].dropna().tolist()
        return None

    # ── Complete sidebar CSS ──
    st.sidebar.markdown("""
    <style>
    /* ── Sidebar background ── */
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0.5rem !important;
    }

    /* ── Section label headers ── */
    .sc-section {
        font-size: 0.6rem; font-weight: 800; color: #3a5a7a;
        letter-spacing: 0.2em; text-transform: uppercase;
        padding: 1.1rem 0.2rem 0.4rem;
        display: flex; align-items: center; gap: 0.5rem;
    }

    /* ── Universe list item buttons ── */
    .univ-wrap { margin: 2px 0; }
    .univ-wrap button {
        background: transparent !important;
        border: none !important;
        border-radius: 10px !important;
        color: #8099bb !important;
        font-size: 0.92rem !important;
        font-weight: 500 !important;
        padding: 0.62rem 0.9rem !important;
        text-align: left !important;
        width: 100% !important;
        justify-content: flex-start !important;
        transition: background 0.15s, color 0.15s !important;
    }
    .univ-wrap button:hover {
        background: rgba(255,255,255,0.07) !important;
        color: #ddeeff !important;
    }
    .univ-active button {
        background: rgba(30,60,120,0.55) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }

    /* ── Divider ── */
    .sc-divider {
        border: none; border-top: 1px solid rgba(255,255,255,0.06);
        margin: 0.3rem 0;
    }

    /* ── Radio — scanner type ── */
    div[data-testid="stSidebar"] div[data-testid="stRadio"] {
        gap: 0 !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label {
        font-size: 0.91rem !important;
        color: #7a90b5 !important;
        padding: 0.45rem 0.3rem !important;
        cursor: pointer !important;
        transition: color 0.15s !important;
        align-items: center !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
        color: #d0e4ff !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    /* Radio circle */
    div[data-testid="stSidebar"] div[data-testid="stRadio"] [data-baseweb="radio"] > div:first-child {
        border-color: #2d4060 !important;
        background: transparent !important;
        width: 17px !important; height: 17px !important;
        flex-shrink: 0 !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stRadio"] [aria-checked="true"] > div:first-child {
        background: #e05252 !important;
        border-color: #e05252 !important;
    }

    /* ── File uploader ── */
    div[data-testid="stSidebar"] [data-testid="stFileUploader"] section {
        border: 1.5px dashed rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        padding: 0.8rem !important;
        background: rgba(255,255,255,0.02) !important;
    }
    div[data-testid="stSidebar"] [data-testid="stFileUploader"] span {
        font-size: 0.8rem !important;
        color: #7a90b5 !important;
    }
    div[data-testid="stSidebar"] [data-testid="stFileUploader"] small {
        font-size: 0.72rem !important;
        color: #4a6080 !important;
    }

    /* ── Run Analysis button ── */
    div[data-testid="stSidebar"] [data-testid="stButton"]:has(button[kind="primary"]) button {
        background: linear-gradient(135deg,#e53e3e 0%,#c53030 100%) !important;
        border: none !important; color: #fff !important;
        font-size: 1rem !important; font-weight: 800 !important;
        letter-spacing: 0.07em !important; text-transform: uppercase !important;
        border-radius: 12px !important; height: 54px !important;
        box-shadow: 0 4px 22px rgba(229,62,62,0.4) !important;
        transition: box-shadow 0.2s, transform 0.15s !important;
    }
    div[data-testid="stSidebar"] [data-testid="stButton"]:has(button[kind="primary"]) button:hover {
        box-shadow: 0 8px 32px rgba(229,62,62,0.65) !important;
        transform: translateY(-2px) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Init state ──
    if 'scanner_universe' not in st.session_state:
        st.session_state['scanner_universe'] = 'Nifty 500'

    stock_universe = st.session_state['scanner_universe']
    nifty_active   = stock_universe == 'Nifty 500'
    fo_active      = stock_universe == 'F&O Stocks'

    # ── Stock Universe ──
    st.sidebar.markdown('<div class="sc-section">📂 &nbsp;Stock Universe</div>', unsafe_allow_html=True)
    with st.sidebar:
        st.markdown(f'<div class="univ-wrap {("univ-active" if nifty_active else "")}">', unsafe_allow_html=True)
        if st.button("🗃️   Nifty 500", key="btn_nifty", use_container_width=True):
            st.session_state['scanner_universe'] = 'Nifty 500'
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="univ-wrap {("univ-active" if fo_active else "")}">', unsafe_allow_html=True)
        if st.button("📊   F&O Stocks", key="btn_fo", use_container_width=True):
            st.session_state['scanner_universe'] = 'F&O Stocks'
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.sidebar.markdown('<hr class="sc-divider">', unsafe_allow_html=True)

    # ── Configure Scanner ──
    st.sidebar.markdown('<div class="sc-section">🔍 &nbsp;Configure Scanner</div>', unsafe_allow_html=True)
    analysis_type = st.sidebar.radio(
        "Scanner Type",
        ["Current Signals",
         "Current Signals with Cluster Analysis",
         "Daily Breakout Tracking",
         "Monthly Marubozu Open Scan"],
        label_visibility="collapsed",
        key="scanner_type"
    )

    st.sidebar.markdown('<hr class="sc-divider">', unsafe_allow_html=True)

    # ── Data Upload ──
    st.sidebar.markdown('<div class="sc-section">⬆️ &nbsp;Data Upload</div>', unsafe_allow_html=True)
    uploaded_file = st.sidebar.file_uploader(
        "Upload CSV",
        type=['csv'],
        help="CSV with a 'Symbol' column",
        key="scanner_csv",
        label_visibility="collapsed"
    )

    # ── Run Analysis ──
    st.sidebar.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
    run_clicked = st.sidebar.button("🚀  RUN ANALYSIS", type="primary",
                                    use_container_width=True, key="run_analysis_btn")
    if 'last_run_time' in st.session_state:
        st.sidebar.markdown(
            f'<div style="text-align:center;font-size:0.7rem;color:#4a6080;margin-top:0.3rem;">'
            f'Last run: {st.session_state["last_run_time"]}</div>',
            unsafe_allow_html=True
        )

    # ── Info bar (main area) ──
    last_friday = get_last_friday()
    weekdays    = get_weekdays_since_friday(last_friday)
    st.markdown(
        f"""<div style="background:#0d1a2e;border:1px solid rgba(59,130,246,0.2);
        border-radius:10px;padding:0.55rem 1.1rem;margin-bottom:1rem;
        font-size:0.82rem;color:#7a9fc4;display:flex;gap:1.5rem;">
        <span>📅 <b>Friday:</b> {last_friday.strftime('%b %d, %Y')}</span>
        <span>📆 <b>Days since:</b> {len(weekdays)}</span>
        <span>📦 <b>Universe:</b> {stock_universe}</span>
        </div>""",
        unsafe_allow_html=True
    )

    # ---- Load symbols ----
    symbols = []
    if uploaded_file is not None:
        try:
            df_sym = pd.read_csv(uploaded_file)
            syms = _load_symbols(df_sym)
            if syms is None:
                st.error("CSV must have a 'Symbol' column")
                return
            symbols = syms
        except Exception as e:
            st.error(f"Error reading CSV: {e}")
            return
    else:
        try:
            if stock_universe == "Nifty 500":
                df_sym = pd.read_csv("stocks_500.csv")
                syms = _load_symbols(df_sym)
                if syms is None:
                    st.error("stocks_500.csv must have a 'Symbol' column")
                    return
                symbols = syms
            else:
                df_sym = pd.read_csv("NSE_FO_Stocks_NS.csv")
                syms = _load_symbols(df_sym)
                if syms is None:
                    st.error("NSE_FO_Stocks_NS.csv must have a 'Symbol' column")
                    return
                symbols = syms
        except FileNotFoundError as e:
            st.error(f"Stock file not found: {e}")
            return
        except Exception as e:
            st.error(f"Error reading stock file: {e}")
            return

    symbols = [s.strip() + '.NS' if not str(s).strip().endswith('.NS') else str(s).strip()
               for s in symbols if str(s).strip()]

    analysis_method = "basic"
    if analysis_type == "Current Signals with Cluster Analysis":
        analysis_method = "cluster"

    # ---- Run analysis ----
    if run_clicked:
        if not symbols:
            st.error("No symbols to analyze")
            return

        # Reset filter on fresh scan
        st.session_state['scanner_filter'] = 'All'
        st.session_state.pop('scanner_df', None)
        from datetime import datetime as _dt
        st.session_state['last_run_time'] = _dt.now().strftime('%b %d  %H:%M')

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
        if analysis_type in ["Current Signals", "Current Signals with Cluster Analysis"]:
            method = "cluster" if analysis_type == "Current Signals with Cluster Analysis" else "basic"
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
        if analysis_type in ["Daily Breakout Tracking"]:
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
        "Current Signals", "Current Signals with Cluster Analysis"
    ]:
        df              = st.session_state['scanner_df']
        analysis_method = st.session_state.get('scanner_method', 'basic')

        if analysis_method == "cluster":
            st.markdown("""
            <details style="background:#0d1628;border:1px solid rgba(255,255,255,0.08);
            border-radius:10px;padding:0.6rem 1rem;margin-bottom:0.8rem;cursor:pointer;">
            <summary style="color:#8899bb;font-size:0.85rem;font-weight:600;list-style:none;">
            📋 Signal Meanings &nbsp;<span style="font-size:0.7rem;color:#5a7a9a;">(click to expand)</span>
            </summary>
            <div style="margin-top:0.6rem;font-size:0.82rem;color:#a0b4c8;line-height:1.8;">
            <b style="color:#34d399;">Bullish Confirmed</b> — Price above Friday high, staying strong<br>
            <b style="color:#f87171;">Bearish Confirmed</b> — Price below Friday low, staying weak<br>
            <b style="color:#38bdf8;">Breakout Done but Returns</b> — Broke above Friday high, now back in cluster<br>
            <b style="color:#f87171;">Breakdown Done but Returns</b> — Broke below Friday low, now back in cluster<br>
            <b style="color:#fbbf24;">Post-Movement Consolidation</b> — Had big move, now ranging<br>
            <b style="color:#8899bb;">Neutral</b> — No breakout/breakdown yet
            </div></details>
            """, unsafe_allow_html=True)

        # Header + Search
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

            # ─── Tile grid: st.button with nth-child CSS scoped to anchor divs ───
            # Strategy: inject markdown anchor BEFORE st.columns; use
            #   div:has(#anchor) ~ [stHorizontalBlock] [stColumn]:nth-child(N) button
            # to scope color CSS to only our tile rows.

            def tile_css(act, tile_cfg, tile_counts):
                rows_cfg = [
                    [('All','#e2e8f0','#0f172a','#f59e0b'),
                     ('Cluster','#38bdf8','#071828','#38bdf8'),
                     ('Strong','#fbbf24','#130d00','#fbbf24')],
                    [('Bullish','#34d399','#021a0e','#34d399'),
                     ('Bearish','#f87171','#1a0404','#f87171'),
                     ('Breakout','#34d399','#021a0e','#34d399'),
                     ('Breakdown','#f87171','#1a0404','#f87171')],
                ]
                basic_cfg = [
                    [('All','#e2e8f0','#0f172a','#f59e0b'),
                     ('Bullish','#34d399','#021a0e','#34d399'),
                     ('Bearish','#f87171','#1a0404','#f87171')],
                ]

                css = "<style>"
                # Base button style for ALL tile rows (3-col and 4-col)
                css += (
                    "div[data-testid='stHorizontalBlock']:has([class*='tile-row'])"
                    " div[data-testid='stColumn'] button{"
                    "border-radius:16px!important;"
                    "height:115px!important;min-height:115px!important;max-height:115px!important;"
                    "width:100%!important;font-weight:900!important;"
                    "font-size:2.5rem!important;line-height:1.15!important;"
                    "white-space:pre-line!important;"
                    "padding:0.8rem 0.3rem!important;"
                    "letter-spacing:-0.03em!important;"
                    "display:flex!important;flex-direction:column!important;"
                    "align-items:center!important;justify-content:center!important;"
                    "transition:transform 0.15s,box-shadow 0.15s!important;}"
                    "div[data-testid='stHorizontalBlock']:has(.tile-row-1)"
                    " div[data-testid='stColumn'] button{"
                    "font-size:2rem!important;}"
                    "div[data-testid='stHorizontalBlock']:has([class*='tile-row'])"
                    " div[data-testid='stColumn'] button:hover{"
                    "transform:translateY(-4px)!important;}"
                )

                for row_idx, row in enumerate(rows_cfg):
                    for col_idx, (key, num, bg, ba) in enumerate(row):
                        is_act = (act == key)
                        _bg    = '#1e0d00' if is_act else bg
                        _bd    = ba if is_act else 'rgba(255,255,255,0.08)'
                        _glow  = num + '55' if is_act else num + '18'
                        css += (
                            # anchor id = tile-r0 or tile-r1, scoped by row
                            "div[data-testid='stHorizontalBlock']:has(.tile-row-" + str(row_idx) + ")"
                            " div[data-testid='stColumn']:nth-child(" + str(col_idx+1) + ") button{"
                            "background:" + _bg + "!important;"
                            "border:2px solid " + _bd + "!important;"
                            "color:" + num + "!important;"
                            "box-shadow:0 4px 24px " + _glow + "!important;}"
                        )
                # basic mode (1 row only, 3 tiles)
                for col_idx, (key, num, bg, ba) in enumerate(basic_cfg[0]):
                    is_act = (act == key)
                    _bg    = '#1e0d00' if is_act else bg
                    _bd    = ba if is_act else 'rgba(255,255,255,0.08)'
                    _glow  = num + '55' if is_act else num + '18'
                    css += (
                        "div[data-testid='stHorizontalBlock']:has(.tile-row-basic)"
                        " div[data-testid='stColumn']:nth-child(" + str(col_idx+1) + ") button{"
                        "background:" + _bg + "!important;"
                        "border:2px solid " + _bd + "!important;"
                        "color:" + num + "!important;"
                        "box-shadow:0 4px 24px " + _glow + "!important;}"
                    )
                css += "</style>"
                return css

            st.markdown(tile_css(active, TILE_CFG, TILE_COUNTS), unsafe_allow_html=True)

            def render_tile_row(keys, row_class):
                # Inject class marker inside the row so :has() can scope the CSS
                # We put it as the FIRST element inside the first column
                cols = st.columns(len(keys))
                for i, (col, key) in enumerate(zip(cols, keys)):
                    cfg    = TILE_CFG[key]
                    is_act = (active == key)
                    cnt_v  = str(TILE_COUNTS[key])
                    lbl    = cfg['label']
                    arrow  = '\u25b6  ' if is_act else ''
                    btn_lbl = cnt_v + '\n' + arrow + lbl.upper()
                    with col:
                        if i == 0:
                            # Marker span in first col — CSS :has(.tile-row-N) scopes the whole row
                            st.markdown(
                                '<span class="' + row_class + '" style="display:none;"></span>',
                                unsafe_allow_html=True
                            )
                        if st.button(btn_lbl, key='tile_' + key,
                                     use_container_width=True,
                                     help='Filter: ' + lbl):
                            st.session_state['scanner_filter'] = 'All' if is_act else key
                            st.rerun()

            if analysis_method == 'cluster':
                render_tile_row(['All', 'Cluster', 'Strong'], 'tile-row-0')
                st.markdown('<div style="height:0.4rem;"></div>', unsafe_allow_html=True)
                render_tile_row(['Bullish', 'Bearish', 'Breakout', 'Breakdown'], 'tile-row-1')
            else:
                render_tile_row(['All', 'Bullish', 'Bearish'], 'tile-row-basic')

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

    elif analysis_type in ["Current Signals", "Current Signals with Cluster Analysis"]:
        st.info("\U0001f448 Click **Run Analysis** in the sidebar to start scanning.")

    # ── Daily Breakout display ───────────────────────────────────────────────
    if 'scanner_daily_df' in st.session_state and analysis_type in ["Daily Breakout Tracking"]:
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
