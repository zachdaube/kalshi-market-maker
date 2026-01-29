# Kalshi Market Maker

Automated market making bot for Kalshi prediction markets using the Avellaneda-Stoikov optimal quoting model. Includes a real-time web dashboard for monitoring.

## Requirements

- Python 3.11+
- Kalshi API credentials (key ID + private key)
- Docker (for cloud deployment)

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Get API Credentials

1. Go to https://kalshi.com/account/api (or https://demo.kalshi.co for demo)
2. Generate an API key pair
3. Download the private key file
4. Save the private key as:
   - `kalshidemo.txt` for demo environment
   - `kalshiprod.txt` for production

### 3. Configure

Edit `config/demo.yaml` or `config/prod.yaml`:

```yaml
markets:
  - ticker: YOUR_MARKET_TICKER  # Find at kalshi.com/markets
    enabled: true
    gamma: 0.1      # Risk aversion
    sigma: 2.0      # Volatility estimate
    k: 1.5          # Order arrival decay
    base_size: 10   # Contracts per order
    max_position: 100
    max_loss_cents: 500.0
```

### 4. Run Locally

**With Dashboard (Recommended):**
```bash
# Dashboard + bot on http://localhost:8080
python dashboard.py --env demo

# Live trading with dashboard
python dashboard.py --env demo --live --port 8080
```

**Headless (no dashboard):**
```bash
python run_market_maker.py --env demo
python run_market_maker.py --env demo --live
```

## Cloud Deployment (DigitalOcean)

Deploy to a cloud server so the bot runs 24/7 without your computer being on.

### Initial Setup

1. Create a DigitalOcean droplet (Ubuntu 24.04, $6/month is sufficient)
2. Update the IP address in `scripts/deploy.sh` and `scripts/bot.sh`

### Deploy

```bash
./scripts/deploy.sh
```

This will:
1. Run all tests locally to verify the code works
2. Set up Docker on the server (first time only)
3. Copy project files to the server
4. Build and start the bot

### Control the Bot

| Command | Description |
|---------|-------------|
| `./scripts/bot.sh stop` | **EMERGENCY STOP** - Immediately stop the bot |
| `./scripts/bot.sh start` | Start the bot |
| `./scripts/bot.sh restart` | Restart the bot |
| `./scripts/bot.sh status` | Check if bot is running |
| `./scripts/bot.sh logs` | Stream live logs (Ctrl+C to exit) |
| `./scripts/bot.sh logs-tail` | Show last 50 log lines |
| `./scripts/bot.sh ssh` | SSH into the server |

### Access Dashboard

Once deployed, access the dashboard at: `http://YOUR_DROPLET_IP:8080`

## Dashboard

The web dashboard provides real-time visualization of:
- **Statistics**: Quotes placed, fills, cancels, P&L
- **Order Book**: Live bid/ask levels with depth
- **Positions**: Current inventory for each market
- **Active Quotes**: Your bid/ask prices and sizes
- **Event Log**: Trade and quote history

## How It Works

The bot uses the Avellaneda-Stoikov model to calculate optimal quotes:

1. **Reservation Price**: `r = mid - inventory * gamma * sigma^2`
   - Adjusts fair value based on inventory to encourage mean reversion

2. **Optimal Spread**: `spread = (2/gamma) * ln(1 + gamma/k)`
   - Calibrated to order arrival rates and risk preferences

3. **Quote Placement**: Posts bid at `r - spread/2`, ask at `r + spread/2`

See `docs/AVELLANEDA_STOIKOV_GUIDE.md` for detailed parameter tuning.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gamma` | 0.1 | Risk aversion. Higher = wider spreads when positioned |
| `sigma` | 2.0 | Volatility estimate in cents |
| `k` | 1.5 | Order arrival decay. Lower = expect fills at wider spreads |
| `base_size` | 10 | Contracts per order |
| `max_position` | 100 | Max inventory before pulling quotes |
| `max_loss_cents` | 500 | Stop loss threshold |

## Project Structure

```
kalshi-market-maker/
├── dashboard.py           # Web dashboard + bot (main entry)
├── run_market_maker.py    # Headless bot
├── Dockerfile
├── docker-compose.yml
├── scripts/
│   ├── deploy.sh          # Deploy to cloud server
│   └── bot.sh             # Control bot (start/stop/logs)
├── src/
│   ├── client.py          # Kalshi API wrapper
│   ├── execution.py       # Main trading loop
│   ├── quotes.py          # Avellaneda-Stoikov model
│   ├── orderbook.py       # Order book processing
│   ├── fees.py            # Fee calculations
│   ├── flow.py            # Toxic flow detection
│   └── config_loader.py   # Configuration loading
├── config/
│   ├── demo.yaml          # Demo environment config
│   └── prod.yaml          # Production config
├── tests/                 # Unit tests
└── docs/
    ├── AVELLANEDA_STOIKOV_GUIDE.md
    └── KALSHI_MECHANICS.md
```

## Testing

Run tests before deploying (deploy script does this automatically):

```bash
pytest tests/ -v
```

## Security

API credentials are protected via `.gitignore`. Never commit:
- Private key files (`*.txt`, `*.pem`, `*.key`)
- Environment files (`.env`)
- Credential configs

**After deployment**, consider:
- Changing your droplet password
- Setting up SSH key authentication
- Restricting dashboard access with a firewall

## Risk Warning

Market making involves financial risk. Start with:
- Demo environment first
- Small position sizes
- Tight stop losses

Monitor continuously and be ready to stop the bot.

## License

MIT License - Use at your own risk.
