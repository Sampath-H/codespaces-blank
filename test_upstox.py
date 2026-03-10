import requests

url = 'https://api.upstox.com/v2/historical-candle/NSE_INDEX|Nifty 50/1minute/2026-03-08/2026-02-08'
headers = {'Accept': 'application/json'}
try:
    response = requests.get(url, headers=headers)
    print("STATUS CODE:", response.status_code)
    print("RESPONSE JSON:", response.json())
except Exception as e:
    print("ERROR:", e)
