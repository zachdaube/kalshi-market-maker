# API Architecture Decisions

## Sync vs Async

### Decision: Start with Sync, Migrate to Async in Phase 6

**Current:** Using `kalshi_python_sync`

**Rationale:**
- Simpler to debug during development (Phases 1-5)
- Easier to test incrementally
- Sufficient for single-market market making
- 1Hz polling is adequate for prediction markets

**Future (Phase 6):**
- Migrate to `kalshi_python_async`
- Benefits: Poll multiple markets simultaneously, non-blocking I/O
- Use `asyncio` for concurrent orderbook fetching + order placement
- Better performance for multi-market strategies

**Migration Path:**
```python
# Current (sync)
orderbook = client.get_orderbook(ticker)

# Future (async)
orderbook = await client.get_orderbook(ticker)

# Multi-market async
orderbooks = await asyncio.gather(*[
    client.get_orderbook(t) for t in tickers
])
```

## REST vs WebSockets

### Decision: Use REST API Polling

**Rationale:**
1. **Kalshi WebSocket support unclear**: Orderbook updates may not be available via WS
2. **Prediction markets are slower**: Not like crypto orderbooks changing 100x/second
3. **1Hz polling is sufficient**: Markets don't move that fast
4. **Simpler error handling**: No need to handle WS disconnects/reconnects
5. **Rate limit friendly**: Controlled polling respects API limits

**Polling Strategy:**
```python
while True:
    orderbook = client.get_orderbook(ticker)
    # Process orderbook, update quotes
    time.sleep(1.0)  # 1Hz polling
```

**Alternative considered:**
- WebSockets for trade feed (detect toxic flow)
- REST for orderbook + order management
- **Decision:** REST-only for now, can add WS later if needed

## Order Types

### Using Limit Orders with Post-Only

**Why:**
- **Maker fees**: 0.0175 × C × P × (1-P) - 4x cheaper than taker
- **Post-only**: Ensures we never take liquidity
- **Avoid adverse selection**: Don't chase the market

**Order Placement Strategy:**
```python
# Post quotes on both sides
yes_bid_order = place_order(
    side="yes",
    action="buy",
    price=bid_price,
    type="limit"
)

no_bid_order = place_order(
    side="no",
    action="buy",
    price=100 - ask_price,  # NO bid = YES ask
    type="limit"
)
```

## Error Handling

### SDK Bug Workaround

**Issue:** `kalshi_python_sync` has Pydantic validation bug in orderbook
- Expects string quantities, API returns integers
- Causes validation errors on non-empty orderbooks

**Solution:** Bypass SDK validation with raw HTTP:
```python
response = self.client.call_api(method="GET", url=orderbook_url)
data = json.loads(response.read())
```

**Fallback:** Use market endpoint for top-of-book if orderbook fails

### Rate Limiting

**Strategy (Phase 6):**
- Track API calls per second/minute
- Exponential backoff on 429 errors
- Queue requests if approaching limits

**Current:** 1Hz polling is well under limits

## Testing Strategy

### Demo First, Production Never (Until Ready)

**Demo Environment:**
- All development and testing
- Virtual money ($98.00 balance)
- Safe to experiment
- Same API, different host

**Production Environment:**
- Only when strategy is proven profitable in demo
- Start with minimal size (10 contracts)
- Strict risk limits

**Order Placement Test Results:**
```
✓ Placed order at 28¢ (20¢ below mid)
✓ Order confirmed RESTING
✓ Cancellation working
✓ Balance unchanged
```

## Performance Considerations

### Current (Phases 1-5):
- Sync API: ~100-200ms per request
- 1Hz polling: Sufficient for prediction markets
- Single market focus

### Future Optimizations (Phase 6+):
- Async API: Parallel requests
- Connection pooling
- Request batching where possible
- Caching market metadata

## Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Sync vs Async** | Sync now, Async Phase 6 | Simpler development |
| **REST vs WS** | REST polling | Sufficient + simpler |
| **Polling Rate** | 1Hz | Balances latency + rate limits |
| **Order Type** | Limit (post-only) | Maker fees 4x cheaper |
| **Environment** | Demo only | Safe testing |
| **Error Handling** | SDK bypass + fallbacks | Robust operation |

These decisions support building a solid foundation in Phases 1-5, with clear path to optimization in Phase 6+.
