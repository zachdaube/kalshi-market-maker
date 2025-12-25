# Kalshi Market Making Bot

A sophisticated market making bot for Kalshi prediction markets that provides two-sided liquidity, captures bid-ask spreads, and manages inventory risk.

## 🎯 Project Status

**Phase 1: Complete ✅** - API Foundation
- Authenticated API connection via RSA keys
- Market data retrieval and filtering
- Full orderbook depth (with SDK bug workaround)
- Order management (place, cancel, track)
- Portfolio tracking and balance queries

**Phase 2: Complete ✅** - Order Book Processing
- NO bid → YES ask conversion (100 - X formula)
- Best bid/ask, mid price, spread calculations
- VWAP (Volume-Weighted Average Price) analysis
- Depth analysis and cumulative liquidity tracking
- Edge case handling (empty, crossed, one-sided markets)

**Phase 3: Complete ✅** - Fee Economics
- Maker (1.75%) and taker (7.00%) fee calculations
- Profitability analysis (gross → net P&L)
- Minimum spread requirements (2¢ to break even)
- Market evaluation logic (should_quote_market)
- ROI and per-contract profit metrics

**Coming Next:**
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

### 3. Run Tests

```bash
# Phase 1: API connection and basic functionality
python phase1_test.py

# Phase 2: Order book processing and analysis
python phase2_test.py

# Phase 3: Fee calculations and profitability
python phase3_test.py

# Run all unit tests
pytest tests/ -v
```

Expected output (Phase 3):
```
✓ Fee calculations working with real data
✓ Profitability analysis functional
✓ Market evaluation logic implemented
✓ Maker fees significantly lower than taker fees
```

## 📁 Project Structure

```
kalshiproject/
├── src/                    # Core modules
│   ├── __init__.py
│   ├── client.py           # Kalshi API wrapper (371 lines)
│   ├── orderbook.py        # Order book processing (290 lines)
│   └── fees.py             # Fee calculations & profitability (580 lines)
│
├── tests/                  # Unit tests (53 tests, all passing)
│   ├── test_orderbook.py   # Order book tests (18 tests)
│   └── test_fees.py        # Fee calculation tests (35 tests)
│
├── docs/                   # Documentation
│   ├── PHASE1_SUMMARY.md   # API Foundation
│   ├── PHASE2_SUMMARY.md   # Order Book Processing
│   ├── PHASE3_SUMMARY.md   # Fee Economics
│   ├── KALSHI_MECHANICS.md # How Kalshi markets work
│   ├── ORDERBOOK_FIX.md    # SDK bug workaround
│   ├── API_DECISIONS.md    # REST vs WebSocket, sync vs async
│   └── GIT_SETUP.md        # Repository setup
│
├── config/
│   ├── README.md
│   └── config.example.yaml
│
├── phase1_test.py          # API & orderbook demo
├── phase2_test.py          # Order book processing demo
├── phase3_test.py          # Fee economics demo
├── test_order_placement.py # Real order placement test
├── place_demo_orders.py    # Place live orders (no cancel)
│
├── .gitignore              # Protects API keys
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

**Lines of Code**: ~1,650 (src/) + ~850 (tests/) = 2,500+ lines

## 🔑 Key Features

### Phase 1: API Foundation

- **RSA Key Authentication**: Secure cryptographic authentication with Kalshi
- **Market Data**: Fetch markets, orderbooks, trades, and portfolio data
- **Order Management**: Place, cancel, and track orders
- **SDK Bug Workaround**: Bypasses validation errors to get full orderbook depth

### Phase 2: Order Book Processing

- **NO → YES Conversion**: Automatically converts NO bids to YES asks using `100 - X` formula
- **Market Metrics**: Best bid/ask, mid price, spread, cumulative depth
- **VWAP Analysis**: Calculate average execution price for large orders
- **Edge Cases**: Handles empty, one-sided, and crossed markets
- **Pretty Printing**: Formatted orderbook display for analysis

### Phase 3: Fee Economics

- **Fee Calculations**: Maker (1.75%) vs Taker (7.00%) fees
- **Profitability**: Full P&L analysis including fees, ROI, per-contract profit
- **Spread Requirements**: Calculate minimum spread to break even or hit target profit
- **Market Evaluation**: Automated decision whether to quote a market
- **Critical Insight**: 2¢ spread profitable as maker, but unprofitable as taker!

### Understanding Kalshi's Order Book

Kalshi only returns **bids** for YES and NO. A NO bid at price X is equivalent to a YES ask at (100 - X).

**Example:**
```python
from src.orderbook import OrderBook

