"""
Kalshi Market Maker Dashboard

Real-time web dashboard for monitoring the trading bot.
Displays: positions, P&L, orderbook, trades, and bot status.
"""

import os
import sys
import json
import time
import threading
import argparse
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from collections import deque

from flask import Flask, render_template_string
from flask_socketio import SocketIO

from src.client import KalshiClient
from src.config_loader import ConfigLoader
from src.orderbook import OrderBook
from src.quotes import ASParams, Position, PositionTracker, generate_quote
from src.execution import MarketConfig, ExecutionConfig, OrderState

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


@dataclass
class DashboardState:
    """Global state for the dashboard."""
    running: bool = False
    dry_run: bool = True
    environment: str = "demo"
    start_time: Optional[float] = None

    # Market data
    orderbooks: Dict[str, dict] = None
    positions: Dict[str, dict] = None
    quotes: Dict[str, dict] = None

    # Stats
    total_quotes: int = 0
    total_fills: int = 0
    total_cancels: int = 0
    pnl_cents: float = 0.0

    # History (last 100 events)
    trade_history: deque = None
    quote_history: deque = None

    def __post_init__(self):
        self.orderbooks = {}
        self.positions = {}
        self.quotes = {}
        self.trade_history = deque(maxlen=100)
        self.quote_history = deque(maxlen=100)


# Global state
state = DashboardState()
client: Optional[KalshiClient] = None
config: Optional[ExecutionConfig] = None
position_tracker = PositionTracker()
order_states: Dict[str, OrderState] = {}


def emit_state():
    """Emit current state to all connected clients."""
    socketio.emit('state_update', {
        'running': state.running,
        'dry_run': state.dry_run,
        'environment': state.environment,
        'uptime': int(time.time() - state.start_time) if state.start_time else 0,
        'stats': {
            'quotes': state.total_quotes,
            'fills': state.total_fills,
            'cancels': state.total_cancels,
            'pnl_cents': state.pnl_cents
        },
        'positions': state.positions,
        'quotes': state.quotes,
        'orderbooks': state.orderbooks,
        'trade_history': list(state.trade_history),
        'quote_history': list(state.quote_history),
        'timestamp': datetime.now().isoformat()
    })


def log_event(event_type: str, data: dict):
    """Log an event and emit to dashboard."""
    event = {
        'type': event_type,
        'data': data,
        'timestamp': datetime.now().isoformat()
    }

    if event_type == 'trade':
        state.trade_history.appendleft(event)
    elif event_type == 'quote':
        state.quote_history.appendleft(event)

    socketio.emit('event', event)


def trading_loop():
    """Main trading loop running in background thread."""
    global state, client, config

    state.running = True
    state.start_time = time.time()
    last_sync = 0

    while state.running:
        try:
            # Sync positions periodically
            if time.time() - last_sync > config.position_sync_interval:
                sync_positions()
                last_sync = time.time()

            # Update each market
            for ticker, mc in config.markets.items():
                if mc.enabled:
                    update_market(ticker, mc)

            # Emit state to dashboard
            emit_state()

            time.sleep(config.quote_interval)

        except Exception as e:
            log_event('error', {'message': str(e)})
            time.sleep(1)

    # Cleanup on stop
    for ticker in order_states:
        cancel_orders(ticker)


def sync_positions():
    """Sync positions from API."""
    global state, client

    try:
        api_positions = client.get_positions()
        for p in api_positions:
            ticker = p.get('ticker')
            qty = p.get('position', 0)
            avg_price = p.get('average_price_paid', 0)

            current = position_tracker.get_position(ticker)
            if current.quantity != qty:
                delta = abs(qty - current.quantity)
                state.total_fills += delta
                log_event('trade', {
                    'ticker': ticker,
                    'old_qty': current.quantity,
                    'new_qty': qty,
                    'delta': delta
                })

            position_tracker.positions[ticker] = Position(ticker, qty, avg_price if avg_price else None)
            state.positions[ticker] = {
                'quantity': qty,
                'avg_price': avg_price,
                'side': 'LONG' if qty > 0 else 'SHORT' if qty < 0 else 'FLAT'
            }

    except Exception as e:
        log_event('error', {'message': f'Position sync error: {e}'})


