# Avellaneda-Stoikov Market Maker: Implementation Guide

## Overview

This market maker implements the optimal quoting strategy from the paper "High-frequency trading in a limit order book" (Avellaneda & Stoikov, 2006). The model provides mathematically derived formulas for:

1. **Where to quote** (reservation price based on inventory)
2. **How wide to quote** (optimal spread based on order arrival rates)

---

## How the Bot Works

### Core Logic Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Every 1 second:                          │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch orderbook from Kalshi API                         │
│  2. Get current mid price (best_bid + best_ask) / 2         │
│  3. Get current inventory position                          │
│  4. Calculate RESERVATION PRICE (inventory-adjusted fair)   │
│  5. Calculate OPTIMAL SPREAD                                │
│  6. Place bid/ask around reservation price                  │
│  7. Cancel old orders if prices moved                       │
└─────────────────────────────────────────────────────────────┘
```

### The Math

**Reservation Price** (where the market maker thinks fair value is, given inventory):
```
r = s - q × γ × σ²
```

| Variable | Meaning | Example |
|----------|---------|---------|
| `s` | Market mid price | 50¢ |
| `q` | Current inventory (+long, -short) | +20 contracts |
| `γ` | Risk aversion parameter | 0.1 |
| `σ` | Volatility (cents) | 2.0 |

**Example**: Mid = 50¢, inventory = +20 (long), γ=0.1, σ=2.0
```
r = 50 - 20 × 0.1 × 4 = 50 - 8 = 42¢
```
The reservation price is BELOW mid because we're long and want to sell.

**Optimal Spread**:
```
spread = (2/γ) × ln(1 + γ/k)
```

| Variable | Meaning | Example |
|----------|---------|---------|
| `γ` | Risk aversion | 0.1 |
| `k` | Order arrival decay | 1.5 |

**Example**: γ=0.1, k=1.5
```
spread = (2/0.1) × ln(1 + 0.1/1.5) = 20 × ln(1.067) = 20 × 0.065 = 1.3¢
```

**Final Quotes**:
```
bid = reservation - spread/2 = 42 - 0.65 = 41¢
ask = reservation + spread/2 = 42 + 0.65 = 43¢
```

### What This Achieves

1. **Inventory Mean-Reversion**: When long, quotes shift DOWN to encourage selling
2. **Risk Management**: Spread widens based on volatility and risk preferences
3. **Optimal Fill Rate**: Spread calibrated to order arrival rates

---

## Parameter Tuning Guide

### γ (gamma) - Risk Aversion

| Value | Behavior | Use When |
|-------|----------|----------|
| 0.01 | Very small inventory adjustment, quotes near mid | High liquidity, confident in fair value |
| 0.1 | Moderate adjustment (default) | Normal conditions |
| 0.5 | Aggressive inventory control | Volatile markets, want to stay flat |
| 1.0+ | Extreme aversion, very wide quotes when positioned | Very risk-averse |

### σ (sigma) - Volatility

| Value | Meaning |
|-------|---------|
| 1.0 | Low volatility market |
| 2.0 | Normal volatility (default) |
| 5.0+ | High volatility / uncertain markets |

**Tip**: Estimate from recent price moves. If price typically moves 2-3 cents per minute, σ ≈ 2-3.

### k - Order Arrival Intensity

| Value | Meaning |
|-------|---------|
| 0.5 | Orders arrive frequently even at wide spreads |
| 1.5 | Normal decay (default) |
| 3.0+ | Orders only arrive at very tight spreads |

**Tip**: Lower k = expect fills even with wider spreads. Higher k = need tighter spreads to get filled.

---

## Deployment Steps

### Step 1: Prerequisites

```bash
# Clone repository
git clone https://github.com/zachdaube/kalshi-market-maker.git
cd kalshi-market-maker

# Install dependencies
pip install -r requirements.txt

# Verify tests pass
python -m pytest tests/ --ignore=tests/test_flow.py -v
```

### Step 2: Get Kalshi API Credentials

1. Go to https://kalshi.com/account/api
2. Generate an API key pair
3. Download the private key file
4. Set environment variable:
   ```bash
   export KALSHI_KEY_ID="your-key-id-here"
   ```
5. Save private key as `kalshidemo.txt` (for demo) or `kalshiprod.txt` (for prod)

### Step 3: Configure Markets

Edit `config/demo.yaml`:

```yaml
environment: demo

