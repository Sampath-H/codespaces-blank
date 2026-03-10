import requests
from urllib.parse import quote
from typing import Optional, Tuple, Any


class UpstoxClient:
    """Minimal wrapper around the Upstox Open API."""

    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        })
        if self.access_token and not getattr(self, '_paper_mode', False):
            self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _url(self, path: str) -> str:
        return f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _encode_key(instrument_key: str) -> str:
        """URL-encode instrument key so NSE_INDEX|Nifty 50 works in URL paths."""
        return quote(instrument_key, safe='')

    @classmethod
    def authorization_url(cls, api_key, redirect_uri, response_type="code", use_v2=False):
        from urllib.parse import quote_plus
        encoded = quote_plus(redirect_uri)
        if use_v2:
            return (
                f"https://api.upstox.com/v2/login/authorization/dialog?"
                f"response_type={response_type}&client_id={api_key}"
                f"&redirect_uri={encoded}"
            )
        return (
            f"https://api.upstox.com/index/dialog/oauth?api_key={api_key}"
            f"&redirect_uri={redirect_uri}&response_type={response_type}"
        )

    @classmethod
    def exchange_code(cls, api_key, api_secret, code, redirect_uri):
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": api_key,
            "client_secret": api_secret,
        }
        resp = requests.post("https://api.upstox.com/v2/login/authorization/token", data=data)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"token exchange failed ({resp.status_code}): {resp.text}") from exc
        return resp.json()

    @classmethod
    def refresh_token(cls, api_key, api_secret, refresh_token):
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": api_key,
            "client_secret": api_secret,
        }
        resp = requests.post("https://api.upstox.com/v2/login/authorization/token", data=data)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"refresh token failed ({resp.status_code}): {resp.text}") from exc
        return resp.json()

    def test_connection(self):
        try:
            resp = self.session.get(self._url("/user/profile"))
            resp.raise_for_status()
            return True, resp.json()
        except Exception as exc:
            return False, str(exc)

    def get_positions(self):
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            return []
        resp = self.session.get(self._url("/portfolio/positions"))
        resp.raise_for_status()
        return resp.json()

    def get_market_quote_ohlc(self, instrument_keys: str, interval: str = "1d"):
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            import yfinance as yf
            fake_data = {"status": "success", "data": {}}
            keys = [k.strip() for k in instrument_keys.split(",")]
            for k in keys:
                try:
                    yf_symbol = k if k.endswith('.NS') else f"{k}.NS"
                    ticker = yf.Ticker(yf_symbol)
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        last_price = float(hist['Close'].iloc[-1])
                        open_price = float(hist['Open'].iloc[-1])
                        high = float(hist['High'].iloc[-1])
                        low = float(hist['Low'].iloc[-1])
                    else:
                        last_price = open_price = 1000.0
                        high = 1010.0
                        low = 990.0
                except Exception:
                    last_price = open_price = 1000.0
                    high = 1010.0
                    low = 990.0
                fake_data["data"][k] = {
                    "live_ohlc": {"open": round(open_price, 2), "high": round(high, 2),
                                  "low": round(low, 2), "close": round(last_price, 2)},
                    "last_price": round(last_price, 2)
                }
            return fake_data

        params = {"instrument_key": instrument_keys, "interval": interval}
        resp = self.session.get(self._url("/market-quote/ohlc"), params=params)
        resp.raise_for_status()
        return resp.json()

    def get_historical_candle(self, instrument_key: str, interval: str, to_date: str, from_date: str):
        """
        Fetch historical candle data. Chunks into 25-day windows for intraday.
        FIXED: URL-encodes instrument key (NSE_INDEX|Nifty 50 works now).
        FIXED: Falls back to yfinance when using MOCK token.
        """
        from datetime import datetime, timedelta

        # MOCK fallback via yfinance
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            return self._yfinance_historical(instrument_key, interval, from_date, to_date)

        t_d = datetime.strptime(to_date, "%Y-%m-%d")
        f_d = datetime.strptime(from_date, "%Y-%m-%d")

        all_candles = []
        current_to = t_d

        while current_to >= f_d:
            current_from = max(current_to - timedelta(days=25), f_d)

            # FIXED: URL-encode so | and spaces don't corrupt the URL
            encoded_key = self._encode_key(instrument_key)
            url = self._url(
                f"/historical-candle/{encoded_key}/{interval}"
                f"/{current_to.strftime('%Y-%m-%d')}/{current_from.strftime('%Y-%m-%d')}"
            )

            resp = self.session.get(url)
            try:
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success" and data.get("data", {}).get("candles"):
                    all_candles.extend(data["data"]["candles"])
            except requests.HTTPError as e:
                print(f"Historical API Error for {current_from} to {current_to}: {resp.text}")

            if current_from == f_d:
                break
            current_to = current_from - timedelta(days=1)

        return {"status": "success", "data": {"candles": all_candles}}

    def get_live_intraday(self, instrument_key: str, interval: str) -> Optional[dict]:
        """
        Fetch today's live intraday candles.
        FIXED: URL-encodes instrument key.
        """
        unit = "minute"
        interv = "1"
        if interval == "1minute":    interv = "1"
        elif interval == "5minute":  interv = "5"
        elif interval == "15minute": interv = "15"
        elif interval == "30minute": interv = "30"
        elif interval == "1hour":    interv = "1"; unit = "hour"
        elif interval == "day":      interv = "1"; unit = "day"

        # FIXED: URL-encode instrument key
        encoded_key = self._encode_key(instrument_key)
        url = self._url(f"/historical-candle/intraday/{encoded_key}/{unit}/{interv}")
        resp = self.session.get(url)
        try:
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            print(f"Intraday API Error: {resp.text}")
            return {"status": "error", "data": {"candles": []}}

    @staticmethod
    def _yfinance_historical(instrument_key: str, interval: str, from_date: str, to_date: str) -> dict:
        """Fallback: fetch historical OHLCV from yfinance when using MOCK token."""
        import yfinance as yf
        import pandas as pd
        from datetime import datetime, timedelta

        KEY_MAP = {
            "NSE_INDEX|Nifty 50":        "^NSEI",
            "NSE_INDEX|Nifty Bank":      "^NSEBANK",
            "BSE_INDEX|SENSEX":          "^BSESN",
            "NSE_INDEX|NIFTY MIDCAP 50": "^NSEMDCP50",
        }

        if instrument_key in KEY_MAP:
            yf_symbol = KEY_MAP[instrument_key]
        elif "NSE_EQ|" in instrument_key or "NSE_FO|" in instrument_key:
            yf_symbol = instrument_key.split("|")[-1] + ".NS"
        else:
            yf_symbol = instrument_key + ".NS"

        INTERVAL_MAP = {
            "1minute":  "1m",
            "5minute":  "5m",
            "15minute": "15m",
            "30minute": "30m",
            "1hour":    "1h",
            "day":      "1d",
            "week":     "1wk",
            "month":    "1mo",
        }
        yf_interval = INTERVAL_MAP.get(interval, "5m")

        try:
            # yfinance only keeps 60 days of 1m data, 730 days of daily
            df = yf.download(
                yf_symbol,
                start=from_date,
                end=to_date,
                interval=yf_interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                return {"status": "success", "data": {"candles": []}}

            df = df.reset_index()
            candles = []
            for _, row in df.iterrows():
                ts = row.get("Datetime", row.get("Date", None))
                if ts is None:
                    continue
                if not isinstance(ts, pd.Timestamp):
                    ts = pd.Timestamp(ts)
                candles.append([
                    ts.isoformat(),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row.get("Volume", 0)),
                    0,
                ])
            candles.reverse()  # newest first, matches Upstox API
            return {"status": "success", "data": {"candles": candles}}

        except Exception as e:
            print(f"[yfinance fallback] Error fetching {yf_symbol}: {e}")
            return {"status": "success", "data": {"candles": []}}

    def resolve_options_contract(self, underlying, spot_price, trade_date,
                                  expiry_type="Weekly", option_type="CE", strike_offset=0):
        import pandas as pd
        try:
            csv_url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
            master_df = pd.read_csv(csv_url, compression='gzip')
        except Exception as e:
            print(f"Failed to fetch Upstox Master Instruments: {e}")
            return None

        fo_df = master_df[
            (master_df['instrument_type'] == 'OPTIDX') & (master_df['name'] == underlying)
        ].copy()
        if fo_df.empty:
            return None

        step_size = 50 if underlying == "NIFTY" else 100
        atm_strike = round(spot_price / step_size) * step_size
        target_strike = atm_strike + (strike_offset * step_size)

        matching = fo_df[
            (fo_df['strike'] == target_strike) & (fo_df['option_type'] == option_type)
        ].copy()
        if matching.empty:
            return None

        matching['expiry_date'] = pd.to_datetime(matching['expiry'])
        future = matching[matching['expiry_date'].dt.date >= trade_date.date()].copy()
        if future.empty:
            return None

        future = future.sort_values('expiry_date')
        if expiry_type == "Monthly":
            month_opts = future[future['expiry_date'].dt.month == trade_date.month]
            selected = month_opts.iloc[-1] if not month_opts.empty else future.iloc[0]
        else:
            selected = future.iloc[0]

        return {
            "instrument_token": selected['instrument_key'],
            "lot_size": int(selected['lot_size']),
            "trading_symbol": selected['tradingsymbol']
        }

    def place_order(self, symbol, quantity, transaction_type,
                    price=None, order_type="LIMIT", product="MIS", **kwargs):
        payload = {
            "symbol": symbol, "quantity": quantity,
            "transaction_type": transaction_type,
            "order_type": order_type, "product": product,
        }
        if price is not None:
            payload["price"] = price
        payload.update(kwargs)
        resp = self.session.post(self._url("/orders/place"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_orders(self):
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            return [{"order_id": "MOCK123", "symbol": "TCS", "quantity": 5,
                     "transaction_type": "BUY", "status": "complete"}]
        resp = self.session.get(self._url("/orders"))
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id):
        resp = self.session.get(self._url(f"/orders/{order_id}"))
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id):
        resp = self.session.post(self._url(f"/orders/{order_id}/cancel"))
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# PaperUpstoxClient
# ---------------------------------------------------------------------------
class PaperUpstoxClient(UpstoxClient):
    """
    Paper-trading wrapper.

    FIXED BUGS:
      1. Now sets Authorization header for real (non-MOCK) tokens so that
         get_historical_candle / get_live_intraday hit the real Upstox API.
      2. get_live_intraday now calls real API (or yfinance fallback) instead
         of returning empty candles.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paper_mode = True

        # FIXED: Set auth header when a real token is provided
        # (super().__init__ skips it because _paper_mode wasn't set yet)
        if self.access_token and self.access_token != "MOCK_TOKEN_FOR_TESTING":
            self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

        self.orders = []
        self.next_order_id = 1

    def test_connection(self) -> Tuple[bool, Any]:
        return True, {"mode": "paper"}

    def place_order(self, symbol, quantity, transaction_type,
                    price=None, order_type="LIMIT", product="MIS", **kwargs):
        if order_type == "MARKET" and price is None:
            import yfinance as yf
            try:
                yf_symbol = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
                ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="1d")
                price = round(float(hist['Close'].iloc[-1]), 2) if not hist.empty else 1000.0
            except Exception:
                price = 1000.0

        order = {
            "order_id": f"PAPER{self.next_order_id}",
            "symbol": symbol, "quantity": quantity,
            "transaction_type": transaction_type,
            "order_type": order_type, "product": product,
            "price": price, "status": "placed",
            **kwargs,
        }
        self.next_order_id += 1
        self.orders.append(order)
        return order

    def get_orders(self):
        return list(self.orders)

    def get_live_intraday(self, instrument_key: str, interval: str) -> Optional[dict]:
        """
        FIXED: Actually fetches live intraday data.
        - Real token  → calls Upstox API (via parent class)
        - MOCK token  → yfinance fallback
        """
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            return self._yfinance_intraday(instrument_key, interval)
        # Real token: use parent implementation (auth header is now set)
        return super().get_live_intraday(instrument_key, interval)

    @staticmethod
    def _yfinance_intraday(instrument_key: str, interval: str) -> dict:
        """yfinance fallback for today's intraday data when using MOCK token."""
        import yfinance as yf
        import pandas as pd
        import pytz
        from datetime import datetime, timedelta, time as dtime

        KEY_MAP = {
            "NSE_INDEX|Nifty 50":   "^NSEI",
            "NSE_INDEX|Nifty Bank": "^NSEBANK",
            "BSE_INDEX|SENSEX":     "^BSESN",
        }
        if instrument_key in KEY_MAP:
            yf_symbol = KEY_MAP[instrument_key]
        else:
            yf_symbol = instrument_key.split("|")[-1] + ".NS"

        INTERVAL_MAP = {
            "1minute":  "1m",
            "5minute":  "5m",
            "15minute": "15m",
            "30minute": "30m",
            "1hour":    "60m",
            "day":      "1d",
        }
        yf_interval = INTERVAL_MAP.get(interval, "5m")

        try:
            IST = pytz.timezone("Asia/Kolkata")
            today_str    = datetime.now(IST).strftime("%Y-%m-%d")
            tomorrow_str = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")

            df = yf.download(
                yf_symbol,
                start=today_str,
                end=tomorrow_str,
                interval=yf_interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                return {"status": "success", "data": {"candles": []}}

            df = df.reset_index()
            candles = []
            for _, row in df.iterrows():
                ts = row.get("Datetime", row.get("Date", None))
                if ts is None:
                    continue
                if not isinstance(ts, pd.Timestamp):
                    ts = pd.Timestamp(ts)
                ts_ist = ts.tz_convert(IST) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(IST)
                # Filter to market hours 09:15–15:30 IST
                if not (dtime(9, 15) <= ts_ist.time() <= dtime(15, 30)):
                    continue
                candles.append([
                    ts.isoformat(),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row.get("Volume", 0)),
                    0,
                ])
            candles.reverse()  # newest first
            return {"status": "success", "data": {"candles": candles}}

        except Exception as e:
            print(f"[yfinance intraday] Error for {yf_symbol}: {e}")
            return {"status": "success", "data": {"candles": []}}

    def cancel_order(self, order_id):
        for o in self.orders:
            if o.get("order_id") == order_id:
                o["status"] = "cancelled"
                return o
        raise ValueError("Order not found")

    @classmethod
    def get_equity_instrument_token(cls, symbol: str) -> Optional[str]:
        import pandas as pd
        clean_symbol = symbol.replace('.NS', '').strip().upper()
        try:
            csv_url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
            master_df = pd.read_csv(csv_url, compression='gzip')
            eq_df = master_df[
                (master_df['instrument_type'] == 'EQUITY') &
                (master_df['tradingsymbol'] == clean_symbol)
            ]
            return eq_df.iloc[0]['instrument_key'] if not eq_df.empty else None
        except Exception as e:
            print(f"Failed to fetch Upstox Master Instruments: {e}")
            return None
