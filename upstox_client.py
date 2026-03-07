import requests
from typing import Optional, Tuple, Any


class UpstoxClient:
    """Minimal wrapper around the Upstox Open API.

    This class handles authentication (via access token) and exposes
    a few convenience methods for placing orders and querying account
    information.  The implementation below uses the public REST
    endpoints documented at
    https://upstox.com/developer/api-documentation/open-api.

    Note that Upstox uses API key + secret for initial login flow to
    obtain an access token; once you have the token you simply pass it
    in the `Authorization: Bearer <token>` header for subsequent
    requests.  This wrapper does not implement the OAuth dance; it
    assumes you already have a valid access token from your Upstox
    developer portal or login process.
    """

    # Base URL for live environment using API v2.  The previous v1
    # endpoints have been deprecated and will return a warning message
    # such as "API is deprecated, please migrate to Upstox API v2".
    # See https://upstox.com/developer/api-documentation/ for details.
    BASE_URL = "https://api.upstox.com/v2"  # or sandbox 'https://api.upstox.com/v2' if provided

    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.session = requests.Session()
        # common headers
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        })
        if self.access_token and not getattr(self, '_paper_mode', False):
            self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _url(self, path: str) -> str:
        """Build a full endpoint URL from a path."""
        return f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}"

    @classmethod
    def authorization_url(
        cls,
        api_key: str,
        redirect_uri: str,
        response_type: str = "code",
        use_v2: bool = False,
    ) -> str:
        """Construct the OAuth authorization URL.

        Historically Upstox used ``/index/dialog/oauth`` (unversioned) for the
        login page.  The v2 API tries to migrate toward ``/v2/oauth/authorize``
        or similar, which may be what the server expects now; at the same time
        adding ``/v2`` in front of the old path broke earlier.  We offer both
        options so the user can try the alternative if one of them returns a
        deprecation message.
        """
        # the upstox documentation indicates the correct auth url is
        # /v2/login/authorization/dialog with client_id and response_type.
        # this replaces the earlier guesswork which produced either the
        # deprecated v1 page or a 404.  we retain the old style as a
        # fallback in case the new one is unavailable.
        from urllib.parse import quote_plus

        # ensure redirect URI is percent-encoded exactly as required by the
        # Upstox authorization service; mismatched encoding is a common source
        # of UDAPI100068 errors.
        encoded = quote_plus(redirect_uri)
        if use_v2:
            return (
                f"https://api.upstox.com/v2/login/authorization/dialog?"
                f"response_type={response_type}&client_id={api_key}"
                f"&redirect_uri={encoded}"
            )
        else:
            # legacy unversioned endpoint, may still work for some apps
            return (
                f"https://api.upstox.com/index/dialog/oauth?api_key={api_key}"
                f"&redirect_uri={redirect_uri}&response_type={response_type}"
            )

    @classmethod
    def exchange_code(cls, api_key: str, api_secret: str, code: str, redirect_uri: str) -> Any:
        """Exchange an authorization code for an access token."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": api_key,
            "client_secret": api_secret,
        }
        # correct v2 token endpoint per docs (not /v2/oauth/token)
        resp = requests.post("https://api.upstox.com/v2/login/authorization/token", data=data)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"token exchange failed ({resp.status_code}): {resp.text}"
            ) from exc
        return resp.json()

    @classmethod
    def refresh_token(cls, api_key: str, api_secret: str, refresh_token: str) -> Any:
        """Use a refresh token to obtain a new access token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": api_key,
            "client_secret": api_secret,
        }
        # use the same authorization/token endpoint for refresh
        resp = requests.post("https://api.upstox.com/v2/login/authorization/token", data=data)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"refresh token failed ({resp.status_code}): {resp.text}"
            ) from exc
        return resp.json()

    def test_connection(self) -> Tuple[bool, Any]:
        """Verify that the access token is valid by fetching the user's profile.

        Returns a tuple (success, data_or_error).  On success `data_or_error`
        contains the parsed JSON response from the `/user/profile` endpoint;
        on failure it contains the exception message or response text.
        """
        try:
            # v2 profile endpoint (the v1 path used to be /user/profile)
            resp = self.session.get(self._url("/user/profile"))
            resp.raise_for_status()
            return True, resp.json()
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Example convenience methods
    # ------------------------------------------------------------------
    def get_positions(self) -> Any:
        """Retrieve the current margin positions for the account."""
        # positions endpoint under v2
        resp = self.session.get(self._url("/portfolio/positions"))
        resp.raise_for_status()
        return resp.json()

    def get_market_quote_ohlc(self, instrument_keys: str, interval: str = "1d") -> Any:
        """Fetch Live OHLC quotes for given instrument keys.
        
        Args:
            instrument_keys: Comma-separated list of Upstox instrument keys (e.g., 'NSE_EQ|INE002A01018')
            interval: The interval for OHLC. Valid values: '1d' (default), 'I1' (1-min), 'I30' (30-min).
                      Note: '1d' returns only today's live OHLC.
        """
        if self.access_token == "MOCK_TOKEN_FOR_TESTING":
            # Return realistic fake data for testing without auth
            import random
            
            fake_data = {"status": "success", "data": {}}
            keys = [k.strip() for k in instrument_keys.split(",")]
            for k in keys:
                price = random.uniform(2000, 3000)
                fake_data["data"][k] = {
                    "live_ohlc": {
                        "open": price * random.uniform(0.98, 1.02),
                        "high": price * random.uniform(1.0, 1.05),
                        "low": price * random.uniform(0.95, 0.99),
                        "close": price * random.uniform(0.98, 1.02),
                    },
                    "last_price": price
                }
            return fake_data

        params = {
            "instrument_key": instrument_keys,
            "interval": interval
        }
        resp = self.session.get(self._url("/market-quote/ohlc"), params=params)
        resp.raise_for_status()
        return resp.json()

    def place_order(
        self,
        symbol: str,
        quantity: int,
        transaction_type: str,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        product: str = "MIS",
        **kwargs,
    ) -> Any:
        """Place a new order.

        Parameters mirror the JSON schema described in the Upstox docs.
        Additional keyword arguments are passed through to the request
        body (e.g. "trigger_price" for stop orders).
        """
        payload = {
            "symbol": symbol,
            "quantity": quantity,
            "transaction_type": transaction_type,
            "order_type": order_type,
            "product": product,
        }
        if price is not None:
            payload["price"] = price
        payload.update(kwargs)
        resp = self.session.post(self._url("/orders/place"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> Any:
        """Fetch details for a single order by its ID."""
        resp = self.session.get(self._url(f"/orders/{order_id}"))
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> Any:
        """Cancel an existing order."""
        resp = self.session.post(self._url(f"/orders/{order_id}/cancel"))
        resp.raise_for_status()
        return resp.json()


# --- paper trading support -------------------------------------------------
class PaperUpstoxClient(UpstoxClient):
    """In‑memory client that simulates trading without network calls.

    Intended for demo and backtesting.  The interface matches
    :class:`UpstoxClient` so you can swap them easily in application code.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # avoid adding Authorization header
        self._paper_mode = True
        self.orders = []
        self.next_order_id = 1

    def test_connection(self) -> Tuple[bool, Any]:
        return True, {"mode": "paper"}

    def place_order(
        self,
        symbol: str,
        quantity: int,
        transaction_type: str,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        product: str = "MIS",
        **kwargs,
    ) -> Any:
        order = {
            "order_id": f"PAPER{self.next_order_id}",
            "symbol": symbol,
            "quantity": quantity,
            "transaction_type": transaction_type,
            "order_type": order_type,
            "product": product,
            "price": price,
            "status": "placed",
            **kwargs,
        }
        self.next_order_id += 1
        self.orders.append(order)
        return order

    def get_orders(self) -> Any:
        return list(self.orders)

    def cancel_order(self, order_id: str) -> Any:
        for o in self.orders:
            if o.get("order_id") == order_id:
                o["status"] = "cancelled"
                return o
        raise ValueError("Order not found")
