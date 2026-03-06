# Stock Trading Platform

A comprehensive algorithmic trading platform with stock scanning and automated trading capabilities.

## Features

- **Stock Scanner**: Scan for foundation candle patterns, Friday breakouts, and monthly Marubozu setups
- **Algo Trading**: Automated order execution with paper trading mode
- **OAuth Integration**: Secure login with Upstox API v2
- **Real-time Data**: Live market data from Yahoo Finance
- **Paper Trading**: Risk-free strategy testing

## Project Structure

```
├── main.py              # Main application entry point
├── scanner.py           # Stock scanning module
├── algo_trading.py      # Algorithmic trading module
├── upstox_client.py     # Upstox API client
├── trade.py             # Legacy single-file version
├── email_alert.py       # Email notification system
├── stocks_500.csv       # Nifty 500 stock list
├── NSE_FO_Stocks_NS.csv # F&O eligible stocks
└── __pycache__/         # Python cache
```

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install streamlit yfinance pandas openpyxl requests
   ```

## Usage

### Running the Application

```bash
streamlit run main.py
```

### For Codespaces

If running in GitHub Codespaces, update your Upstox app's redirect URI to:
```
https://<your-codespace-name>-8501.app.github.dev/
```

### Navigation

1. **Login**: Enter your Upstox API credentials
2. **Dashboard**: Overview of activity and statistics
3. **Stock Scanner**: Scan for trading setups
4. **Algo Trading**: Execute automated strategies

## Configuration

### Environment Variables

Set these for automatic credential loading:

```bash
export UPSTOX_API_KEY="your-api-key"
export UPSTOX_API_SECRET="your-api-secret"
```

### Preset Credentials

Edit the constants in `main.py`:

```python
PRESET_API_KEY = "your-api-key"
PRESET_API_SECRET = "your-api-secret"
```

## Trading Strategies

### Foundation Candle Returns
- Identifies strong 1-hour candles with high volume
- Triggers when price returns to the foundation zone

### Friday Breakout
- Monitors Friday's high/low levels
- Triggers on breakouts in the following week

### Monthly Marubozu
- Scans for strong monthly candles
- Triggers on retracements or rallies

## Safety Features

- **Paper Trading Mode**: Test strategies without real money
- **Manual Order Review**: All automated orders can be reviewed
- **Connection Testing**: Verify API connectivity before trading

## API Documentation

### UpstoxClient

```python
from upstox_client import UpstoxClient, PaperUpstoxClient

# Real trading
client = UpstoxClient(api_key, api_secret, access_token)

# Paper trading
client = PaperUpstoxClient(api_key, api_secret, access_token)

# Place order
result = client.place_order(
    symbol="SBIN.NS",
    quantity=1,
    transaction_type="BUY",
    price=None  # Market order
)
```

### Scanner Functions

```python
from scanner import scan_foundation_candle_returns

# Scan for setups
setups = scan_foundation_candle_returns(symbols_list)
```

## Troubleshooting

### OAuth Issues
- Ensure redirect URI matches exactly in Upstox console
- For Codespaces, use the forwarded URL with https
- Check that API key/secret are correct

### Connection Problems
- Test connection in the Algo Trading tab
- Verify internet connectivity
- Check Upstox API status

### Data Issues
- Ensure CSV files are in the correct format
- Check symbol suffixes (.NS for NSE)
- Verify Yahoo Finance data availability

## Development

### Adding New Strategies

1. Add scanning logic to `scanner.py`
2. Update the strategy selection in `algo_trading.py`
3. Test with paper trading mode

### Custom Scanners

Extend the `Scanner` class in `scanner.py`:

```python
def custom_scan(symbols):
    # Your scanning logic here
    return pd.DataFrame(results)
```

## License

This project is for educational purposes. Use at your own risk.