def update_market(ticker: str, mc: MarketConfig):
    """Update quotes for a single market."""
    global state, client, order_states

    if ticker not in order_states:
        order_states[ticker] = OrderState(ticker=ticker)
    os_state = order_states[ticker]

    # Fetch orderbook
    try:
        raw_ob = client.get_orderbook(ticker, depth=10)
        if not raw_ob:
            return
        ob = OrderBook(ticker, raw_ob)
    except Exception as e:
        log_event('error', {'message': f'Orderbook error {ticker}: {e}'})
        return

    # Store orderbook for dashboard
    state.orderbooks[ticker] = {
        'bids': [{'price': q.price, 'quantity': q.quantity} for q in ob.yes_bids[:10]],
        'asks': [{'price': q.price, 'quantity': q.quantity} for q in ob.yes_asks[:10]],
        'mid': ob.mid_price,
        'spread': ob.spread,
        'best_bid': ob.best_bid,
        'best_ask': ob.best_ask
    }

    if ob.mid_price is None:
        cancel_orders(ticker)
        return

    # Get position
    pos = position_tracker.get_position(ticker)

    # Generate quote using AS model
    params = ASParams(
        gamma=mc.gamma,
        sigma=mc.sigma,
        k=mc.k,
        max_position=mc.max_position,
        base_size=mc.base_size
    )
    quote = generate_quote(ticker, ob.mid_price, pos, params)

    if not quote:
        cancel_orders(ticker)
        return

    # Store quote for dashboard
    state.quotes[ticker] = {
        'bid_price': quote.bid.price_cents,
        'bid_qty': quote.bid.quantity,
        'ask_price': quote.ask.price_cents,
        'ask_qty': quote.ask.quantity,
        'reservation_price': quote.reservation_price,
        'spread': quote.ask.price_cents - quote.bid.price_cents
    }

    # Check if we need to update orders
    if os_state.last_quote:
        bid_diff = abs(quote.bid.price_cents - os_state.last_quote.bid.price_cents)
        ask_diff = abs(quote.ask.price_cents - os_state.last_quote.ask.price_cents)
        if bid_diff < config.cancel_threshold and ask_diff < config.cancel_threshold:
            return

    # Place orders
    place_orders(ticker, quote, os_state)


def place_orders(ticker: str, quote, os_state: OrderState):
    """Place or update orders."""
    global state, client, config

    cancel_orders(ticker)

    log_event('quote', {
        'ticker': ticker,
        'bid': quote.bid.price_cents,
        'ask': quote.ask.price_cents,
        'bid_qty': quote.bid.quantity,
        'ask_qty': quote.ask.quantity,
        'reservation': round(quote.reservation_price, 1),
        'dry_run': config.dry_run
    })

    state.total_quotes += 1

    if config.dry_run:
        os_state.last_quote = quote
        return

    # Place real orders
    yes_bid, no_bid = quote.to_kalshi_orders()

    try:
        resp = client.place_order(
            ticker=ticker,
            side=yes_bid['side'],
            action=yes_bid['action'],
            quantity=yes_bid['quantity'],
            price=yes_bid['price'],
            order_type="limit"
        )
        if resp:
            os_state.yes_order_id = resp.get('order_id')

        resp = client.place_order(
            ticker=ticker,
            side=no_bid['side'],
            action=no_bid['action'],
            quantity=no_bid['quantity'],
            price=no_bid['price'],
            order_type="limit"
        )
        if resp:
            os_state.no_order_id = resp.get('order_id')

        os_state.last_quote = quote
        os_state.last_update = time.time()

    except Exception as e:
        log_event('error', {'message': f'Order error {ticker}: {e}'})


def cancel_orders(ticker: str):
    """Cancel active orders for a market."""
    global state, client, config, order_states

    if ticker not in order_states:
        return
    os_state = order_states[ticker]

    if config.dry_run:
        os_state.yes_order_id = None
        os_state.no_order_id = None
        return

    for order_id in [os_state.yes_order_id, os_state.no_order_id]:
        if order_id:
            try:
                client.cancel_order(order_id)
                state.total_cancels += 1
            except Exception:
                pass

    os_state.yes_order_id = None
    os_state.no_order_id = None


