# Kalshi Market Mechanics - Deep Dive

## The Critical Question: Why Do YES + NO Prices > $1?

This is **essential** to understand for market making. Let me break it down:

### Settlement Value vs Trading Prices

**At Settlement (when market resolves)**:
- If YES wins: YES holders get $1.00, NO holders get $0.00
- If NO wins: NO holders get $1.00, YES holders get $0.00
- **Total payout is always exactly $1.00** (zero-sum)

**While Trading (on the orderbook)**:
- Best YES ask: 49¢
- Best NO ask: 52¢
- **Total of asks: 49¢ + 52¢ = $1.01** ❗

### Why This Happens: The Bid-Ask Spread

The key insight: **YES and NO are SEPARATE orderbooks**, each with their own bid-ask spread!

```
YES Orderbook:
  Best Bid: 48¢  (someone will BUY YES at 48¢)
  Best Ask: 49¢  (someone will SELL YES at 49¢)

NO Orderbook:
  Best Bid: 51¢  (someone will BUY NO at 51¢)
  Best Ask: 52¢  (someone will SELL NO at 52¢)
```

### The Math: What Does This Mean?

**Option 1: Buy YES at ask**
- Pay: 49¢
- Get if YES wins: $1.00
- Profit if win: 51¢
- Probability implied: 49%

**Option 2: Buy NO at ask**
- Pay: 52¢
- Get if NO wins: $1.00
- Profit if win: 48¢
- Probability implied: 52%

**Total probability**: 49% + 52% = **101%**

This "over-round" is the **market maker's edge**! The spread represents inefficiency that liquidity providers capture.

### Example: How Market Making Works

Let's say mid is 50/50 (truly uncertain event):

**Our Quotes**:
- Post YES bid at 48¢ (willing to buy YES)
- Post NO bid at 51¢ (willing to buy NO)

**What This Means**:
```
We BUY YES at 48¢:
  - If YES wins: We get $1.00 (profit 52¢)
  - If NO wins: We get $0.00 (loss 48¢)

We BUY NO at 51¢:
  - If NO wins: We get $1.00 (profit 49¢)
  - If YES wins: We get $0.00 (loss 51¢)
```

**The Position Risk**:
- If we buy 1 YES at 48¢ and 1 NO at 51¢, we've spent 99¢
- One of them WILL pay $1.00 at settlement
- **Guaranteed profit: $1.00 - $0.99 = 1¢** 🎯

But wait! We're a market maker, so we're **selling** not buying!

## How We Actually Make Money

### As a Maker (providing liquidity):

**Post YES Bid at 48¢**:
- We're offering to BUY YES at 48¢
- Someone sells us YES → we're now LONG YES at 48¢
- We paid 48¢, could get $1.00 if YES wins

**Post NO Bid at 51¢**:
- We're offering to BUY NO at 51¢
- Someone sells us NO → we're now LONG NO at 51¢
- We paid 51¢, could get $1.00 if NO wins

Wait, this seems backwards! If we get filled on BOTH, we're in trouble:
- Spent: 48¢ + 51¢ = 99¢
- Get back: $1.00 (one of them wins)
- Profit: 1¢

But that's only if we get filled on BOTH sides simultaneously!

## The REAL Market Making Strategy

### Understanding Position Management

The key insight: **We want to be FLAT (no position) and capture the spread**

**Round Trip Example**:

1. **Someone hits our YES bid at 48¢**
   - We buy 1 YES for 48¢
   - Position: +1 YES (long 1 YES contract)
   - P&L: -48¢ (we paid)

