import os
import requests
import json

api_key = os.environ.get("UPSTOX_API_KEY")
api_secret = os.environ.get("UPSTOX_API_SECRET")
# The access token is needed, if I don't have it, I might get 401. But let me write a script that can read it from a file or prints how to get it.
# Actually, I can't easily get the access token without user login.
# Wait, I am just writing the script to see what it requires.

print("To test OHLC, we need an access token.")
