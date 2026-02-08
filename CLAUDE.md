# CLAUDE.md - Kalshi Market Maker Agent Reference

This document is the authoritative reference for AI agents working on this codebase.
Read it fully before making any changes. The codebase is a work-in-progress and
contains known bugs and incomplete integrations documented below.

---

## Project Overview

An automated market maker for Kalshi prediction markets using the Avellaneda-Stoikov
(AS) optimal quoting model. The bot continuously posts two-sided quotes (a bid to buy
YES and an equivalent ask to sell YES) on configured markets, adjusts prices based on
inventory, and captures the bid-ask spread as profit.

**Key tech:** Python 3.11, Kalshi API via `kalshi_python_sync`, Flask + SocketIO dashboard.

---

## Repository Structure

```
run_market_maker.py          # Headless entry point (no dashboard)
dashboard.py                 # Web dashboard + integrated bot (primary entry point)
Dockerfile                   # Container build
docker-compose.yml           # Orchestration (mounts keys, config)
requirements.txt             # Dependencies

src/
  client.py                  # Kalshi API wrapper (auth, orders, market data)
  execution.py               # Main execution engine (tick loop, state management)
  quotes.py                  # AS model (reservation price, optimal spread, quote gen)
  orderbook.py               # Order book parsing (NO->YES conversion, metrics)
  fees.py                    # Fee calculations (maker 1.75%, taker 7%)
  flow.py                    # Toxic flow detection (NOT INTEGRATED - see Known Bugs)
  config_loader.py           # YAML config loading with env var expansion

config/
  demo.yaml                  # Demo environment config (dry_run: true by default)
  prod.yaml                  # Production config (REAL MONEY)

scripts/
  deploy.sh                  # Deploy to DigitalOcean droplet via Docker
  bot.sh                     # Remote bot control (start/stop/logs/status)

tests/
  test_config.py             # Config validation and loading
  test_quotes.py             # AS model math and quote generation
  test_orderbook.py          # Order book parsing and metrics
  test_fees.py               # Fee calculations
  test_execution.py          # Engine lifecycle and state management
  test_flow.py               # Flow detection (most comprehensive test file)

docs/
  AVELLANEDA_STOIKOV_GUIDE.md
  KALSHI_MECHANICS.md
```

---

## How the Bot Works: End-to-End Flow

### 1. Startup

Two entry points exist:

- **`run_market_maker.py`** - Headless. Loads config, creates `KalshiClient`, runs
  `ExecutionEngine.start()` in main thread. Signal handlers (SIGINT/SIGTERM) trigger
  `engine.stop()`.
- **`dashboard.py`** - Primary. Same setup but also starts Flask+SocketIO on port 8080.
  The trading loop runs in a **background daemon thread**. The dashboard provides
  real-time WebSocket updates to a browser UI.

Startup sequence:
```
CLI args (--env, --live, --port) parsed
  -> ConfigLoader.load(environment) reads YAML
  -> Environment variables expanded (${KALSHI_KEY_ID} etc.)
  -> Config validated (required sections, tickers, API fields)
  -> Private key read from file (kalshidemo.txt or kalshiprod.txt)
  -> KalshiClient initialized with RSA-signed auth
  -> ExecutionEngine created with config + client
  -> Main loop starts
```

### 2. The Main Tick Loop

The engine runs a `while self.running` loop, calling `_tick()` then sleeping
`quote_interval` seconds (default 1.0s).

Each tick does:

```
_tick():
  1. If position_sync_interval (5s) has elapsed -> _sync_positions()
  2. If total_exposure > total_max_position -> cancel ALL orders, return
  3. For each enabled market -> _update_market(ticker, market_config)
```

### 3. Market Update Cycle (`_update_market`)

This is the core per-market logic, called every tick for each enabled market:

```
_update_market(ticker, market_config):
  1. Initialize OrderState for this ticker if first time
  2. Fetch orderbook from API (depth=5 in engine, depth=10 in dashboard)
  3. Create OrderBook object (parses raw data, converts NO bids -> YES asks)
  4. Check mid_price exists and is valid -> if not, cancel orders, return
  5. Get current position from PositionTracker
  6. Check stop loss: if PnL < -max_loss_cents -> cancel orders, return
  7. Build ASParams, call generate_quote()
  8. If quote is None -> cancel orders, return
  9. Compare new quote vs last_quote:
     - If bid AND ask moved less than cancel_threshold -> skip (no update)
  10. Call _place_orders()
```

