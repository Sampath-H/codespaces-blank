import requests

def test_api(instrument):
    url = f'https://api.upstox.com/v2/historical-candle/{instrument}/1minute/2026-03-08/2026-03-06'
    headers = {'Accept': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        print(f"\n--- {instrument} ---")
        print("STATUS CODE:", response.status_code)
        data = response.json()
        print("STATUS:", data.get('status'))
        if data.get('status') == 'error':
            print("ERRORS:", data.get('errors'))
        else:
            candles = data.get('data', {}).get('candles', [])
            print(f"CANDLES RETURNED: {len(candles)}")
            if candles:
                print("FIRST CANDLE:", candles[0])
    except Exception as e:
        print("ERROR:", e)

test_api("NSE_INDEX|Nifty 50")
test_api("NSE_EQ|RELIANCE")
test_api("NSE_EQ|SBIN")
test_api("NSE_EQ|TCS")
