# Kalshi Market Making Bot

A sophisticated market making bot for Kalshi prediction markets that provides two-sided liquidity, captures bid-ask spreads, and manages inventory risk.

## 🎯 Project Status

**Phase 1: Complete ✅**
- Authenticated API connection
- Market data retrieval
- Full orderbook depth (with SDK bug workaround)
- Order management
- Portfolio tracking

**Coming Next:**
- Phase 2: Order Book Processing
- Phase 3: Fee Economics
- Phase 4: Quote Generation
- Phase 5: Flow Detection & Toxic Flow Protection
- Phase 6: Execution Engine
- Phase 7: Configuration & Deployment

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd kalshiproject

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Set up your API credentials
# 1. Get your API key ID and private key from Kalshi
# 2. Save private key to kalshidemo.txt (for demo) or zachdaube.txt (for production)
# 3. Copy config example
cp config/config.example.yaml config/config.yaml

# 4. Edit config.yaml with your API key ID
# WARNING: Never commit your API keys!
```

### 3. Run Phase 1 Test

```bash
python phase1_test.py
```

Expected output:
```
✓ Loaded private key
✓ Client initialized
✓ Found 10 open markets
✓ Order book retrieved
✓ Account balance: $98.00
```

## 📁 Project Structure

```
kalshiproject/
├── src/
│   ├── __init__.py
│   └── client.py           # Kalshi API wrapper
├── config/
│   ├── README.md
│   └── config.example.yaml # Configuration template
├── docs/
│   ├── PHASE1_SUMMARY.md   # Phase 1 detailed explanation
│   └── ORDERBOOK_FIX.md    # Technical writeup of SDK bug fix
├── tests/
│   └── (test files)
├── .gitignore              # Protects API keys
├── requirements.txt        # Python dependencies
├── phase1_test.py          # Phase 1 demonstration
└── README.md               # This file
```

## 🔑 Key Features

### Phase 1: API Foundation

- **RSA Key Authentication**: Secure cryptographic authentication with Kalshi
- **Market Data**: Fetch markets, orderbooks, trades, and portfolio data
- **Order Management**: Place, cancel, and track orders
- **SDK Bug Workaround**: Bypasses validation errors to get full orderbook depth

### Understanding Kalshi's Order Book

Kalshi only returns **bids** for YES and NO. A NO bid at price X is equivalent to a YES ask at (100 - X).

**Example:**
```python
orderbook = {
  "yes": [[48, 307]],  # Someone will pay 48¢ for YES
  "no": [[51, 873]]    # Someone will pay 51¢ for NO
}

# Convert to traditional view:
best_yes_bid = 48¢
best_yes_ask = 100 - 51 = 49¢  # Implied from NO bid
spread = 1¢
```

## 🛡️ Security

### API Key Protection

Your API keys are **never committed** to the repository:

```gitignore
# .gitignore includes:
*.pem
*demo.txt
zachdaube.txt
kalshidemo.txt
*.key
credentials.yaml
.env
```

### Demo vs Production

| Environment | Host | Purpose |
|------------|------|---------|
| **Demo** | `demo-api.kalshi.co` | Safe testing, virtual money |
| **Production** | `api.elections.kalshi.com` | Real trading, real money |

**Always test on demo first!**

## 📚 Documentation

- **[Phase 1 Summary](docs/PHASE1_SUMMARY.md)**: Detailed explanation of authentication, orderbooks, and API usage
- **[Orderbook Fix](docs/ORDERBOOK_FIX.md)**: Technical details on the SDK bug and our workaround
- **[Config Guide](config/README.md)**: How to set up your configuration

## 🔧 Development

### API Client (src/client.py)

```python
from src.client import KalshiClient

# Initialize
client = KalshiClient(
    key_id="your-key-id",
    private_key=open('kalshidemo.txt').read(),
    host="https://demo-api.kalshi.co/trade-api/v2"
)

# Get markets
markets = client.get_markets(status="open", limit=10)

# Get orderbook (full depth)
orderbook = client.get_orderbook("TICKER", depth=10)

# Place order
order = client.place_order(
    ticker="TICKER",
    side="yes",
    action="buy",
    quantity=10,
    price=45
)
```

### Running Tests

```bash
# Phase 1 test (current)
python phase1_test.py

# Unit tests (coming in later phases)
pytest tests/
```

## 🎓 Learning Resources

### How Market Making Works

1. **Post two-sided quotes**: Bid below fair value, ask above
2. **Capture the spread**: Profit from the difference
3. **Manage inventory**: Don't accumulate too much directional risk
4. **Avoid toxic flow**: Don't get picked off by informed traders

### Kalshi-Specific Concepts

- **Binary markets**: YES/NO outcomes, prices from 0¢ to 100¢
- **NO bid = YES ask**: Understanding the complementary nature
- **Fee structure**: Maker fees (0.0175 × C × P × (1-P)), taker fees 4x higher
- **Settlement**: Markets resolve to 0¢ or 100¢ based on outcome

## ⚠️ Risk Warnings

- **Start small**: Test with minimal position sizes
- **Use demo first**: Never go straight to production
- **Set limits**: Max position, max loss per session
- **Monitor closely**: Market making can lose money if not managed
- **Understand fees**: They eat into your profits

## 🐛 Known Issues

### kalshi_python_sync SDK Bug

The official SDK has a validation bug in the orderbook endpoint. Our client bypasses this with raw HTTP requests. See [ORDERBOOK_FIX.md](docs/ORDERBOOK_FIX.md) for details.

## 📈 Roadmap

- [x] Phase 1: API Foundation
- [ ] Phase 2: Order Book Processing
- [ ] Phase 3: Fee Economics
- [ ] Phase 4: Quote Generation
- [ ] Phase 5: Flow Detection
- [ ] Phase 6: Execution Engine
- [ ] Phase 7: Configuration & Deployment

## 🤝 Contributing

This is a personal project for learning market making. Feel free to fork and experiment!

## 📄 License

MIT License - Use at your own risk

## ⚖️ Disclaimer

This software is for educational purposes. Market making involves financial risk. The authors assume no liability for financial losses. Always trade responsibly and never risk more than you can afford to lose.

---

**Built with:**
- Python 3.12+
- kalshi_python_sync SDK
- Love for prediction markets 📊