execution:
  quote_interval: 1.0           # How often to update quotes
  position_sync_interval: 5.0   # How often to sync positions
  total_max_position: 500       # Max exposure across all markets
  cancel_threshold: 1           # Requote if price moves 1+ cents
  dry_run: true                 # SET TO FALSE FOR REAL TRADING

markets:
  - ticker: KXBTC-25JAN15-T100000   # Replace with actual ticker
    enabled: true
    gamma: 0.1        # Risk aversion
    sigma: 2.0        # Volatility estimate
    k: 1.5            # Order arrival decay
    base_size: 10     # Contracts per order
    max_position: 100 # Max position this market
    max_loss_cents: 500.0  # Stop loss

api:
  key_id: ${KALSHI_KEY_ID}
  private_key_file: kalshidemo.txt
  host: https://demo-api.kalshi.co/trade-api/v2
```

### Step 4: Test in Dry Run Mode

```bash
# Run with dry_run: true (no real orders)
python run_market_maker.py --env demo

# Output will show:
# [DRY] KXBTC-25JAN15 bid=48c x10 ask=52c x10 (r=50.0)
```

### Step 5: Test on Demo Environment

```bash
# Edit config/demo.yaml: set dry_run: false
# This uses DEMO API with virtual money

python run_market_maker.py --env demo
```

Monitor:
- Are quotes being placed?
- Are they getting filled?
- Is inventory staying bounded?

### Step 6: Production Deployment

1. **Create production config** (`config/prod.yaml`):
   ```yaml
   environment: prod

   execution:
     dry_run: false  # REAL ORDERS
     # ... same as demo but with real tickers

   api:
     key_id: ${KALSHI_KEY_ID}
     private_key_file: kalshiprod.txt
     host: https://trading-api.kalshi.com/trade-api/v2
   ```

2. **Start with small size**:
   ```yaml
   base_size: 5        # Start small
   max_position: 50    # Limit exposure
   ```

3. **Run**:
   ```bash
   python run_market_maker.py --env prod
   ```

### Step 7: Monitor

Watch for:
- **Position drift**: Is inventory staying near zero on average?
- **Fill rate**: Are both sides getting filled?
- **P&L**: Are you profitable after fees?

---

## Architecture

```
run_market_maker.py          # Entry point
    │
    ├── src/config_loader.py # Loads YAML config
    │
    ├── src/client.py        # Kalshi API wrapper
    │
    ├── src/execution.py     # Main loop
    │       │
    │       ├── Fetches orderbook
    │       ├── Calls generate_quote()
    │       └── Places/cancels orders
    │
    ├── src/quotes.py        # AS model
    │       │
    │       ├── calculate_reservation_price()
    │       ├── calculate_optimal_spread()
    │       └── generate_quote()
    │
    └── src/orderbook.py     # Orderbook processing
```

---

## File Reference

| File | Purpose | Lines |
|------|---------|-------|
| `src/quotes.py` | AS model (reservation price, spread) | 224 |
| `src/execution.py` | Main loop, order management | 290 |
| `src/orderbook.py` | Parse Kalshi orderbook format | 311 |
| `src/fees.py` | Kalshi fee calculations | 55 |
| `src/config_loader.py` | YAML config loading | 109 |
| `src/client.py` | Kalshi API client | ~370 |

---

## Common Issues

### "No quote generated"
- Check if orderbook has liquidity on both sides
- Mid price must be between 1-99

### "Position keeps growing"
- Increase γ (gamma) for more aggressive inventory control
- Check if one side is getting filled more than other

### "Not getting filled"
- Spread may be too wide - decrease γ or increase k
- Check if you're competitive with other market makers

### "Losing money"
- Fees are 1.75% maker - need spread > ~2-3¢ to profit
- May be getting adversely selected (informed traders)

---

## Quick Start Commands

```bash
# Test everything works
python -m pytest tests/ --ignore=tests/test_flow.py -v

# Dry run (no orders)
python run_market_maker.py --env demo

# Demo trading (virtual money)
# First: edit config/demo.yaml, set dry_run: false
python run_market_maker.py --env demo

# Production (REAL MONEY)
# First: create config/prod.yaml with production settings
python run_market_maker.py --env prod
```

---

## References

- [Avellaneda & Stoikov (2006)](https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf) - Original paper
- [Kalshi API Docs](https://trading-api.readme.io/) - API reference
