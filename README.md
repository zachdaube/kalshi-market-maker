# Kalshi Market Maker

An automated market maker for [Kalshi](https://kalshi.com) prediction markets using the **Avellaneda-Stoikov** optimal quoting model. The bot continuously posts two-sided quotes on configured markets, adjusts prices based on inventory risk, and captures the bid-ask spread as profit.

Includes a **real-time web dashboard**, a **market scanner** for finding profitable opportunities, and full **Docker deployment** support.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Running the Bot](#running-the-bot)
- [Market Scanner](#market-scanner)
- [Configuration](#configuration)
- [Parameter Tuning](#parameter-tuning)
- [Dashboard](#dashboard)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Risk Warning](#risk-warning)

---

## How It Works

### The Avellaneda-Stoikov Model

The bot uses two core equations to calculate where to place orders:

**1. Reservation Price** — an inventory-adjusted "fair value":

```
r = mid_price - inventory * gamma * sigma^2
```

When you're **long** (holding YES contracts), the reservation price drops below the market mid, making your ask more competitive and encouraging you to sell. When **short**, it rises, encouraging you to buy. This creates a natural mean-reversion toward flat inventory.

**2. Optimal Spread** — how wide to quote around the reservation:

```
spread = (2 / gamma) * ln(1 + gamma / k)
```

The bid goes at `r - spread/2` and the ask at `r + spread/2`.

### Kalshi's Order Format

Kalshi only has **bid** orders on both YES and NO sides. There are no explicit asks. To provide two-sided liquidity:

- **YES bid at 48c** = straightforward buy YES
- **YES ask at 52c** = place a **NO bid at 48c** (100 - 52 = 48)

If both fill, you pay 48 + 48 = 96c and hold 1 YES + 1 NO. One settles at $1, the other at $0. Profit: 4c minus fees.

### The Trading Loop

Every tick (default 1 second), for each market:

```
1. Sync positions from API (every 5s)
2. Check global position limit
3. Fetch orderbook
4. Check stop loss
5. Analyze trade flow for toxicity
6. Generate optimal quote (AS model)
7. Apply flow adjustments (widen/reduce if toxic)
8. Cancel old orders, place new ones
```

---

## Architecture

```
                                        +------------------+
                                        |   Kalshi API     |
                                        +--------+---------+
                                                 |
                                    auth / orders / market data
                                                 |
                                        +--------+---------+
                                        |   client.py      |
                                        |  (API wrapper)   |
                                        +--------+---------+
                                                 |
                    +----------------------------+----------------------------+
                    |                            |                            |
          +---------+--------+       +-----------+----------+      +---------+---------+
          |  execution.py    |       |   dashboard.py       |      | trading_worker.py |
          |  (headless)      |       |  (Flask + SocketIO)  |      | (Docker worker)   |
          +------------------+       +----------------------+      +-------------------+
                    |                            |                            |
          All three use the same core modules:   |                            |
                    |                            |                            |
                    +----------------------------+----------------------------+
                                                 |
                    +----------------------------+----------------------------+
                    |              |              |              |             |
              +-----+----+  +----+-----+  +-----+----+  +-----+----+  +-----+----+
              | quotes.py |  |orderbook |  | fees.py  |  | flow.py  |  | config   |
              | (AS model)|  |  .py     |  |          |  | (toxic   |  | _loader  |
              |           |  | (parser) |  |          |  |  flow)   |  |  .py     |
              +-----------+  +----------+  +----------+  +----------+  +----------+

              +------------------+
              |  scanner.py      |   <-- standalone, uses client.py
              |  (market finder) |
              +------------------+
```

**Three entry points** exist for running the bot. All three share the same core trading logic:

| Entry Point | Purpose | Use Case |
|---|---|---|
| `dashboard.py` | Web UI + trading bot | Development, monitoring |
| `run_market_maker.py` | Headless trading bot | Simple local runs |
| `trading_worker.py` | Docker-optimized worker | Production deployment |

**`scan_markets.py`** is a separate utility that scans all open Kalshi markets and scores them for market-making profitability.

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Kalshi API Credentials

1. Sign up at [kalshi.com](https://kalshi.com) (or [demo.kalshi.co](https://demo.kalshi.co) for paper trading)
2. Go to **Settings > API** and generate an API key pair
3. Download the private key file
4. Save it in the project root:
   - `kalshidemo.txt` for demo environment
   - `kalshiprod.txt` for production

### 3. Set Your API Key ID

```bash
export KALSHI_KEY_ID=your-api-key-id-here
```

Or edit it directly in `config/demo.yaml` / `config/prod.yaml`.

### 4. Find a Market

Use the scanner to find good markets:

```bash
python scan_markets.py --env demo --top 10
```

Or browse [kalshi.com/markets](https://kalshi.com/markets) and copy a ticker.

### 5. Configure

Edit `config/demo.yaml` and replace the placeholder ticker:

```yaml
markets:
  - ticker: KXEVENT-TICKER-HERE   # Replace with a real ticker
    enabled: true
    gamma: 0.1
    sigma: 2.0
    k: 1.5
    base_size: 10
    max_position: 100
    max_loss_cents: 500.0
```

### 6. Run

```bash
# Dry run (no real orders, just logs quotes)
python dashboard.py --env demo

# Open http://localhost:8080 to see the dashboard
```

---

## Running the Bot

### Dry Run (Paper Trading)

See what the bot *would* do without placing any orders:

```bash
# With dashboard
python dashboard.py --env demo

# Headless (terminal only)
python run_market_maker.py --env demo
```

Look for `[DRY]` in the logs — this means orders are being simulated. The dashboard still shows live orderbooks, quotes, and flow analysis.

### Demo Live Trading

Place real orders on Kalshi's demo exchange (paper money):

```bash
python dashboard.py --env demo --live
```

This uses the demo API (`demo-api.kalshi.co`) with virtual funds. Safe for testing the full order lifecycle.

### Production Live Trading

Place real orders with real money:

```bash
python dashboard.py --env prod --live
```

A confirmation prompt will appear. Add `--yes` to skip it (for automated deployments):

```bash
python trading_worker.py --env prod --live --yes
```

### Docker

```bash
docker-compose up -d
```

This runs `trading_worker.py` in a container with the production config. See [Deployment](#deployment) for cloud setup.

---

## Market Scanner

The scanner fetches all open Kalshi markets and scores them on six criteria:

| Criterion | Weight | What It Measures |
|---|---|---|
| **Spread** | 30% | Natural bid-ask spread (sweet spot: 4-8c) |
| **Volume** | 20% | 24h trading volume (sweet spot: 100-10k contracts) |
| **Fee Efficiency** | 15% | How much spread survives after round-trip maker fees |
| **Time to Expiry** | 15% | Days until settlement (sweet spot: 7-30 days) |
| **Liquidity** | 10% | Open interest and dollar book depth |
| **Price Level** | 10% | Distance from extremes (avoid <5c or >95c) |

### Usage

```bash
# Scan with defaults (top 20 markets)
python scan_markets.py --env demo

# Filter: minimum 100 daily volume, 3c+ spread
python scan_markets.py --env prod --min-volume 100 --min-spread 3

# Output YAML config for the top 5 markets (paste into your config)
python scan_markets.py --env prod --yaml --yaml-count 5

# Filter by event or series
python scan_markets.py --env prod --event KXELECTION
```

### Example Output

```
Rank  Score  Ticker                         Bid  Ask  Sprd   Vol24h      OI  Days  Title
---------------------------------------------------------------------------------------------------------------------
1     82.3   KXEVENT-26FEB-T042             45    52     7      850     320  18.3  Will X happen by Feb 26?
2     79.1   KXWEATHER-MAR-RAIN             30    36     6     1200     540  25.1  March rainfall above average?
3     76.5   KXPOLITICS-CONFIRM             62    68     6      430     180  12.7  Senate confirmation vote?

Suggested Parameters for Top Markets:
Ticker                         gamma   sigma       k   size  max_pos
----------------------------------------------------------------------
KXEVENT-26FEB-T042              0.10     4.2     1.5      5       25
KXWEATHER-MAR-RAIN              0.10     3.6     2.0      7       25
KXPOLITICS-CONFIRM              0.10     3.6     1.5      5       25
```

The `--yaml` flag outputs ready-to-paste market configs with tuned parameters.

---

## Configuration

### Config Files

| File | Purpose |
|---|---|
| `config/demo.yaml` | Demo environment (paper trading) |
| `config/prod.yaml` | Production (real money) |

### Execution Parameters

```yaml
execution:
  quote_interval: 1.0           # Seconds between ticks
  position_sync_interval: 5.0   # Seconds between API position syncs
  total_max_position: 500       # Global exposure limit (all markets combined)
  cancel_threshold: 1           # Min price move (cents) to trigger requote
  dry_run: true                 # true = simulate, false = real orders
```

### Per-Market Parameters

```yaml
markets:
  - ticker: KXEVENT-TICKER
    enabled: true
    gamma: 0.1           # Risk aversion
    sigma: 2.0           # Volatility estimate (cents)
    k: 1.5               # Order arrival intensity
    base_size: 10        # Contracts per order
    max_position: 100    # Max inventory for this market
    max_loss_cents: 500  # Stop loss threshold (cents)
```

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `KALSHI_KEY_ID` | Yes | API key ID for authentication |

Private keys are read from files (`kalshidemo.txt` / `kalshiprod.txt`), not environment variables.

---

## Parameter Tuning

### Gamma (Risk Aversion)

Controls how aggressively inventory is managed and how wide spreads are:

| Gamma | Behavior |
|---|---|
| 0.05 | Aggressive — tight spreads, slow inventory correction |
| 0.10 | Balanced — standard operation |
| 0.15 | Conservative — wider spreads, faster reversion to flat |
| 0.20+ | Very conservative — very wide spreads, strong inventory pull |

### Sigma (Volatility)

Estimated price uncertainty in cents. Wider sigma = wider spreads:

| Sigma | Market Type |
|---|---|
| 1.0 | Stable, slow-moving markets |
| 2.0 | Normal prediction markets |
| 3.0-5.0 | Volatile or news-driven markets |

### K (Order Arrival Intensity)

How quickly order flow decays at wider prices. Higher k = tighter spreads:

| K | Interpretation |
|---|---|
| 0.5-1.0 | Low activity — wide spreads needed to protect |
| 1.5 | Moderate activity — standard |
| 2.0-3.0 | High activity — can quote tighter |

### Interaction Effects

These parameters interact multiplicatively:
- Doubling sigma has the same spread effect as quadrupling gamma (sigma is squared)
- High gamma + high sigma = very wide spreads (may never fill)
- Low gamma + high k = very tight spreads (may not cover fees)

### Fee Awareness

The bot automatically enforces a minimum spread that covers round-trip maker fees:

| Mid Price | Round-trip Fee | Min Profitable Spread |
|---|---|---|
| 50c | ~0.88c | 2c |
| 25c / 75c | ~0.66c | 1c |
| 10c / 90c | ~0.32c | 1c |

---

## Dashboard

The web dashboard runs at `http://localhost:8080` and provides real-time visibility into:

- **Bot status** — running/stopped, dry run/live, uptime
- **Statistics** — quotes placed, fills detected, cancels, P&L
- **Order book** — live bid/ask depth with your quotes highlighted
- **Positions** — current inventory per market with unrealized P&L
- **Flow analysis** — toxicity score and current adjustment action
- **Active quotes** — your bid/ask prices, sizes, reservation price
- **AS model state** — reservation price shift, spread calculation
- **Event log** — color-coded history of quotes, fills, and errors

```bash
python dashboard.py --env demo --port 8080
```

The dashboard updates every tick via WebSocket. No page refresh needed.

---

## Deployment

### Docker (Local)

```bash
docker-compose up -d        # Start
docker-compose logs -f      # Stream logs
docker-compose down         # Stop
```

### Cloud (DigitalOcean)

#### Prerequisites

1. Create a DigitalOcean droplet (Ubuntu 24.04, $6/month is sufficient)
2. Update the IP address in `scripts/deploy.sh` and `scripts/bot.sh`

#### Deploy

```bash
./scripts/deploy.sh
```

This runs tests locally, copies files to the server, builds the Docker image, and starts the bot.

#### Remote Control

| Command | Description |
|---|---|
| `./scripts/bot.sh stop` | **Emergency stop** (cancels all orders) |
| `./scripts/bot.sh start` | Start the bot |
| `./scripts/bot.sh restart` | Restart |
| `./scripts/bot.sh status` | Check if running |
| `./scripts/bot.sh logs` | Stream live logs |
| `./scripts/bot.sh logs-tail` | Last 50 log lines |
| `./scripts/bot.sh ssh` | SSH into server |

#### Access Dashboard Remotely

After deployment: `http://YOUR_DROPLET_IP:8080`

---

## Project Structure

```
kalshi-market-maker/
├── dashboard.py              # Web dashboard + trading bot
├── run_market_maker.py       # Headless trading bot
├── trading_worker.py         # Docker-optimized worker
├── scan_markets.py           # Market scanner CLI
│
├── src/
│   ├── client.py             # Kalshi API wrapper (auth, orders, market data)
│   ├── execution.py          # Trading engine (tick loop, state, risk controls)
│   ├── quotes.py             # AS model (reservation price, spread, quote gen)
│   ├── orderbook.py          # Order book parsing (NO->YES conversion, metrics)
│   ├── fees.py               # Fee calculations (maker/taker)
│   ├── flow.py               # Toxic flow detection (runs, imbalance, momentum)
│   ├── scanner.py            # Market scanner (scoring, parameter suggestion)
│   └── config_loader.py      # YAML config with env var expansion
│
├── config/
│   ├── demo.yaml             # Demo environment
│   └── prod.yaml             # Production environment
│
├── tests/                    # 175 unit tests (all mocked, no API calls)
│   ├── test_quotes.py
│   ├── test_execution.py
│   ├── test_orderbook.py
│   ├── test_fees.py
│   ├── test_flow.py
│   ├── test_config.py
│   └── test_scanner.py
│
├── scripts/
│   ├── deploy.sh             # Deploy to DigitalOcean
│   └── bot.sh                # Remote bot control
│
├── docs/
│   ├── AVELLANEDA_STOIKOV_GUIDE.md
│   └── KALSHI_MECHANICS.md
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Testing

```bash
# Run all 175 tests
pytest tests/ -v

# Run specific module
pytest tests/test_quotes.py -v
pytest tests/test_scanner.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

All tests use mocked API clients. No real API calls are made during testing.

---

## Risk Controls

| Control | Trigger | Action |
|---|---|---|
| **Global position limit** | Total exposure > `total_max_position` | Cancel ALL orders across all markets |
| **Per-market stop loss** | Unrealized P&L < `-max_loss_cents` | Cancel orders for that market |
| **Size reduction** | Position > 80% of `max_position` | Halve order size on the risky side |
| **Toxic flow: PULL** | Toxicity score > 80 | Pull all quotes, 30s cooldown |
| **Toxic flow: WIDEN** | Toxicity score > 60 | Double spread, halve size, 10s cooldown |
| **Toxic flow: REDUCE** | Toxicity score > 40 | 1.5x spread, 0.75x size, 5s cooldown |
| **Dry run mode** | `dry_run: true` | Log quotes but never call the API |
| **Cancel threshold** | Price move < `cancel_threshold` | Skip requote to avoid order thrashing |
| **Fee floor** | Spread < round-trip fee | Widen to minimum profitable spread |

---

## Security

- Private key files (`.txt`, `.pem`, `.key`) are in `.gitignore` — never committed
- API key IDs are loaded via environment variables or config files
- Docker volumes mount keys as read-only
- The dashboard runs without authentication — restrict access with a firewall in production

---

## Risk Warning

Market making on prediction markets involves real financial risk. You can lose money. Start with:

1. **Demo environment** first (paper money)
2. **Dry run mode** to validate behavior
3. **Small position sizes** (`base_size: 3-5`)
4. **Tight stop losses** (`max_loss_cents: 50-100`)
5. **Continuous monitoring** via the dashboard

Understand the AS model parameters before going live. The bot is a tool, not a guaranteed profit strategy.

## License

MIT License - Use at your own risk.
