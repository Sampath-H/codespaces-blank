#!/usr/bin/env python3
"""
Example script to demonstrate fetching live OHLC data from Upstox API.
This shows how to use the WebSocket feed for real-time market data.
"""

import time
import threading
from upstox_client import UpstoxClient

def live_data_callback(data):
    """Callback function to handle incoming live OHLC data."""
    for instrument_key, feed in data.items():
        ohlc = feed.get("ohlc", {})
        ltp = feed.get("ltp")
        print(f"Live Data for {instrument_key}:")
        if ohlc:
            print(f"  OHLC: O={ohlc.get('open')} H={ohlc.get('high')} L={ohlc.get('low')} C={ohlc.get('close')}")
        if ltp:
            print(f"  LTP: {ltp}")
        print("---")

def main():
    # Replace with your actual credentials
    API_KEY = "your_api_key_here"
    API_SECRET = "your_api_secret_here"
    ACCESS_TOKEN = "your_access_token_here"

    # Initialize client
    client = UpstoxClient(API_KEY, API_SECRET, ACCESS_TOKEN)

    # Test connection
    success, data = client.test_connection()
    if not success:
        print(f"Connection failed: {data}")
        return

    print("Connected successfully!")

    # Example instrument keys (NSE stocks)
    # You can get instrument keys from Upstox API or use their format
    instruments = [
        "NSE_EQ|INE002A01018",  # Example: RELIANCE
        "NSE_EQ|INE009A01021",  # Example: HDFC
    ]

    # Start live feed
    stop_event = threading.Event()
    client.start_live_feed(instruments, live_data_callback, stop_event)

    print("Live feed started. Press Ctrl+C to stop.")

    try:
        # Keep running for 60 seconds as example
        time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        print("Stopping live feed...")

if __name__ == "__main__":
    main()