2. **Later, we SELL that YES at 49¢** (hit someone's YES ask OR wait for our ask to get hit)
   - We sell 1 YES for 49¢
   - Position: 0 (flat)
   - P&L: +49¢ - 48¢ = **+1¢ profit** ✅

We captured the 1¢ spread!

### Equivalence: Buying NO = Selling YES

This is CRITICAL to understand!

**Kalshi's Key Insight**: "There's no inherent difference between buying a Yes contract and selling a No contract"

Here's why:
```
Buying YES at 48¢:
  - Pay 48¢
  - Get $1.00 if YES wins, $0.00 if NO wins

Selling NO at 48¢ (equivalently, BUYING NO at 52¢):
  - Receive 52¢ from buyer
  - Owe them $1.00 if NO wins
  - Net position: Same exposure as buying YES!
```

Actually, let me recalculate this...

**Buying YES at 48¢**:
- Cost: 48¢
- Payoff: $1.00 if YES, $0 if NO
- Net: +52¢ if YES, -48¢ if NO

**Selling NO (receive 52¢, owe $1 if NO wins)**:
- Receive: 52¢
- Owe: $1.00 if NO wins, $0 if YES wins
- Net: +52¢ if YES, -48¢ if NO

**SAME PAYOFF!** ✅

### How We Post Quotes on Kalshi

When we want to provide two-sided liquidity:

**To offer to BUY YES at 48¢**:
- Place YES bid at 48¢
- If filled: We own YES, paid 48¢

**To offer to SELL YES at 52¢**:
- We **cannot** directly post a YES ask!
- Instead: Place NO bid at 48¢ (complementary price!)
- Why? Buying NO at 48¢ = Selling YES at 52¢
- Check: 48¢ (NO) + 52¢ (implied YES) = 100¢ ✅

### The Formula

```
To sell YES at price X:
  → Buy NO at price (100 - X)

To sell NO at price X:
  → Buy YES at price (100 - X)
```

## Complete Market Making Example

**Market**: Houston wins (currently 50/50)

**Current Orderbook**:
```
YES Bids: [48, 47, 46, ...]
NO Bids:  [51, 50, 49, ...]
```

**Implied Market**:
- Best YES bid: 48¢
- Best YES ask: 49¢ (from 100 - 51 = 49)
- Mid: 48.5¢
- Spread: 1¢

**Our Strategy**:
1. Post YES bid at 48¢ (willing to buy YES)
2. Post NO bid at 51¢ (willing to buy NO = willing to sell YES at 49¢)

**Scenario 1: Someone sells us YES**
- We pay 48¢, now long 1 YES
- Risk: Need to exit position
- Exit by: Selling YES at 49¢ (hitting NO bid at 51¢... wait, that's backwards!)

Let me recalculate the exit...

**If we're long 1 YES (bought at 48¢)**:
- To exit: We need to SELL YES
- Option A: Hit the YES ask? No, that's buying more!
- Option B: Wait for someone to hit our YES bid? No, we already have the position!
- Option C: **Post a NO bid** to effectively sell our YES position

Actually, I think I'm confusing myself. Let me think about positions more carefully...

## Position Management - The Clean Way

### Positions on Kalshi

You can have:
- **+N YES contracts** (long YES)
- **-N YES contracts** (short YES, same as +N NO)
- **+N NO contracts** (long NO)
- **-N NO contracts** (short NO, same as +N YES)

### How to Exit Positions

**If you're +1 YES (long YES)**:
- You bought YES for X¢
- To exit: **Sell YES** for Y¢
- But Kalshi only has BIDS, not ASKS!
- Solution: ???

Wait, this is the confusion! Let me look at the actual API...

Actually, from our tests, we saw the API has BOTH:
- `side`: "yes" or "no"
- `action`: "buy" or "sell"

So you CAN sell YES directly!

### The Complete Picture

**API allows 4 order types**:
1. Buy YES (go long YES)
2. Sell YES (go short YES = go long NO)
3. Buy NO (go long NO = go short YES)
4. Sell NO (go short NO = go long YES)

**Equivalences**:
- Sell YES = Buy NO (both result in short YES position)
- Sell NO = Buy YES (both result in short NO position)

### Market Making Strategy (Corrected)

**To provide two-sided liquidity at mid = 48.5¢**:

**Option A: Using YES side**
1. Post: Buy YES at 48¢ (bid)
2. Post: Sell YES at 49¢ (ask)

**Option B: Using NO side**
1. Post: Buy NO at 51¢ (bid)
2. Post: Sell NO at 52¢ (ask)

**Option C: Mixed (what Kalshi orderbook shows)**
1. Post: Buy YES at 48¢ (YES bid)
2. Post: Buy NO at 51¢ (NO bid, implies YES ask at 49¢)

All three are equivalent from a position perspective!

## Profitability Analysis

**Scenario: We post both sides and get filled**

1. Someone sells us YES at 48¢
   - Position: +1 YES
   - Cash: -48¢

2. Someone sells us NO at 51¢
   - Position: +1 YES, +1 NO
   - Cash: -48¢ - 51¢ = -99¢

At settlement:
- One contract pays $1.00, the other pays $0
- Total received: $1.00
- **Net profit: $1.00 - $0.99 = 1¢**

This is the spread we captured! ✅

**But what if we only get filled on one side?**

If only filled on YES at 48¢:
- Position: +1 YES
- Need to exit to lock in profit
- Exit by selling YES at 49¢
- Profit: 1¢

If only filled on NO at 51¢:
- Position: +1 NO
- Exit by selling NO at 52¢
- Profit: 1¢

Either way, we capture the spread!

## Risk: Adverse Selection

**The danger**: Market moves against us before we can exit

Example:
1. We buy YES at 48¢
2. Bad news comes out (Houston QB injured!)
3. Market crashes to 30¢ bid / 31¢ ask
4. We're forced to sell at 31¢
5. **Loss: 48¢ - 31¢ = 17¢** ❌

This is why we need:
- Position limits
- Toxic flow detection
- Quick position exit

## Summary for Market Making Bot

✅ **Understanding**:
- YES + NO asks > $1 due to bid-ask spread on each side
- Spread = market maker's edge
- Buying NO = Selling YES (complementary)

✅ **Strategy**:
- Post bids on both YES and NO sides
- Capture spread when filled
- Exit positions quickly to lock profit
- Watch for toxic flow (informed traders)

✅ **Risk Management**:
- Limit position size
- Exit quickly when filled on one side
- Detect runs (consecutive same-direction fills)
- Pull quotes if toxic flow detected

**Next**: Phase 3 will implement fee calculations and profitability checks!