### 4. Quote Generation (Avellaneda-Stoikov Model)

Core logic in `src/quotes.py`. Two formulas drive everything:

**Reservation Price** (inventory-adjusted fair value):
```
r = s - q * gamma * sigma^2
```
- `s` = mid price from orderbook
- `q` = current inventory (positive = long YES, negative = short YES)
- `gamma` = risk aversion parameter
- `sigma` = volatility estimate (cents)

When long (q > 0), reservation drops below mid -> quotes shift down to encourage
selling. When short (q < 0), reservation rises above mid -> quotes shift up to
encourage buying. This is the inventory management mechanism.

**Optimal Spread**:
```
spread = (2/gamma) * ln(1 + gamma/k)
```
- `k` = order arrival intensity decay

**Quote construction**:
```
bid = reservation - spread/2   (rounded to int cents)
ask = reservation + spread/2   (rounded to int cents)
```

After rounding:
- Enforce minimum 1-cent spread (if bid >= ask, force bid = floor(r)-1, ask = floor(r)+1)
- Clamp to valid range: bid in [1, 98], ask in [2, 99]
- If still bid >= ask after clamping -> return None (no valid quote)

**Size adjustment**: When position exceeds 80% of max_position, the side that would
increase exposure gets its size halved. E.g., if long and at 85% capacity, bid_size
is halved but ask_size stays at base_size.

### 5. Order Placement

`_place_orders()` always cancels existing orders first (cancel-replace pattern):

```
_place_orders(ticker, quote, state):
  1. _cancel_orders(ticker)  -- cancel old YES and NO orders by stored IDs
  2. If dry_run: log the quote, store as last_quote, return
  3. Convert quote to Kalshi order format via to_kalshi_orders()
  4. Place YES bid order -> store yes_order_id
  5. Place NO bid order -> store no_order_id
  6. Update last_quote, last_update, stats['quotes']
```

### 6. Kalshi Order Format (Critical Detail)

Kalshi's orderbook is **bids-only** on both YES and NO sides. There are no explicit
asks. To provide two-sided liquidity:

- **YES bid** at X cents: We want to buy YES at X. Straightforward.
- **YES ask** at Y cents: We want to sell YES at Y. Kalshi has no ask orders.
  Instead, we place a **NO bid** at `100 - Y` cents. Buying NO at that price has
  the same economic payoff as selling YES.

The `TwoSidedQuote.to_kalshi_orders()` method handles this conversion:
```python
yes_bid = {'side': 'yes', 'action': 'buy', 'price': bid.price_cents, 'quantity': bid.quantity}
no_bid  = {'side': 'no',  'action': 'buy', 'price': 100 - ask.price_cents, 'quantity': ask.quantity}
```

**Example**: If our quote is bid=48, ask=52:
- YES bid at 48c (we buy YES at 48c)
- NO bid at 48c (100-52=48; economically equivalent to selling YES at 52c)

If BOTH orders fill, we pay 48+48=96c and hold 1 YES + 1 NO. One settles at $1, the
other at $0, so we receive $1. Profit = 4c minus fees. This is the ideal outcome.

Typically only ONE side fills. Then inventory management (via the reservation price
shift) encourages the opposite side to fill on subsequent ticks.

### 7. Position Tracking and Fill Detection

Fills are detected via `_sync_positions()`, called every `position_sync_interval`
(default 5s). It compares API positions against the local `PositionTracker`:

```
_sync_positions():
  api_positions = client.get_positions()
  for each position:
    if API qty != tracked qty:
      delta = abs(difference)
      stats['fills'] += delta
      update PositionTracker
```

**PositionTracker** (`quotes.py`):
- `positions: Dict[str, Position]` where Position has `ticker`, `quantity`, `avg_entry_price`
- `update_position(ticker, delta, price)` handles averaging entry prices
- `get_total_exposure()` = sum of abs(quantity) across all tickers
- Clearing: when quantity reaches 0, avg_entry_price resets to None

### 8. Risk Controls