# Dashboard HTML template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Kalshi Market Maker Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Consolas', monospace;
            background: #0d1117;
            color: #c9d1d9;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #30363d;
        }
        .header h1 { color: #58a6ff; font-size: 24px; }
        .status {
            display: flex;
            gap: 20px;
            align-items: center;
        }
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-running { background: #238636; color: white; }
        .status-stopped { background: #da3633; color: white; }
        .status-dry { background: #9e6a03; color: white; }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
        }
        .card h2 {
            color: #58a6ff;
            font-size: 14px;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        /* Stats */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
        }
        .stat { text-align: center; }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #f0f6fc;
        }
        .stat-label {
            font-size: 11px;
            color: #8b949e;
            text-transform: uppercase;
        }
        .stat-positive { color: #3fb950; }
        .stat-negative { color: #f85149; }

        /* Orderbook */
        .orderbook { display: flex; gap: 10px; }
        .orderbook-side { flex: 1; }
        .orderbook-title {
            font-size: 11px;
            color: #8b949e;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        .orderbook-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 8px;
            font-size: 13px;
            border-radius: 3px;
            margin-bottom: 2px;
        }
        .bid-row { background: rgba(46, 160, 67, 0.15); }
        .ask-row { background: rgba(248, 81, 73, 0.15); }
        .price { font-weight: bold; }
        .bid-price { color: #3fb950; }
        .ask-price { color: #f85149; }
        .qty { color: #8b949e; }

        /* Positions */
        .position-row {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: #21262d;
            border-radius: 5px;
            margin-bottom: 8px;
        }
        .position-ticker { font-weight: bold; color: #f0f6fc; }
        .position-long { color: #3fb950; }
        .position-short { color: #f85149; }
        .position-flat { color: #8b949e; }

        /* Quotes */
        .quote-row {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: #21262d;
            border-radius: 5px;
            margin-bottom: 8px;
            align-items: center;
        }
        .quote-prices {
            display: flex;
            gap: 20px;
        }
        .quote-bid { color: #3fb950; }
        .quote-ask { color: #f85149; }
        .quote-spread { color: #8b949e; font-size: 12px; }

        /* Event log */
        .events {
            max-height: 300px;
            overflow-y: auto;
        }
        .event {
            padding: 8px 10px;
            border-left: 3px solid #30363d;
            margin-bottom: 5px;
            font-size: 12px;
            background: #21262d;
        }
        .event-quote { border-left-color: #58a6ff; }
        .event-trade { border-left-color: #3fb950; }
        .event-error { border-left-color: #f85149; }
        .event-time { color: #8b949e; margin-right: 10px; }

        /* Controls */
        .controls { display: flex; gap: 10px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-family: inherit;
            font-size: 13px;
            font-weight: bold;
        }
        .btn-start { background: #238636; color: white; }
        .btn-stop { background: #da3633; color: white; }
        .btn:hover { opacity: 0.9; }

        .mid-price {
            text-align: center;
            padding: 10px;
            background: #21262d;
            border-radius: 5px;
            margin-bottom: 10px;
        }
        .mid-value { font-size: 24px; font-weight: bold; color: #f0f6fc; }
        .spread-value { font-size: 12px; color: #8b949e; }

        .full-width { grid-column: span 2; }

        @media (max-width: 900px) {
            .grid { grid-template-columns: 1fr; }
            .full-width { grid-column: span 1; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Kalshi Market Maker</h1>
        <div class="status">
            <span id="env-badge" class="status-badge">DEMO</span>
            <span id="mode-badge" class="status-badge status-dry">DRY RUN</span>
            <span id="status-badge" class="status-badge status-stopped">STOPPED</span>
            <span id="uptime" style="color: #8b949e; font-size: 13px;">--:--:--</span>
        </div>
    </div>

    <div class="grid">
        <!-- Stats -->
        <div class="card full-width">
            <h2>Statistics</h2>
            <div class="stats-grid">
                <div class="stat">
                    <div class="stat-value" id="stat-quotes">0</div>
                    <div class="stat-label">Quotes</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="stat-fills">0</div>
                    <div class="stat-label">Fills</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="stat-cancels">0</div>
                    <div class="stat-label">Cancels</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="stat-pnl">$0.00</div>
                    <div class="stat-label">P&L</div>
                </div>
            </div>
        </div>

        <!-- Orderbook -->
        <div class="card">
            <h2>Order Book</h2>
            <div id="orderbook-container">
                <div class="mid-price">
                    <div class="mid-value" id="mid-price">--</div>
                    <div class="spread-value">Spread: <span id="spread">--</span>c</div>
                </div>
                <div class="orderbook">
                    <div class="orderbook-side">
                        <div class="orderbook-title">Bids</div>
                        <div id="bids"></div>
                    </div>
                    <div class="orderbook-side">
                        <div class="orderbook-title">Asks</div>
                        <div id="asks"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Positions & Quotes -->
        <div class="card">
            <h2>Positions & Quotes</h2>
            <div id="positions"></div>
            <div style="margin-top: 15px;">
                <h2>Active Quotes</h2>
                <div id="quotes"></div>
            </div>
        </div>

        <!-- Event Log -->
        <div class="card full-width">
            <h2>Event Log</h2>
            <div class="events" id="events"></div>
        </div>
    </div>

    <script>
        const socket = io();

        function formatTime(isoString) {
            const d = new Date(isoString);
            return d.toLocaleTimeString();
        }

        function formatUptime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = seconds % 60;
            return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        socket.on('state_update', function(data) {
            // Status badges
            document.getElementById('status-badge').textContent = data.running ? 'RUNNING' : 'STOPPED';
            document.getElementById('status-badge').className = 'status-badge ' + (data.running ? 'status-running' : 'status-stopped');
            document.getElementById('mode-badge').textContent = data.dry_run ? 'DRY RUN' : 'LIVE';
            document.getElementById('mode-badge').className = 'status-badge ' + (data.dry_run ? 'status-dry' : 'status-running');
            document.getElementById('env-badge').textContent = data.environment.toUpperCase();
            document.getElementById('uptime').textContent = formatUptime(data.uptime);

            // Stats
            document.getElementById('stat-quotes').textContent = data.stats.quotes;
            document.getElementById('stat-fills').textContent = data.stats.fills;
            document.getElementById('stat-cancels').textContent = data.stats.cancels;
            const pnl = (data.stats.pnl_cents / 100).toFixed(2);
            const pnlEl = document.getElementById('stat-pnl');
            pnlEl.textContent = '$' + pnl;
            pnlEl.className = 'stat-value ' + (data.stats.pnl_cents >= 0 ? 'stat-positive' : 'stat-negative');

            // Orderbook (first market)
            const tickers = Object.keys(data.orderbooks);
            if (tickers.length > 0) {
                const ticker = tickers[0];
                const ob = data.orderbooks[ticker];

                document.getElementById('mid-price').textContent = ob.mid ? ob.mid.toFixed(0) + 'c' : '--';
                document.getElementById('spread').textContent = ob.spread ? ob.spread.toFixed(1) : '--';

                let bidsHtml = '';
                (ob.bids || []).slice(0, 8).forEach(b => {
                    bidsHtml += `<div class="orderbook-row bid-row">
                        <span class="price bid-price">${b.price}c</span>
                        <span class="qty">${b.quantity}</span>
                    </div>`;
                });
                document.getElementById('bids').innerHTML = bidsHtml || '<div style="color:#8b949e;padding:10px;">No bids</div>';

                let asksHtml = '';
                (ob.asks || []).slice(0, 8).forEach(a => {
                    asksHtml += `<div class="orderbook-row ask-row">
                        <span class="price ask-price">${a.price}c</span>
                        <span class="qty">${a.quantity}</span>
                    </div>`;
                });
                document.getElementById('asks').innerHTML = asksHtml || '<div style="color:#8b949e;padding:10px;">No asks</div>';
            }

            // Positions
            let posHtml = '';
            for (const [ticker, pos] of Object.entries(data.positions)) {
                const sideClass = pos.quantity > 0 ? 'position-long' : pos.quantity < 0 ? 'position-short' : 'position-flat';
                posHtml += `<div class="position-row">
                    <span class="position-ticker">${ticker}</span>
                    <span class="${sideClass}">${pos.quantity > 0 ? '+' : ''}${pos.quantity} (${pos.side})</span>
                </div>`;
            }
            document.getElementById('positions').innerHTML = posHtml || '<div style="color:#8b949e;padding:10px;">No positions</div>';

            // Quotes
            let quotesHtml = '';
            for (const [ticker, q] of Object.entries(data.quotes)) {
                quotesHtml += `<div class="quote-row">
                    <span class="position-ticker">${ticker}</span>
                    <div class="quote-prices">
                        <span class="quote-bid">${q.bid_price}c x${q.bid_qty}</span>
                        <span class="quote-ask">${q.ask_price}c x${q.ask_qty}</span>
                    </div>
                    <span class="quote-spread">r=${q.reservation_price.toFixed(1)}</span>
                </div>`;
            }
            document.getElementById('quotes').innerHTML = quotesHtml || '<div style="color:#8b949e;padding:10px;">No quotes</div>';
        });

        socket.on('event', function(event) {
            const eventsEl = document.getElementById('events');
            const eventClass = 'event event-' + event.type;
            let content = '';

            if (event.type === 'quote') {
                content = `<strong>${event.data.ticker}</strong> Bid: ${event.data.bid}c x${event.data.bid_qty} | Ask: ${event.data.ask}c x${event.data.ask_qty}`;
                if (event.data.dry_run) content += ' [DRY]';
            } else if (event.type === 'trade') {
                content = `<strong>${event.data.ticker}</strong> Position: ${event.data.old_qty} → ${event.data.new_qty} (${event.data.delta > 0 ? '+' : ''}${event.data.delta})`;
            } else if (event.type === 'error') {
                content = `<strong>ERROR:</strong> ${event.data.message}`;
            }

            const eventHtml = `<div class="${eventClass}">
                <span class="event-time">${formatTime(event.timestamp)}</span>
                ${content}
            </div>`;

            eventsEl.insertAdjacentHTML('afterbegin', eventHtml);

            // Keep only last 50 events in DOM
            while (eventsEl.children.length > 50) {
                eventsEl.removeChild(eventsEl.lastChild);
            }
        });

        socket.on('connect', function() {
            console.log('Connected to dashboard');
        });
    </script>
</body>
</html>
'''


@app.route('/')
def dashboard():
    """Serve the dashboard page."""
    return render_template_string(DASHBOARD_HTML)


@socketio.on('connect')
def handle_connect():
    """Handle new client connection."""
    emit_state()


def run_dashboard(env: str, live: bool, port: int):
    """Initialize and run the dashboard with trading bot."""
    global client, config, state

    # Load configuration
    loader = ConfigLoader()
    cfg_dict = loader.load(env)

    # Override dry_run based on --live flag
    if live:
        cfg_dict['execution']['dry_run'] = False

    state.dry_run = cfg_dict['execution'].get('dry_run', True)
    state.environment = env

    # Create execution config
    markets = {}
    for m in cfg_dict.get('markets', []):
        markets[m['ticker']] = MarketConfig(
            ticker=m['ticker'],
            enabled=m.get('enabled', True),
            gamma=m.get('gamma', 0.1),
            sigma=m.get('sigma', 2.0),
            k=m.get('k', 1.5),
            base_size=m.get('base_size', 10),
            max_position=m.get('max_position', 100),
            max_loss_cents=m.get('max_loss_cents', 500.0)
        )

    config = ExecutionConfig(
        quote_interval=cfg_dict['execution'].get('quote_interval', 1.0),
        position_sync_interval=cfg_dict['execution'].get('position_sync_interval', 5.0),
        total_max_position=cfg_dict['execution'].get('total_max_position', 500),
        cancel_threshold=cfg_dict['execution'].get('cancel_threshold', 1),
        markets=markets,
        dry_run=state.dry_run
    )

    # Initialize API client
    api_cfg = cfg_dict['api']
    key_id = os.environ.get('KALSHI_KEY_ID', api_cfg.get('key_id', ''))
    key_file = api_cfg.get('private_key_file', 'kalshidemo.txt')
    host = api_cfg.get('host', 'https://demo-api.kalshi.co/trade-api/v2')

    print(f"Initializing Kalshi client...")
    print(f"  Environment: {env}")
    print(f"  Host: {host}")
    print(f"  Dry run: {state.dry_run}")
    print(f"  Markets: {list(markets.keys())}")

    try:
        client = KalshiClient(key_id=key_id, private_key_path=key_file, host=host)
        print("  Client initialized successfully")
    except Exception as e:
        print(f"  Warning: Could not initialize client: {e}")
        print("  Running in offline mode (dashboard only)")
        client = None

    # Start trading thread if client is available
    if client:
        trading_thread = threading.Thread(target=trading_loop, daemon=True)
        trading_thread.start()
        print(f"\nTrading bot started")

    print(f"\nDashboard available at http://localhost:{port}")
    print("Press Ctrl+C to stop\n")

    # Run Flask with SocketIO
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


def main():
    parser = argparse.ArgumentParser(description='Kalshi Market Maker Dashboard')
    parser.add_argument('--env', choices=['demo', 'prod'], default='demo',
                        help='Environment to use (default: demo)')
    parser.add_argument('--live', action='store_true',
                        help='Enable live trading (disables dry run)')
    parser.add_argument('--port', type=int, default=8080,
                        help='Dashboard port (default: 8080)')

    args = parser.parse_args()

    if args.live and args.env == 'prod':
        print("\n" + "=" * 50)
        print("WARNING: PRODUCTION LIVE MODE")
        print("This will place REAL orders with REAL money!")
        print("=" * 50)
        response = input("Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return

    try:
        run_dashboard(args.env, args.live, args.port)
    except KeyboardInterrupt:
        print("\nShutting down...")
        state.running = False


if __name__ == '__main__':
    main()