orderbook = {
  "yes": [[48, 307]],  # Someone will pay 48¢ for YES
  "no": [[51, 873]]    # Someone will pay 51¢ for NO
}

ob = OrderBook("TICKER", orderbook)
print(f"Best Bid: {ob.best_bid}¢")  # 48¢
print(f"Best Ask: {ob.best_ask}¢")  # 49¢ (from 100 - 51)
print(f"Spread: {ob.spread}¢")      # 1¢
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

### Phase Summaries
- **[Phase 1: API Foundation](docs/PHASE1_SUMMARY.md)** - Authentication, orderbooks, API usage, SDK bug fix
- **[Phase 2: Order Book Processing](docs/PHASE2_SUMMARY.md)** - NO→YES conversion, VWAP, depth analysis, 18 tests
- **[Phase 3: Fee Economics](docs/PHASE3_SUMMARY.md)** - Fee calculations, profitability, minimum spreads, 35 tests

### Technical Guides
- **[Kalshi Mechanics](docs/KALSHI_MECHANICS.md)** - Why YES + NO > $1, position equivalence, market making strategy
- **[API Decisions](docs/API_DECISIONS.md)** - REST vs WebSocket, sync vs async, polling frequency
- **[Orderbook Fix](docs/ORDERBOOK_FIX.md)** - SDK bug workaround details
- **[Git Setup](docs/GIT_SETUP.md)** - Repository initialization and structure

### Configuration
- **[Config Guide](config/README.md)** - How to set up your configuration files

## 🔧 Development

### Quick Example: End-to-End Market Making Decision

```python
from src.client import KalshiClient
from src.orderbook import OrderBook
from src.fees import should_quote_market

# Initialize client
client = KalshiClient(
    key_id="your-key-id",
    private_key=open('kalshidemo.txt').read(),
    host="https://demo-api.kalshi.co/trade-api/v2"
)

# Get market and orderbook
markets = client.get_markets(status="open", limit=1)
ticker = markets[0]['ticker']
raw_ob = client.get_orderbook(ticker, depth=10)

# Process orderbook
ob = OrderBook(ticker, raw_ob)
print(f"Spread: {ob.spread}¢, Mid: {ob.mid_price}¢")

# Evaluate profitability
result = should_quote_market(
    spread_cents=ob.spread,
    contracts=100,
    mid_price_cents=int(ob.mid_price),
    min_profit_cents=25,
    as_maker=True
)

if result['should_quote']:
    print(f"✅ Quote: {result['recommended_bid']}¢ / {result['recommended_ask']}¢")
    print(f"   Expected profit: {result['analysis'].net_profit_cents:.2f}¢")
else:
    print(f"❌ Skip: {result['reason']}")
```

### Running Tests

```bash
# All unit tests
pytest tests/ -v

# Specific module
pytest tests/test_fees.py -v
pytest tests/test_orderbook.py -v

# Phase demonstrations
python phase1_test.py  # API connection
python phase2_test.py  # Order book processing
python phase3_test.py  # Fee economics
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

- [x] **Phase 1: API Foundation** - Authentication, market data, orderbooks, order management
- [x] **Phase 2: Order Book Processing** - NO→YES conversion, VWAP, depth analysis
- [x] **Phase 3: Fee Economics** - Fee calculations, profitability, minimum spreads
- [ ] **Phase 4: Quote Generation** - Optimal pricing, inventory management, quote sizing
- [ ] **Phase 5: Flow Detection** - Toxic flow detection, adverse selection protection
- [ ] **Phase 6: Execution Engine** - Order placement, position tracking, risk limits
- [ ] **Phase 7: Configuration & Deployment** - Config system, logging, monitoring, deployment

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
