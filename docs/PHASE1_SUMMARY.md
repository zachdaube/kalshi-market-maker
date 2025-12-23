# Phase 1 Complete: Kalshi API Foundation ✓

## What We Built

We've successfully established an authenticated connection to the Kalshi API and built core data retrieval functions. The foundation is solid and ready for Phase 2.

## Files Created

1. **[src/client.py](src/client.py)** - Main API wrapper with all essential methods
2. **[phase1_test.py](phase1_test.py)** - Test script that demonstrates the connection
3. **[requirements.txt](requirements.txt)** - Python dependencies
4. **[README.md](README.md)** - Project documentation

## How RSA Key Authentication Works

Kalshi uses a sophisticated authentication system:

1. **Key Pair**: You have an API Key ID (like a username) and an RSA private key (like a password, but cryptographic)

2. **Request Signing**: Each API request is signed with your private key
   - The SDK (`kalshi_python_sync`) handles this automatically
   - The server verifies the signature using your public key (which they have)
   - This proves the request came from you without sending your private key

3. **Why RSA vs Username/Password?**
   - More secure - private key never leaves your machine
   - Better for programmatic access
   - Harder to accidentally leak (can't just copy-paste a password)

## Demo vs Production Environments

### Demo Environment
- **Host**: `https://demo-api.kalshi.co/trade-api/v2`
- **Purpose**: Safe testing without real money
- **API Key**: Different from production (you have: `2afd56dd-fd59-4649-8135-e6c39e89325c`)
- **Limitations**: May have fewer active markets, empty orderbooks
- **Balance**: Virtual money ($98 in your demo account)

### Production Environment
- **Host**: `https://api.elections.kalshi.com/trade-api/v2`
- **Purpose**: Real trading with real money
- **API Key**: Different from demo (stored in `zachdaube.txt`)
- **Critical**: ALWAYS test strategies on demo first!

## Rate Limits

The Kalshi API has rate limits to prevent abuse:
- **Per-second limits**: Varies by endpoint
- **Per-minute limits**: More generous ceiling
- **Handling**: The SDK will raise an exception if you hit limits
- **Best practice**:
  - Don't poll faster than 1Hz (once per second) for market data
  - Use exponential backoff if you get rate limit errors
  - Cache data when possible

We'll implement proper rate limit handling in Phase 6 (Execution Engine).

## Understanding Kalshi's Order Book Format

This is **critical** for market making!

### What Kalshi Returns

```json
{
  "yes": [[45, 100], [44, 50]],  // YES bids only
  "no": [[60, 100], [61, 50]]    // NO bids only
}
```

Kalshi only shows **bids** for both sides. There are no explicit "asks". Why?

### The Math Behind It

**Key Insight**: Buying NO at price X is mathematically equivalent to selling YES at price (100 - X).

#### Example 1: Simple Conversion

- **NO bid at 40¢** means: "I'll pay 40¢ to buy NO"
- This is the same as: "I'll sell YES at 60¢" (100 - 40 = 60)
- Why? Let's trace the money:

  **If you sell YES at 60¢**:
  - You receive: 60¢
  - If YES wins: You pay $1.00 (net: -40¢)
  - If YES loses: You pay $0.00 (net: +60¢)

  **If you buy NO at 40¢**:
  - You pay: 40¢
  - If NO wins: You receive $1.00 (net: +60¢)
  - If NO loses: You receive $0.00 (net: -40¢)

  **Same payoff structure!**

#### Example 2: Market Making View

Suppose we see:
```
YES bids: [[45, 100]]  // Someone will pay 45¢ for YES
NO bids: [[60, 100]]   // Someone will pay 60¢ for NO
```

From a YES-centric view:
- **Best YES bid**: 45¢ (direct from orderbook)
- **Best YES ask**: 40¢ (implied from NO bid at 60¢)

**This market is crossed!** The ask (40¢) is lower than the bid (45¢). This shouldn't happen in normal markets and represents an arbitrage opportunity.

#### Example 3: Normal Two-Sided Market

```
YES bids: [[48, 100]]
NO bids: [[48, 100]]
```

From a YES-centric view:
- **Best YES bid**: 48¢
- **Best YES ask**: 52¢ (from 100 - 48 = 52)
- **Spread**: 4¢
- **Mid price**: 50¢

This makes sense! The market is centered around 50/50.

### Edge Cases We Handle

1. **Empty Order Book**
   - Demo environments often have no orders
   - Our wrapper returns `{"yes": [], "no": []}`
   - Best bid/ask will be None

2. **One-Sided Book**
   - Only YES bids OR only NO bids
   - Still valid - just means no one wants the other side
   - We handle this gracefully

3. **Stale Quotes**
   - Orders may be cancelled between fetches
   - Always refresh before placing orders
   - We'll add staleness checks in Phase 6

## API Methods We Implemented

### Market Data

```python
# Fetch multiple markets
markets = client.get_markets(status="open", limit=100)

# Get single market details
market = client.get_market("KXCBDECISIONJAPAN-26JAN22-HOLD")

# Get order book (with empty book handling)
orderbook = client.get_orderbook("TICKER", depth=10)

# Get recent trades
trades = client.get_trades("TICKER", limit=100)
```

### Order Management

```python
# Place an order
order = client.place_order(
    ticker="TICKER",
    side="yes",  # or "no"
    action="buy",  # or "sell"
    quantity=10,
    price=45,  # cents
    order_type="limit"
)

# Cancel orders
client.cancel_order(order_id="...")
client.cancel_all_orders(ticker="TICKER")  # or all if ticker=None

# Check positions and balance
orders = client.get_open_orders()
positions = client.get_positions()
balance = client.get_balance()
```

## Test Results

Running `python phase1_test.py`:

```
✓ Loaded private key (1679 characters)
✓ Using API Key ID: 2afd56dd-fd59-4649-8135-e6c39e89325c
✓ Client initialized
✓ Found 10 open markets
✓ Order book retrieved
✓ Account balance: $98.00
```

**Status**: All systems operational! 🚀

## Common Issues & Solutions

### Issue: "Validation error" when fetching orderbook
**Cause**: The `kalshi_python_sync` SDK has a Pydantic validation bug - it expects strings for quantity values in `yes_dollars`/`no_dollars` arrays, but the Kalshi API returns integers.
**Solution**: Our wrapper bypasses the SDK's broken `get_market_orderbook()` method and makes a raw authenticated HTTP request using `client.call_api()`, then parses the JSON directly. This gives us the full orderbook depth without validation errors.

### Issue: "Authentication failed"
**Cause**: Wrong API key ID or private key
**Solution**: Double-check your credentials match the environment (demo vs production)

### Issue: Rate limit errors
**Cause**: Too many API calls
**Solution**: Add delays between requests (we'll implement this in Phase 6)

## Next Steps

**Phase 2**: Order Book Processing
- Build `OrderBook` class to parse Kalshi's format
- Convert to unified YES-centric view (bids and asks)
- Calculate depth, VWAP, spread metrics
- Handle all edge cases gracefully

**Phase 3**: Fee Economics
- Implement maker/taker fee calculations
- Determine minimum profitable spreads
- Calculate expected profit per round trip

Are you ready to move on to Phase 2? We'll build the orderbook parser and analysis tools!
