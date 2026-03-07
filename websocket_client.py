import streamlit as st
import threading
import time
from typing import List, Dict, Callable
import logging

try:
    import upstox_client
    from upstox_client.rest import ApiException
    from upstox_client.market_data_streamer_v3 import MarketDataStreamerV3
    import upstox_client.MarketDataFeed_pb2 as pb
    HAS_UPSTOX_SDK = True
except ImportError:
    HAS_UPSTOX_SDK = False


# Setup basic logging for the streamer
logger = logging.getLogger("upstox_streamer")
logger.setLevel(logging.INFO)

class UpstoxStreamerManager:
    """
    Manages the Upstox WebSocket Streamer in a background thread.
    This prevents the Streamlit UI from blocking while listening to the socket.
    Results are pushed directly into st.session_state so the UI can read them.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UpstoxStreamerManager, cls).__new__(cls)
            cls._instance.streamer = None
            cls._instance.thread = None
            cls._instance.is_running = False
            cls._instance.subscriptions = set()
            cls._instance.on_tick_callback = None
            
            # Store live data globally in the instance to survive Streamlit reruns
            cls._instance.live_data = {}  
        return cls._instance

    def initialize(self, api_key: str, access_token: str):
        if self.is_running and self.streamer:
            return  # Already running

        # --- MOCK MODE HANDLING ---
        if access_token == "MOCK_TOKEN_FOR_TESTING":
            st.session_state["streamer_status"] = "Connected (Mock) 🟢"
            self.is_running = True
            
            def mock_stream():
                import random
                while self.is_running:
                    try:
                        time.sleep(1)
                        if not self.subscriptions:
                            continue
                            
                        # Pick a random subscribed instrument and generate a fake tick
                        inst = random.choice(list(self.subscriptions))
                        inst_name = inst.split('|')[-1]
                        
                        # Get previous or initial price
                        last_tick = self.live_data.get(inst_name)
                        if last_tick:
                            price = last_tick['ltp'] * random.uniform(0.998, 1.002)
                        else:
                            # Fetch real price from yfinance only once
                            import yfinance as yf
                            yf_symbol = inst_name if inst_name.endswith('.NS') else f"{inst_name}.NS"
                            try:
                                ticker = yf.Ticker(yf_symbol)
                                hist = ticker.history(period="1d")
                                if not hist.empty:
                                    price = float(hist['Close'].iloc[-1])
                                else:
                                    price = random.uniform(1000, 3000)
                            except:
                                price = random.uniform(1000, 3000)
                            
                        tick = {
                            'instrument': inst_name,
                            'ltp': round(price, 2),
                            'close': round(price * 0.99, 2),
                            'timestamp': time.time()
                        }
                        
                        self.live_data[inst_name] = tick
                        
                        if self.on_tick_callback:
                            self.on_tick_callback(tick)
                            
                    except Exception as e:
                        logger.error(f"Mock thread error: {e}")
                        
            self.streamer = "MOCK_STREAMER"
            self.thread = threading.Thread(target=mock_stream, daemon=True)
            self.thread.start()
            return
        # --------------------------

        if not HAS_UPSTOX_SDK:
            raise ImportError("upstox-python-sdk is not installed. Please add it to requirements.txt")

        configuration = upstox_client.Configuration()
        configuration.access_token = access_token

        # Define streamer callbacks
        def on_open():
            st.session_state["streamer_status"] = "Connected 🟢"
            logger.info("Streamer connected")
            if self.subscriptions:
                # Resubscribe upon reconnect
                self.streamer.subscribe(list(self.subscriptions), "ltpc")

        def on_close(message):
            st.session_state["streamer_status"] = "Disconnected 🔴"
            logger.info(f"Streamer disconnected: {message}")

        def on_error(error):
            st.session_state["streamer_status"] = "Error ⚠️"
            logger.error(f"Streamer error: {error}")

        def on_message(message):
            """Decode the incoming protobuf message and update state."""
            try:
                # The upstream SDK returns a byte string which we decode using Protobuf
                feed_response = pb.FeedResponse()
                feed_response.ParseFromString(message)
                
                # Parse all feeds
                for instrument_key, feed in feed_response.feeds.items():
                    if feed.HasField('ltpc'):
                        tick = {
                            'instrument': instrument_key.split('|')[-1], # E.g. RELIANCE
                            'ltp': feed.ltpc.ltp,
                            'ltt': feed.ltpc.ltt,
                            'close': feed.ltpc.cp,
                            'timestamp': time.time()
                        }
                    elif feed.HasField('ff'): # Full feed
                        tick = {
                            'instrument': instrument_key.split('|')[-1],
                            'ltp': feed.ff.marketFF.ltpc.ltp,
                            'volume': feed.ff.marketFF.eFeedDetails.v,
                            'timestamp': time.time()
                        }
                    else:
                        continue
                        
                    # Update internal live cache
                    self.live_data[tick['instrument']] = tick
                    
                    # Fire custom callback if defined (useful for strategy execution)
                    if self.on_tick_callback:
                        self.on_tick_callback(tick)
                        
            except Exception as e:
                logger.error(f"Message parse error: {e}")

        self.streamer = MarketDataStreamerV3(
            upstox_client.ApiClient(configuration), 
            list(self.subscriptions) if self.subscriptions else [], 
            "ltpc"
        )
        
        self.streamer.on("open", on_open)
        self.streamer.on("close", on_close)
        self.streamer.on("error", on_error)
        self.streamer.on("message", on_message)
        
        # Start in background thread
        self.is_running = True
        st.session_state["streamer_status"] = "Connecting... ⏳"
        
        def run_stream():
            self.streamer.connect()
            
        self.thread = threading.Thread(target=run_stream, daemon=True)
        self.thread.start()

    def subscribe(self, instrument_keys: List[str], mode: str = "ltpc"):
        """Subscribe to new instruments."""
        new_subs = set(instrument_keys) - self.subscriptions
        self.subscriptions.update(instrument_keys)
        
        if self.is_running and self.streamer and self.streamer != "MOCK_STREAMER":
            if new_subs:
                self.streamer.subscribe(list(new_subs), mode)

    def unsubscribe(self, instrument_keys: List[str]):
        if self.is_running and self.streamer and self.streamer != "MOCK_STREAMER":
            self.streamer.unsubscribe(instrument_keys)
        # remove from set
        for key in instrument_keys:
            if key in self.subscriptions:
                self.subscriptions.remove(key)

    def stop(self):
        if self.streamer and self.streamer != "MOCK_STREAMER":
            self.streamer.disconnect()
        self.is_running = False
        self.streamer = None
        self.thread = None
        st.session_state["streamer_status"] = "Disconnected 🔴"

    def get_live_data(self) -> Dict:
        """Returns the current cache of live ticks."""
        return self.live_data

    def set_callback(self, callback: Callable):
        """Set a function to be called on every tick (useful for strategies)."""
        self.on_tick_callback = callback