| Control | Location | Trigger | Action |
|---------|----------|---------|--------|
| Global position limit | `_tick()` | `total_exposure > total_max_position` | Cancel ALL orders across all markets |
| Per-market stop loss | `_update_market()` | `(mid - avg_entry) * qty < -max_loss_cents` | Cancel orders for that market |
| Position-based size reduction | `generate_quote()` | `abs(qty) > 0.8 * max_position` | Halve order size on the side that increases exposure |
| Dry run mode | `_place_orders()` | `config.dry_run == True` | Log quotes but never call API |
| Cancel threshold | `_update_market()` | `bid_diff < threshold AND ask_diff < threshold` | Skip update to avoid order thrashing |

### 9. Shutdown

On SIGINT/SIGTERM or `engine.stop()`:
1. Set `self.running = False`
2. Cancel all orders for all tracked markets
3. Print final stats (quotes placed, orders cancelled, fills detected, positions)

---

## Configuration System

### Config Files

`config/demo.yaml` and `config/prod.yaml`. Loaded by `ConfigLoader` which:
1. Reads YAML
2. Expands `${VAR_NAME}` env vars (raises `ConfigValidationError` if missing)
3. Validates required sections: `execution`, `markets`, `api`
4. Converts to `ExecutionConfig` + `MarketConfig` dataclasses

### Key Parameters

**Execution parameters** (`ExecutionConfig`):

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `quote_interval` | 1.0s | Main loop sleep between ticks |
| `position_sync_interval` | 5.0s | How often to fetch positions from API |
| `total_max_position` | 500 (demo), 100 (prod) | Global exposure limit in contracts |
| `cancel_threshold` | 1 | Minimum price change (cents) to trigger requote |
| `dry_run` | true (demo), false (prod) | Paper trading mode |

**Per-market parameters** (`MarketConfig`):

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `gamma` | 0.1 | Risk aversion. Higher = wider spreads, stronger inventory pull |
| `sigma` | 2.0 | Volatility in cents. Higher = wider spreads |
| `k` | 1.5 | Order arrival decay. Higher = narrower spreads (expect fills at tight prices) |
| `base_size` | 10 (demo), 5 (prod) | Contracts per order |
| `max_position` | 100 (demo), 25 (prod) | Per-market inventory limit |
| `max_loss_cents` | 500 (demo), 100 (prod) | Stop loss threshold |

**Parameter tuning effects**:
- Increasing gamma: wider spreads, stronger reversion to flat, safer but fewer fills
- Increasing sigma: wider spreads (captures more per trade but fills less often)
- Increasing k: narrower spreads (more competitive but thinner edge)
- These parameters interact multiplicatively - changing one affects the others' impact

**API config**:
- `key_id`: Set via `${KALSHI_KEY_ID}` env var
- `private_key_file`: Path to RSA PEM file (kalshidemo.txt or kalshiprod.txt)
- `host`: API endpoint URL (demo vs prod)

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `KALSHI_KEY_ID` | Yes | API key ID for authentication |

Private keys are read from files specified in config, NOT from env vars.

---

## API Client (`src/client.py`)

### Authentication
Uses `kalshi_python_sync` SDK with RSA key signing. The `Configuration` object is set
up with `api_key_id` and `private_key_pem`, then creates `PortfolioApi`, `MarketApi`,
and `OrdersApi` instances.

### Key Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `get_orderbook(ticker, depth)` | `{'yes': [[price,qty],...], 'no': [...]}` | Uses raw HTTP due to SDK validation bug |
| `get_market(ticker)` | Market dict or None | Single market metadata |
| `get_markets(limit, status, ...)` | List of market dicts | Bulk market fetch |
| `get_trades(ticker, limit)` | List of trade dicts | For flow analysis |
| `place_order(ticker, side, action, qty, price, ...)` | Order dict or None | Limit orders only |
| `cancel_order(order_id)` | bool | Cancel single order |
| `cancel_all_orders(ticker)` | bool | Fetches all open, cancels each |
| `get_open_orders(ticker)` | List of order dicts | Open orders query |
| `get_positions()` | List of position dicts | All market positions |
| `get_balance()` | `{'balance': cents, 'portfolio_value': cents}` | Account balance |

### Error Handling Pattern
Every method is wrapped in try/except. On error, it prints the error and returns
an empty/None value. **No exceptions propagate.** This means the engine continues
running even when API calls fail. This is defensive but also means errors can be
silently swallowed.

### SDK Workaround (get_orderbook)
The `kalshi_python_sync` SDK has a validation bug: it expects string quantities in
orderbook responses but the API returns integers. The client bypasses the SDK for
orderbook fetches by making a raw `call_api("GET", url)` request. If that fails, it
falls back to reconstructing a minimal orderbook from the market endpoint's
top-of-book data (`yes_bid`, `no_bid` fields with quantity=1).

