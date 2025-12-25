# Documentation Index

Complete documentation for the Kalshi Market Making Bot project.

## 📖 Table of Contents

### 🎯 Phase Summaries (Implementation Guides)

1. **[Phase 1: API Foundation](PHASE1_SUMMARY.md)**
   - Kalshi API authentication (RSA keys)
   - Market data retrieval and filtering
   - Orderbook fetching (with SDK bug workaround)
   - Order management (place, cancel, track)
   - Portfolio and balance queries
   - **Status**: ✅ Complete (371 lines)

2. **[Phase 2: Order Book Processing](PHASE2_SUMMARY.md)**
   - NO bid → YES ask conversion (`100 - X` formula)
   - Market metrics (best bid/ask, mid, spread)
   - VWAP (Volume-Weighted Average Price)
   - Depth analysis (cumulative, by price level)
   - Edge case handling (empty, crossed, one-sided)
   - **Status**: ✅ Complete (290 lines, 18 tests)

3. **[Phase 3: Fee Economics](PHASE3_SUMMARY.md)**
   - Maker (1.75%) vs Taker (7.00%) fee calculations
   - Round-trip fee analysis
   - Profitability analysis (gross → net P&L)
   - Minimum spread requirements (2¢ to break even)
   - Market evaluation logic (`should_quote_market`)
   - **Status**: ✅ Complete (580 lines, 35 tests)

4. **Phase 4: Quote Generation** (Coming Next)
   - Optimal bid/ask pricing
   - Inventory-based skewing
   - Quote sizing based on liquidity
   - Position risk management

### 🧠 Conceptual Guides (Understanding Kalshi)

- **[Kalshi Market Mechanics](KALSHI_MECHANICS.md)** - Deep dive into how Kalshi works
  - Why YES + NO prices sum to > $1
  - Position equivalence (buying NO = selling YES)
  - Market making strategy and spread capture
  - Risk of adverse selection
  - Complete with examples and P&L calculations

### 🔧 Technical Reference

- **[API Decisions](API_DECISIONS.md)** - Architecture choices
  - REST vs WebSocket (chose REST for simplicity)
  - Sync vs Async (sync first, async later if needed)
  - Polling frequency (1Hz is sufficient)
  - Rationale for each decision

- **[Orderbook SDK Bug Fix](ORDERBOOK_FIX.md)** - Technical writeup
  - Description of the Pydantic validation bug
  - Root cause analysis
  - Our HTTP bypass solution
  - Code examples and test results

- **[Git Setup](GIT_SETUP.md)** - Repository structure
  - Initial setup and .gitignore
  - Branch strategy
  - Commit message format
  - API key protection

## 📊 Quick Reference

### Key Formulas

**NO Bid → YES Ask Conversion**:
```
YES_ask = 100 - NO_bid
```

**Kalshi Fee Formula**:
```
fee = fee_rate × contracts × P × (1-P)

Maker: fee_rate = 0.0175 (1.75%)
Taker: fee_rate = 0.07 (7.00%)
```

**Minimum Profitable Spread** (at ~48¢ mid, 100 contracts):
- Maker: **2¢** to break even
- Taker: **4¢** to break even

### Critical Insights

1. **Maker Advantage**: Taker fees are 4x higher than maker fees
   - Always provide liquidity (be a maker)
   - Never take liquidity (avoid taker fees)

2. **Fee Impact**: On a 2¢ spread with 100 contracts:
   - Gross profit: 200¢
   - Maker fees: ~87¢ (44% of gross!)
   - Net profit: ~113¢

3. **Price Sensitivity**: Fees are worst at 50¢ (P×(1-P) maximized)
   - At 50¢: 43.75¢ fee per 100 contracts
   - At 30¢: 36.75¢ fee (16% better)
   - At 10¢: 15.75¢ fee (64% better)

4. **Position Equivalence**:
   - Buying NO at X¢ = Selling YES at (100-X)¢
   - Selling NO at X¢ = Buying YES at (100-X)¢

## 🚀 Usage Examples

### Complete Market Making Flow

```python
from src.client import KalshiClient
from src.orderbook import OrderBook
from src.fees import should_quote_market

# 1. Connect to Kalshi
client = KalshiClient(
    key_id="your-key-id",
    private_key=open('kalshidemo.txt').read(),
    host="https://demo-api.kalshi.co/trade-api/v2"
)

# 2. Get market data
markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=5)
ticker = markets[0]['ticker']

# 3. Fetch and process orderbook
raw_ob = client.get_orderbook(ticker, depth=10)
ob = OrderBook(ticker, raw_ob)

# 4. Evaluate profitability
result = should_quote_market(
    spread_cents=ob.spread,
    contracts=100,
    mid_price_cents=int(ob.mid_price),
    min_profit_cents=25,
    as_maker=True
)

# 5. Make decision
if result['should_quote']:
    bid = result['recommended_bid']
    ask = result['recommended_ask']

    # Place YES bid
    client.place_order(ticker, "yes", "buy", 100, bid)

    # Place YES ask (via NO bid at complementary price)
    no_bid = 100 - ask
    client.place_order(ticker, "no", "buy", 100, no_bid)

    print(f"✅ Quoted {ticker}: {bid}¢ / {ask}¢")
else:
    print(f"❌ Skipping {ticker}: {result['reason']}")
```

## 📈 Project Stats

**Code**:
- 3 core modules: 1,241 lines
- 2 test suites: 853 lines
- 5 demo scripts: 640 lines
- **Total**: 2,734 lines of Python

**Tests**:
- 53 unit tests (all passing ✅)
- 100% coverage of public APIs
- Validated with live NFL market data

**Documentation**:
- 6 technical documents
- 3 phase summaries
- ~2,000 lines of documentation

## 🎯 What's Next: Phase 4

Phase 4 will implement quote generation:

**Quote Strategy**:
1. Calculate optimal bid/ask around mid
2. Adjust for inventory (skew away from position)
3. Size quotes based on available liquidity
4. Respect position limits

**Risk Management**:
1. Maximum position size
2. Inventory skewing (lean against position)
3. Maximum loss per session
4. Quote pulling on toxic flow

**Implementation**:
1. `src/quotes.py` - Quote generation logic
2. Position tracking and inventory management
3. Risk limit enforcement
4. Integration with orderbook and fee modules

## 📞 Getting Help

- **Phase summaries**: Start with [PHASE1_SUMMARY.md](PHASE1_SUMMARY.md) → work through sequentially
- **Kalshi concepts**: Read [KALSHI_MECHANICS.md](KALSHI_MECHANICS.md)
- **Technical issues**: Check [ORDERBOOK_FIX.md](ORDERBOOK_FIX.md) and [API_DECISIONS.md](API_DECISIONS.md)
- **Code examples**: See phase test files (`phase1_test.py`, etc.)

## 🔗 External Resources

- [Kalshi API Documentation](https://trading-api.readme.io/reference/getting-started)
- [Kalshi Python SDK (sync)](https://github.com/Kalshi/kalshi-python)
- [Market Making Basics](https://www.investopedia.com/terms/m/marketmaker.asp)
- [Prediction Markets Explained](https://en.wikipedia.org/wiki/Prediction_market)

---

**Last Updated**: December 24, 2024
**Current Phase**: 3/7 Complete
**Next Milestone**: Phase 4 - Quote Generation