---

## Order Book Processing (`src/orderbook.py`)

### NO-to-YES Conversion
Kalshi orderbooks contain YES bids and NO bids. This module converts NO bids into
YES asks for a unified view:

```
NO bid at price X -> YES ask at price (100 - X)
```

Example: NO bid at 40c = YES ask at 60c (someone will pay 40c for NO, meaning
they're willing to sell YES at 60c).

### Calculated Metrics
- `best_bid`: Highest YES bid price
- `best_ask`: Lowest YES ask price (derived from NO bids)
- `mid_price`: (best_bid + best_ask) / 2
- `spread`: best_ask - best_bid
- `bid_depth` / `ask_depth`: Total contracts on each side

### Utility Methods
- `get_vwap(side, quantity)`: Volume-weighted average price to fill N contracts
- `get_cumulative_depth(side, levels)`: Total quantity across N best price levels
- `is_crossed()`: bid >= ask (shouldn't happen, indicates stale data or arb)
- `is_empty()` / `is_one_sided()`: Edge case detection

---

## Fees (`src/fees.py`)

Kalshi fee structure:
- **Maker fee**: 1.75% of potential profit = `0.0175 * contracts * P * (1-P)`
- **Taker fee**: 7.00% of potential profit = `0.07 * contracts * P * (1-P)`
- `P` = price as decimal (e.g., 0.48 for 48c)

Fees are lowest when prices are near 0 or 100 (potential profit is small) and highest
at 50c (maximum uncertainty). A round-trip (buy + sell) incurs fees on both legs.

**Breakeven spread at 50c**: ~1.8c for maker fees. At 25c or 75c: ~0.9c.

---

## Toxic Flow Detection (`src/flow.py`)

### IMPORTANT: NOT INTEGRATED INTO THE EXECUTION ENGINE

The `FlowAnalyzer` class is fully implemented and tested but is **never called** by
`execution.py` or `dashboard.py`. This is the most significant gap in the codebase.
The execution engine does not import or use flow.py at all.

### What It Does (When Integrated)
Analyzes recent trades to detect adverse selection (informed traders taking liquidity):

- **Run detection**: Consecutive trades in the same direction (5+ = toxic)
- **Trade imbalance**: Buy vs sell volume ratio (70%+ one-sided = toxic)
- **Price momentum**: Rapid price movement (5c+ = toxic)
- **Volume spikes**: Unusual activity (3x average = spike)

Produces a `toxicity_score` (0-100) and a `QuoteAdjustment` recommendation:
- Score >= 80: **PULL** all quotes, cooldown 30s
- Score >= 60: **WIDEN** spread 2x, reduce size 0.5x, cooldown 10s
- Score >= 40: **REDUCE** spread 1.5x, reduce size 0.75x, cooldown 5s
- Score < 40: **NORMAL** quoting

### How to Integrate
To wire flow detection into the execution engine, you would need to:
1. Import `FlowAnalyzer` and `parse_kalshi_trades` in `execution.py`
2. Create a `FlowAnalyzer` instance in `ExecutionEngine.__init__`
3. In `_update_market()`, fetch recent trades via `client.get_trades(ticker)`
4. Parse and feed them to the analyzer
5. Call `recommend_adjustment(ticker)` before generating quotes
6. Apply the adjustment's `spread_multiplier` and `size_multiplier` to the quote
7. Respect `cooldown_seconds` (skip quoting during cooldown)

---

## Dashboard (`dashboard.py`)

Flask + SocketIO web UI running on port 8080. Key aspects:

- Uses **global mutable state** (`DashboardState`, `client`, `config`, etc.)
- Trading loop runs in a `threading.Thread(daemon=True)`
- State updates emitted via `socketio.emit('state_update', ...)` every tick
- Events (quotes, trades, errors) emitted individually via `socketio.emit('event', ...)`
- Dashboard HTML is an inline template string with embedded JavaScript
- The dashboard duplicates the execution engine logic (its own `update_market`,
  `place_orders`, `cancel_orders`, `sync_positions` functions) rather than using
  `ExecutionEngine` directly

### Dashboard vs Engine Differences
The dashboard's trading loop is functionally similar to `ExecutionEngine` but:
- Uses depth=10 for orderbooks instead of depth=5
- Does NOT check stop loss (the dashboard's `update_market` omits this check)
- Does NOT check global position limits within the loop (no `total_exposure` check)
- Stores extra state for the UI (orderbook snapshots, quote history, event log)
- Handles errors by emitting error events instead of just logging

This duplication means **fixes to one must be manually applied to the other**.

---

## Known Bugs and Issues

### Critical

1. **Flow detection not integrated** (`flow.py`): The entire toxic flow protection
   module is implemented and tested but never called. The bot has zero protection
   against informed traders. See "How to Integrate" section above.

2. **Dashboard missing risk controls**: The dashboard's `update_market()` function
   does not check stop loss or global position limits. Only the headless
   `ExecutionEngine` has these checks. If you run via the dashboard (the default Docker
   entry point), you are running **without stop-loss protection**.

3. **Code duplication between dashboard and engine**: `dashboard.py` reimplements the
   trading loop rather than using `ExecutionEngine`. Any bug fix or feature added to
   one must be manually mirrored in the other.

### Moderate

4. **Position sync race condition**: Positions sync every 5s but quotes update every
   1s. Between syncs, the bot uses stale inventory data. If an order fills, the next
   1-4 ticks will generate quotes based on the old position, potentially placing orders
   that increase exposure beyond desired limits.

5. **Stop loss uses mid price, not execution price**: PnL is calculated as
   `(mid_price - avg_entry_price) * quantity`. In an illiquid market, the mid may not
   reflect achievable exit prices. Actual losses could exceed the stop loss threshold.

6. **Order cancellation not verified**: `_cancel_orders()` calls `client.cancel_order()`
   for each order ID and clears the stored IDs regardless of whether the cancel
   succeeded. If the API call fails, the order remains live but the bot thinks it was
   cancelled. This could result in ghost orders that accumulate fills.

7. **Position sync overwrites without averaging**: `_sync_positions()` replaces the
   entire Position object with the API's reported quantity but does NOT recalculate
   `avg_entry_price` from the API data consistently. In `execution.py`, it creates a
   new `Position(ticker, qty)` with `avg_entry_price=None`. The dashboard version does
   use `avg_price` from the API, but the headless engine loses entry price tracking
   after every sync.

### Minor

8. **Stats dict not thread-safe**: `stats['quotes'] += 1` is a read-modify-write
   operation. In the dashboard (multi-threaded), this could lose increments under
   contention. Only affects metrics, not trading.

9. **`__repr__` bug in OrderBook**: `orderbook.py:247` has a string formatting error -
   the f-string contains `if self.mid_price else 'N/A'` outside the format braces,
   which will produce malformed output.

10. **Config tickers are placeholders**: `config/demo.yaml` uses
    `REPLACE_WITH_DEMO_MARKET_TICKER` as the ticker. This must be replaced with an
    actual active market ticker before the bot can do anything useful.

---

## Rules for Agents Working on This Codebase

### Before Making Changes

1. **Run the tests** before and after changes: `pytest tests/ -v`
2. **Read both `execution.py` AND `dashboard.py`** if you're modifying trading logic.
   They duplicate the same concepts and both need to stay consistent.
3. **Understand the Kalshi bid-only model**: There are no ask orders. A YES ask at Xc
   is placed as a NO bid at (100-X)c. Get this wrong and you'll place orders at the
   wrong prices.
4. **Check if flow.py is integrated** before assuming it is. As of now, it is not.

### When Modifying Trading Logic

- Any change to `_update_market()` in `execution.py` likely needs a corresponding
  change in `update_market()` in `dashboard.py` (and vice versa).
- When modifying quote generation, verify that:
  - Bid is always < ask after all rounding and clamping
  - Prices are integers in range [1, 99]
  - The spread never goes to zero or negative
  - Size is always >= 1
- The cancel-replace pattern (`_cancel_orders` then `_place_orders`) is intentional.
  Do not try to modify orders in place -- Kalshi doesn't support order amendment.

### When Modifying the API Client

- All methods must be defensive (try/except, return empty/None on error).
- The `get_orderbook` method bypasses the SDK intentionally due to a validation bug.
  Do not "fix" this by going back to the SDK method unless the SDK bug is confirmed
  resolved in `kalshi_python_sync`.
- Handle both Pydantic v1 (`dict()`) and v2 (`model_dump()`) for SDK responses.
- The `place_order` method uses `yes_price` or `no_price` based on `side`. Setting
  the wrong one to a value (instead of None) will cause API errors or wrong prices.

### When Modifying Configuration

- The config loader only expands env vars that match the exact pattern `${VAR_NAME}`
  (starts with `${`, ends with `}`). Partial substitution is not supported.
- Every market must have a `ticker` field. All other per-market fields have defaults.
- Adding new config fields requires updating: the YAML files, `_validate_config()`,
  `to_execution_config()`, and the relevant dataclass.

### When Adding Tests

- Follow existing patterns: use `pytest` fixtures, mock the API client, test edge cases
  (empty orderbook, zero inventory, max inventory, boundary prices).
- The flow tests (`test_flow.py`) are the most comprehensive example of test patterns
  in this codebase.
- Test both valid and invalid inputs for any quote or orderbook logic.
- Fee calculations should be tested with round-trip scenarios.

### Deployment

- Tests must pass before deployment (`deploy.sh` enforces this unless `--skip-tests`)
- Private keys (.txt files) are in `.gitignore` - never commit them
- The `KALSHI_KEY_ID` env var must be set in the environment or `.env` file
- Docker compose mounts config and key files as read-only volumes
- The default Docker command runs the dashboard with `--env prod --live --yes`
- Use `scripts/bot.sh stop` for emergency stop (cancels orders, stops container)

---

## State Transitions Summary

### Order Lifecycle

```
NO ORDERS
  |
  v  [valid mid price + valid quote + above cancel_threshold]
ORDERS ACTIVE (yes_order_id + no_order_id stored)
  |
  |---> [price moved >= threshold] --> CANCEL old -> PLACE new -> ORDERS ACTIVE
  |---> [fill detected via sync]   --> position changes, next quote adjusts
  |---> [mid invalid / quote None] --> CANCEL -> NO ORDERS
  |---> [stop loss triggered]      --> CANCEL -> NO ORDERS (market paused)
  |---> [position limit exceeded]  --> CANCEL ALL -> NO ORDERS (all markets)
  |---> [shutdown signal]          --> CANCEL ALL -> EXIT
```

### Position Lifecycle

```
FLAT (qty=0, avg_entry=None)
  |
  v  [YES bid fills -> buy YES]
LONG (qty>0, avg_entry=fill_price)
  |
  |  Quotes shift: reservation drops below mid (r = mid - q*gamma*sigma^2)
  |  This makes the ask more competitive, encouraging exit
  |
  |---> [NO bid fills -> economically sell YES] --> FLAT (profit captured)
  |---> [another YES bid fills]                 --> LONGER (avg_entry recalculated)
  |---> [stop loss]                             --> orders cancelled, position remains
  v
Similar for SHORT (qty<0) but in reverse direction
```

### Bot Lifecycle

```
INIT -> LOADING CONFIG -> CLIENT AUTH -> RUNNING (loop)
                                            |
                                            |---> TICK -> SYNC -> UPDATE MARKETS -> SLEEP
                                            |                         |
                                            |                         v
                                            |              [for each market: fetch OB,
                                            |               generate quote, place orders]
                                            |
                                            v
                                         SHUTDOWN -> CANCEL ALL -> PRINT STATS -> EXIT
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_quotes.py -v
pytest tests/test_execution.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

All tests use mocks for the API client. No tests make real API calls. The test suite
covers: config validation, AS model math, orderbook parsing, fee calculations, engine
lifecycle, and flow detection. Dashboard WebSocket behavior is not tested.

---

## Quick Reference: Common Tasks

**Add a new market**: Add an entry to the `markets` list in the appropriate YAML config
file with at minimum a `ticker` field. All AS parameters have defaults.

**Change quoting aggressiveness**: Adjust `gamma` (risk aversion), `sigma` (volatility),
or `k` (arrival intensity) in the market config. Lower gamma and sigma = tighter
spreads = more aggressive.

**Emergency stop**: `./scripts/bot.sh stop` or Ctrl+C. Both trigger order cancellation.

**Switch from dry run to live**: Either set `dry_run: false` in the YAML config, or
pass `--live` flag to the entry point. For prod+live, a confirmation prompt appears
unless `--yes` is passed.

**Check if orders are actually being placed**: Look for `[DRY]` prefix in logs. If
present, orders are being simulated. If absent and you see "Placed TICKER bid/ask",
real orders are going to the API.
