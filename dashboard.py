"""
Kalshi Market Maker Dashboard

Real-time web dashboard for monitoring the trading bot.
Displays: positions, P&L, orderbook, trades, flow analysis, and bot status.
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
from src.flow import FlowAnalyzer, FlowConfig, parse_kalshi_trades

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

    # Flow data
    flow_states: Dict[str, dict] = None

    # Balance
    balance_cents: int = 0
    portfolio_value_cents: int = 0

    # History (last 100 events)
    trade_history: deque = None
    quote_history: deque = None

    # Mid price history for charting (per ticker, last 120 data points)
    mid_history: Dict[str, deque] = None
    pnl_history: deque = None

    def __post_init__(self):
        self.orderbooks = {}
        self.positions = {}
        self.quotes = {}
        self.flow_states = {}
        self.trade_history = deque(maxlen=100)
        self.quote_history = deque(maxlen=100)
        self.mid_history = {}
        self.pnl_history = deque(maxlen=120)


# Global state
state = DashboardState()
client: Optional[KalshiClient] = None
config: Optional[ExecutionConfig] = None
position_tracker = PositionTracker()
order_states: Dict[str, OrderState] = {}
flow_analyzer = FlowAnalyzer(FlowConfig())
flow_cooldowns: Dict[str, float] = {}


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
        'balance': {
            'balance_cents': state.balance_cents,
            'portfolio_value_cents': state.portfolio_value_cents,
        },
        'positions': state.positions,
        'quotes': state.quotes,
        'orderbooks': state.orderbooks,
        'flow_states': state.flow_states,
        'trade_history': list(state.trade_history),
        'quote_history': list(state.quote_history),
        'mid_history': {t: list(h) for t, h in state.mid_history.items()},
        'pnl_history': list(state.pnl_history),
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


def trading_loop(key_id: str, private_key: str, host: str):
    """Main trading loop running in background thread."""
    global state, client, config

    from src.client import KalshiClient
    client = KalshiClient(key_id=key_id, private_key=private_key, host=host)
    print("[TRADING] Client initialized in trading thread")

    state.running = True
    state.start_time = time.time()
    last_sync = 0
    last_balance_sync = 0
    loop_count = 0

    while state.running:
        try:
            loop_count += 1
            if loop_count <= 5 or loop_count % 60 == 0:
                print(f"[TRADING] Loop {loop_count}, markets: {list(config.markets.keys())}", flush=True)

            # Sync positions periodically
            if time.time() - last_sync > config.position_sync_interval:
                sync_positions()
                last_sync = time.time()

            # Sync balance every 30s
            if time.time() - last_balance_sync > 30:
                sync_balance()
                last_balance_sync = time.time()

            # Check global position limit
            total_exposure = position_tracker.get_total_exposure()
            if total_exposure > config.total_max_position:
                log_event('error', {'message': f'Position limit exceeded ({total_exposure}/{config.total_max_position}), pulling quotes'})
                for ticker in list(order_states.keys()):
                    cancel_orders(ticker)
                emit_state()
                time.sleep(config.quote_interval)
                continue

            # Update each market
            for ticker, mc in config.markets.items():
                if mc.enabled:
                    update_market(ticker, mc)

            # Track PnL history
            state.pnl_history.append({
                'time': datetime.now().isoformat(),
                'pnl': state.pnl_cents
            })

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
            avg_price = p.get('average_price_paid') or p.get('avg_price')

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

            position_tracker.positions[ticker] = Position(
                ticker, qty, avg_price if avg_price else current.avg_entry_price
            )

            # Calculate unrealized PnL
            pos_obj = position_tracker.get_position(ticker)
            mid = state.orderbooks.get(ticker, {}).get('mid')
            unrealized = 0
            if mid and pos_obj.avg_entry_price and pos_obj.quantity != 0:
                unrealized = (mid - pos_obj.avg_entry_price) * pos_obj.quantity

            state.positions[ticker] = {
                'quantity': qty,
                'avg_price': avg_price,
                'side': 'LONG' if qty > 0 else 'SHORT' if qty < 0 else 'FLAT',
                'unrealized_pnl': round(unrealized, 1),
            }

        # Update total PnL
        total_pnl = sum(p.get('unrealized_pnl', 0) for p in state.positions.values())
        state.pnl_cents = total_pnl

    except Exception as e:
        log_event('error', {'message': f'Position sync error: {e}'})


def sync_balance():
    """Sync balance from API."""
    global state, client
    try:
        bal = client.get_balance()
        if bal:
            state.balance_cents = bal.get('balance', 0)
            state.portfolio_value_cents = bal.get('portfolio_value', 0)
    except Exception as e:
        log_event('error', {'message': f'Balance sync error: {e}'})


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

    # Track mid price history
    if ticker not in state.mid_history:
        state.mid_history[ticker] = deque(maxlen=120)
    if ob.mid_price is not None:
        state.mid_history[ticker].append({
            'time': datetime.now().isoformat(),
            'mid': ob.mid_price,
        })

    if ob.mid_price is None:
        cancel_orders(ticker)
        return

    # Get position
    pos = position_tracker.get_position(ticker)

    # Stop loss check
    if pos.quantity != 0 and pos.avg_entry_price:
        pnl = (ob.mid_price - pos.avg_entry_price) * pos.quantity
        if pnl < -mc.max_loss_cents:
            log_event('error', {'message': f'Stop loss {ticker}: PnL={pnl:.0f}c (limit={-mc.max_loss_cents}c)'})
            cancel_orders(ticker)
            return

    # Flow detection
    flow_adjustment = flow_analyzer.recommend_adjustment(ticker)
    try:
        raw_trades = client.get_trades(ticker, limit=20)
        if raw_trades:
            trades = parse_kalshi_trades(raw_trades)
            flow_analyzer.add_trades(trades)
            flow_adjustment = flow_analyzer.recommend_adjustment(ticker)
    except Exception as e:
        log_event('error', {'message': f'Flow analysis error {ticker}: {e}'})

    # Store flow state for dashboard
    try:
        metrics = flow_analyzer.analyze(ticker)
        state.flow_states[ticker] = {
            'toxicity': metrics.toxicity_score if metrics else 0,
            'action': flow_adjustment.action,
            'reason': flow_adjustment.reason,
            'spread_mult': flow_adjustment.spread_multiplier,
            'size_mult': flow_adjustment.size_multiplier,
            'max_run': metrics.max_run_length if metrics else 0,
            'imbalance': round(metrics.buy_sell_imbalance, 2) if metrics else 0.5,
            'momentum': round(metrics.price_momentum, 1) if metrics else 0,
        }
    except Exception:
        state.flow_states[ticker] = {
            'toxicity': 0, 'action': 'normal', 'reason': '',
            'spread_mult': 1.0, 'size_mult': 1.0,
            'max_run': 0, 'imbalance': 0.5, 'momentum': 0,
        }

    if flow_adjustment.action == "pull":
        log_event('error', {'message': f'Flow PULL {ticker}: {flow_adjustment.reason}'})
        cancel_orders(ticker)
        flow_cooldowns[ticker] = time.time() + flow_adjustment.cooldown_seconds
        return

    if time.time() < flow_cooldowns.get(ticker, 0):
        return

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

    # Apply flow adjustments (widen spread, reduce size)
    if flow_adjustment.spread_multiplier != 1.0 or flow_adjustment.size_multiplier != 1.0:
        mid = quote.reservation_price
        half_spread = (quote.ask.price_cents - quote.bid.price_cents) / 2.0
        new_half = half_spread * flow_adjustment.spread_multiplier
        new_bid = max(1, min(98, int(round(mid - new_half))))
        new_ask = max(2, min(99, int(round(mid + new_half))))
        if new_bid >= new_ask:
            new_bid = max(1, int(mid) - 1)
            new_ask = min(99, int(mid) + 1)
        if new_bid >= new_ask:
            cancel_orders(ticker)
            return
        quote.bid.price_cents = new_bid
        quote.ask.price_cents = new_ask
        quote.spread_cents = new_ask - new_bid
        quote.bid.quantity = max(1, int(quote.bid.quantity * flow_adjustment.size_multiplier))
        quote.ask.quantity = max(1, int(quote.ask.quantity * flow_adjustment.size_multiplier))

    # Store quote for dashboard
    state.quotes[ticker] = {
        'bid_price': quote.bid.price_cents,
        'bid_qty': quote.bid.quantity,
        'ask_price': quote.ask.price_cents,
        'ask_qty': quote.ask.quantity,
        'reservation_price': quote.reservation_price,
        'mid_price': quote.mid_price,
        'spread': quote.ask.price_cents - quote.bid.price_cents,
        'inventory': pos.quantity,
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
        'spread': quote.ask.price_cents - quote.bid.price_cents,
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


# ==================== Dashboard HTML ====================

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kalshi Market Maker</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #1a1f2e;
            --bg-hover: #252b3b;
            --border: #2a3040;
            --border-light: #374151;
            --text-primary: #e5e7eb;
            --text-secondary: #9ca3af;
            --text-muted: #6b7280;
            --accent-blue: #3b82f6;
            --accent-cyan: #22d3ee;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
            --green-dim: rgba(16, 185, 129, 0.12);
            --red-dim: rgba(239, 68, 68, 0.12);
            --blue-dim: rgba(59, 130, 246, 0.12);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.5;
            overflow-x: hidden;
        }

        /* ---- Header ---- */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header-left { display: flex; align-items: center; gap: 16px; }
        .header-left h1 {
            font-size: 18px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.3px;
        }
        .badges { display: flex; gap: 8px; align-items: center; }
        .badge {
            font-size: 11px;
            font-weight: 600;
            padding: 3px 10px;
            border-radius: 100px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-live { background: var(--accent-green); color: #000; }
        .badge-dry { background: var(--accent-yellow); color: #000; }
        .badge-stopped { background: var(--accent-red); color: #fff; }
        .badge-running { background: var(--accent-green); color: #000; }
        .badge-env {
            background: var(--bg-card);
            color: var(--text-secondary);
            border: 1px solid var(--border);
        }
        .header-right {
            display: flex;
            align-items: center;
            gap: 20px;
            font-size: 13px;
            color: var(--text-secondary);
        }
        .header-right .uptime { font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 14px; }
        .pulse {
            width: 8px; height: 8px; border-radius: 50%;
            display: inline-block; margin-right: 6px;
        }
        .pulse-on { background: var(--accent-green); box-shadow: 0 0 8px var(--accent-green); animation: pulse 2s infinite; }
        .pulse-off { background: var(--accent-red); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

        /* ---- Main Grid ---- */
        .main { padding: 20px 24px; }
        .grid-top {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }
        .grid-body {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 16px;
            margin-bottom: 20px;
        }
        .grid-bottom {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 16px;
        }

        /* ---- Cards ---- */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 20px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }
        .card-title {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
        }
        .card-badge {
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 100px;
            font-weight: 600;
        }

        /* ---- Stat Cards ---- */
        .stat-card { text-align: center; padding: 20px 16px; }
        .stat-value {
            font-size: 28px;
            font-weight: 700;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
            margin-bottom: 4px;
            line-height: 1.2;
        }
        .stat-label {
            font-size: 11px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
        }
        .stat-sub {
            font-size: 11px;
            color: var(--text-secondary);
            margin-top: 4px;
        }
        .c-green { color: var(--accent-green); }
        .c-red { color: var(--accent-red); }
        .c-blue { color: var(--accent-blue); }
        .c-yellow { color: var(--accent-yellow); }
        .c-cyan { color: var(--accent-cyan); }
        .c-purple { color: var(--accent-purple); }
        .c-muted { color: var(--text-muted); }

        /* ---- Orderbook ---- */
        .ob-container { display: flex; flex-direction: column; gap: 6px; }
        .ob-mid {
            text-align: center;
            padding: 8px;
            background: var(--bg-hover);
            border-radius: 8px;
            margin-bottom: 4px;
        }
        .ob-mid-price {
            font-size: 26px;
            font-weight: 700;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
        }
        .ob-mid-spread { font-size: 12px; color: var(--text-muted); }
        .ob-side { display: flex; flex-direction: column; gap: 2px; }
        .ob-header {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            padding: 0 8px;
            margin-bottom: 4px;
        }
        .ob-row {
            display: flex;
            align-items: center;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 13px;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
            position: relative;
            overflow: hidden;
        }
        .ob-row .depth-bar {
            position: absolute;
            top: 0; bottom: 0;
            border-radius: 4px;
            z-index: 0;
            transition: width 0.3s ease;
        }
        .ob-row.bid .depth-bar { right: 0; background: var(--green-dim); }
        .ob-row.ask .depth-bar { right: 0; background: var(--red-dim); }
        .ob-row > span { position: relative; z-index: 1; }
        .ob-row .ob-price { flex: 1; font-weight: 600; }
        .ob-row .ob-qty { width: 60px; text-align: right; color: var(--text-secondary); }
        .ob-row.bid .ob-price { color: var(--accent-green); }
        .ob-row.ask .ob-price { color: var(--accent-red); }
        .ob-row.my-quote {
            border: 1px solid var(--accent-cyan);
            background: rgba(34, 211, 238, 0.06);
        }
        .ob-row.my-quote .depth-bar { display: none; }
        .my-tag {
            font-size: 9px;
            background: var(--accent-cyan);
            color: #000;
            padding: 1px 5px;
            border-radius: 3px;
            font-weight: 700;
            margin-left: 6px;
        }

        /* ---- Position Card ---- */
        .pos-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 14px;
            background: var(--bg-hover);
            border-radius: 8px;
            margin-bottom: 6px;
        }
        .pos-ticker { font-weight: 600; font-size: 14px; }
        .pos-details { display: flex; gap: 16px; align-items: center; }
        .pos-qty { font-family: 'SF Mono', 'Cascadia Code', monospace; font-weight: 600; font-size: 15px; }
        .pos-meta { font-size: 12px; color: var(--text-secondary); }
        .pos-pnl { font-family: 'SF Mono', 'Cascadia Code', monospace; font-weight: 600; }

        /* ---- Inventory Gauge ---- */
        .inv-gauge {
            margin-top: 10px;
            padding: 10px;
            background: var(--bg-hover);
            border-radius: 8px;
        }
        .inv-gauge-label {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 6px;
        }
        .inv-bar-track {
            height: 10px;
            background: var(--bg-secondary);
            border-radius: 5px;
            position: relative;
            overflow: hidden;
        }
        .inv-bar-center {
            position: absolute;
            left: 50%; top: 0; bottom: 0;
            width: 2px;
            background: var(--border-light);
        }
        .inv-bar-fill {
            position: absolute;
            top: 0; bottom: 0;
            border-radius: 5px;
            transition: all 0.3s ease;
        }

        /* ---- Quote Card ---- */
        .quote-visual {
            display: flex;
            align-items: center;
            gap: 4px;
            margin-bottom: 10px;
            padding: 12px;
            background: var(--bg-hover);
            border-radius: 8px;
        }
        .qv-section { text-align: center; flex: 1; }
        .qv-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 2px; }
        .qv-price {
            font-size: 22px; font-weight: 700;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
        }
        .qv-qty { font-size: 12px; color: var(--text-secondary); }
        .qv-arrow { font-size: 18px; color: var(--text-muted); flex-shrink: 0; }
        .qv-reservation {
            font-size: 11px;
            text-align: center;
            color: var(--text-muted);
            margin-top: 4px;
        }

        /* ---- Flow Card ---- */
        .flow-gauge { margin-bottom: 12px; }
        .flow-bar-track {
            height: 16px;
            background: var(--bg-secondary);
            border-radius: 8px;
            overflow: hidden;
            position: relative;
        }
        .flow-bar-fill {
            height: 100%;
            border-radius: 8px;
            transition: width 0.5s ease, background 0.5s ease;
        }
        .flow-thresholds {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 4px;
            padding: 0 2px;
        }
        .flow-metrics {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-top: 10px;
        }
        .flow-metric {
            text-align: center;
            padding: 8px;
            background: var(--bg-hover);
            border-radius: 6px;
        }
        .flow-metric-value {
            font-size: 16px;
            font-weight: 600;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
        }
        .flow-metric-label {
            font-size: 10px;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        /* ---- Event Log ---- */
        .events { max-height: 400px; overflow-y: auto; }
        .events::-webkit-scrollbar { width: 6px; }
        .events::-webkit-scrollbar-track { background: transparent; }
        .events::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        .evt {
            display: flex;
            align-items: flex-start;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 6px;
            margin-bottom: 4px;
            font-size: 12px;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
            background: var(--bg-hover);
            border-left: 3px solid transparent;
        }
        .evt-quote { border-left-color: var(--accent-blue); }
        .evt-trade { border-left-color: var(--accent-green); }
        .evt-error { border-left-color: var(--accent-red); }
        .evt-time { color: var(--text-muted); white-space: nowrap; }
        .evt-content { flex: 1; }
        .evt-tag {
            font-size: 9px;
            font-weight: 700;
            padding: 1px 6px;
            border-radius: 3px;
            text-transform: uppercase;
        }
        .evt-tag-quote { background: var(--blue-dim); color: var(--accent-blue); }
        .evt-tag-trade { background: var(--green-dim); color: var(--accent-green); }
        .evt-tag-error { background: var(--red-dim); color: var(--accent-red); }
        .evt-tag-dry { background: var(--bg-secondary); color: var(--accent-yellow); margin-left: 4px; }

        /* ---- Market Tabs ---- */
        .market-tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 16px;
        }
        .market-tab {
            padding: 6px 16px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            background: var(--bg-hover);
            color: var(--text-secondary);
            border: 1px solid transparent;
            transition: all 0.2s;
        }
        .market-tab:hover { color: var(--text-primary); }
        .market-tab.active {
            background: var(--blue-dim);
            color: var(--accent-blue);
            border-color: var(--accent-blue);
        }

        /* ---- AS Model Card ---- */
        .as-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .as-item {
            padding: 8px 10px;
            background: var(--bg-hover);
            border-radius: 6px;
        }
        .as-item-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; }
        .as-item-value {
            font-size: 15px;
            font-weight: 600;
            font-family: 'SF Mono', 'Cascadia Code', monospace;
        }

        .empty-state {
            text-align: center;
            padding: 30px 20px;
            color: var(--text-muted);
            font-size: 13px;
        }

        /* ---- Responsive ---- */
        @media (max-width: 1200px) {
            .grid-top { grid-template-columns: repeat(3, 1fr); }
            .grid-body { grid-template-columns: 1fr 1fr; }
            .grid-bottom { grid-template-columns: 1fr; }
        }
        @media (max-width: 768px) {
            .grid-top { grid-template-columns: repeat(2, 1fr); }
            .grid-body { grid-template-columns: 1fr; }
            .header { flex-direction: column; gap: 10px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <h1>KALSHI MARKET MAKER</h1>
            <div class="badges">
                <span id="env-badge" class="badge badge-env">DEMO</span>
                <span id="mode-badge" class="badge badge-dry">DRY RUN</span>
                <span id="status-badge" class="badge badge-stopped">
                    <span class="pulse pulse-off" id="status-pulse"></span>STOPPED
                </span>
            </div>
        </div>
        <div class="header-right">
            <span id="balance-display" style="color:var(--accent-cyan)">--</span>
            <span>Uptime: <span class="uptime" id="uptime">00:00:00</span></span>
        </div>
    </div>

    <div class="main">
        <!-- Market Tabs -->
        <div class="market-tabs" id="market-tabs"></div>

        <!-- Stat Cards Row -->
        <div class="grid-top">
            <div class="card stat-card">
                <div class="stat-value c-blue" id="stat-quotes">0</div>
                <div class="stat-label">Quotes Placed</div>
            </div>
            <div class="card stat-card">
                <div class="stat-value c-green" id="stat-fills">0</div>
                <div class="stat-label">Fills</div>
            </div>
            <div class="card stat-card">
                <div class="stat-value c-yellow" id="stat-cancels">0</div>
                <div class="stat-label">Cancels</div>
            </div>
            <div class="card stat-card">
                <div class="stat-value" id="stat-pnl">$0.00</div>
                <div class="stat-label">Unrealized P&L</div>
            </div>
            <div class="card stat-card">
                <div class="stat-value c-cyan" id="stat-exposure">0</div>
                <div class="stat-label">Total Exposure</div>
            </div>
            <div class="card stat-card">
                <div class="stat-value c-purple" id="stat-spread">--</div>
                <div class="stat-label">Active Spread</div>
            </div>
        </div>

        <!-- Main Body Grid -->
        <div class="grid-body">
            <!-- Order Book -->
            <div class="card" id="card-orderbook">
                <div class="card-header">
                    <span class="card-title">Order Book</span>
                    <span class="card-badge" id="ob-ticker" style="background:var(--blue-dim);color:var(--accent-blue)">--</span>
                </div>
                <div class="ob-container" id="orderbook-container">
                    <div class="ob-mid">
                        <div class="ob-mid-price" id="ob-mid">--</div>
                        <div class="ob-mid-spread">Spread: <span id="ob-spread">--</span>c</div>
                    </div>
                    <div class="ob-header"><span>ASKS</span><span>QTY</span></div>
                    <div class="ob-side" id="ob-asks"></div>
                    <div style="height:6px"></div>
                    <div class="ob-header"><span>BIDS</span><span>QTY</span></div>
                    <div class="ob-side" id="ob-bids"></div>
                </div>
            </div>

            <!-- Positions + Quotes -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Active Quote</span>
                </div>
                <div id="quote-display">
                    <div class="empty-state">Waiting for quotes...</div>
                </div>

                <div style="margin-top:16px;">
                    <div class="card-header">
                        <span class="card-title">Positions</span>
                    </div>
                    <div id="positions-display">
                        <div class="empty-state">No positions</div>
                    </div>
                </div>

                <div style="margin-top:16px;">
                    <div class="card-header">
                        <span class="card-title">AS Model</span>
                    </div>
                    <div class="as-grid" id="as-model-display">
                        <div class="as-item"><div class="as-item-label">Reservation</div><div class="as-item-value" id="as-reservation">--</div></div>
                        <div class="as-item"><div class="as-item-label">Mid Price</div><div class="as-item-value" id="as-mid">--</div></div>
                        <div class="as-item"><div class="as-item-label">Inv Shift</div><div class="as-item-value" id="as-shift">--</div></div>
                        <div class="as-item"><div class="as-item-label">Spread</div><div class="as-item-value" id="as-spread">--</div></div>
                    </div>
                </div>
            </div>

            <!-- Flow Analysis -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Flow Analysis</span>
                    <span class="card-badge" id="flow-action-badge" style="background:var(--green-dim);color:var(--accent-green)">NORMAL</span>
                </div>
                <div class="flow-gauge">
                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
                        <span style="font-size:11px;color:var(--text-muted)">Toxicity Score</span>
                        <span style="font-family:'SF Mono',monospace;font-size:18px;font-weight:700" id="flow-score">0</span>
                    </div>
                    <div class="flow-bar-track">
                        <div class="flow-bar-fill" id="flow-bar" style="width:0%;background:var(--accent-green)"></div>
                    </div>
                    <div class="flow-thresholds">
                        <span>0</span><span>40 reduce</span><span>60 widen</span><span>80 pull</span><span>100</span>
                    </div>
                </div>
                <div class="flow-metrics">
                    <div class="flow-metric">
                        <div class="flow-metric-value" id="flow-run">0</div>
                        <div class="flow-metric-label">Max Run</div>
                    </div>
                    <div class="flow-metric">
                        <div class="flow-metric-value" id="flow-imbalance">0.50</div>
                        <div class="flow-metric-label">Imbalance</div>
                    </div>
                    <div class="flow-metric">
                        <div class="flow-metric-value" id="flow-momentum">0.0</div>
                        <div class="flow-metric-label">Momentum</div>
                    </div>
                </div>

                <div style="margin-top:16px;">
                    <div class="card-header">
                        <span class="card-title">Inventory Gauge</span>
                    </div>
                    <div class="inv-gauge" id="inv-gauge">
                        <div class="inv-gauge-label">
                            <span>-max</span>
                            <span id="inv-gauge-value">0 contracts</span>
                            <span>+max</span>
                        </div>
                        <div class="inv-bar-track">
                            <div class="inv-bar-center"></div>
                            <div class="inv-bar-fill" id="inv-bar-fill" style="left:50%;width:0%;background:var(--text-muted)"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Bottom: Event Log + Model Params -->
        <div class="grid-bottom">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Event Log</span>
                    <span style="font-size:11px;color:var(--text-muted)" id="event-count">0 events</span>
                </div>
                <div class="events" id="events"></div>
            </div>
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Quote History</span>
                </div>
                <div class="events" id="quote-history-log"></div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let selectedTicker = null;
        let allTickers = [];
        let eventCount = 0;

        function fmt(n, d=1) { return n != null ? n.toFixed(d) : '--'; }
        function fmtTime(iso) {
            const d = new Date(iso);
            return d.toLocaleTimeString('en-US', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
        }
        function fmtUptime(s) {
            const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
            return [h,m,sec].map(v => String(v).padStart(2,'0')).join(':');
        }

        socket.on('state_update', function(d) {
            // ---- Header ----
            const badge = (id, text, cls) => {
                const el = document.getElementById(id);
                el.textContent = text;
                el.className = 'badge ' + cls;
            };
            badge('env-badge', d.environment.toUpperCase(), 'badge-env');
            badge('mode-badge', d.dry_run ? 'DRY RUN' : 'LIVE', d.dry_run ? 'badge-dry' : 'badge-live');

            const statusEl = document.getElementById('status-badge');
            const pulseEl = document.getElementById('status-pulse');
            if (d.running) {
                statusEl.innerHTML = '<span class="pulse pulse-on"></span>RUNNING';
                statusEl.className = 'badge badge-running';
            } else {
                statusEl.innerHTML = '<span class="pulse pulse-off"></span>STOPPED';
                statusEl.className = 'badge badge-stopped';
            }
            document.getElementById('uptime').textContent = fmtUptime(d.uptime);

            // Balance
            const balEl = document.getElementById('balance-display');
            if (d.balance && d.balance.balance_cents > 0) {
                balEl.textContent = '$' + (d.balance.balance_cents / 100).toFixed(2);
            }

            // ---- Stats ----
            document.getElementById('stat-quotes').textContent = d.stats.quotes.toLocaleString();
            document.getElementById('stat-fills').textContent = d.stats.fills.toLocaleString();
            document.getElementById('stat-cancels').textContent = d.stats.cancels.toLocaleString();

            const pnlCents = d.stats.pnl_cents;
            const pnlEl = document.getElementById('stat-pnl');
            pnlEl.textContent = (pnlCents >= 0 ? '+' : '') + (pnlCents / 100).toFixed(2) + '$';
            pnlEl.className = 'stat-value ' + (pnlCents >= 0 ? 'c-green' : 'c-red');

            // Exposure
            let totalExp = 0;
            for (const pos of Object.values(d.positions)) {
                totalExp += Math.abs(pos.quantity || 0);
            }
            document.getElementById('stat-exposure').textContent = totalExp;

            // ---- Market Tabs ----
            const tickers = Object.keys(d.orderbooks);
            if (tickers.length > 0 && (allTickers.join() !== tickers.join())) {
                allTickers = tickers;
                if (!selectedTicker || !tickers.includes(selectedTicker)) {
                    selectedTicker = tickers[0];
                }
                renderTabs();
            }

            if (!selectedTicker && tickers.length > 0) {
                selectedTicker = tickers[0];
                renderTabs();
            }

            // ---- Active Spread ----
            if (selectedTicker && d.quotes[selectedTicker]) {
                document.getElementById('stat-spread').textContent = d.quotes[selectedTicker].spread + 'c';
            }

            // ---- Orderbook ----
            if (selectedTicker && d.orderbooks[selectedTicker]) {
                const ob = d.orderbooks[selectedTicker];
                const q = d.quotes[selectedTicker];
                document.getElementById('ob-ticker').textContent = selectedTicker;
                document.getElementById('ob-mid').textContent = ob.mid != null ? ob.mid.toFixed(1) + 'c' : '--';
                document.getElementById('ob-spread').textContent = ob.spread != null ? ob.spread.toFixed(1) : '--';

                // Find max qty for depth bar sizing
                const allLevels = [...(ob.asks||[]), ...(ob.bids||[])];
                const maxQty = Math.max(1, ...allLevels.map(l => l.quantity));
                const myBid = q ? q.bid_price : null;
                const myAsk = q ? q.ask_price : null;

                // Asks (reversed: highest price on top)
                let asksHtml = '';
                const asks = (ob.asks || []).slice(0, 6).reverse();
                for (const a of asks) {
                    const isMyQuote = myAsk === a.price;
                    const barW = (a.quantity / maxQty * 60).toFixed(1);
                    asksHtml += '<div class="ob-row ask' + (isMyQuote ? ' my-quote' : '') + '">' +
                        '<div class="depth-bar" style="width:' + barW + '%"></div>' +
                        '<span class="ob-price">' + a.price + 'c' + (isMyQuote ? '<span class="my-tag">YOU</span>' : '') + '</span>' +
                        '<span class="ob-qty">' + a.quantity + '</span></div>';
                }
                document.getElementById('ob-asks').innerHTML = asksHtml || '<div class="empty-state">No asks</div>';

                // Bids (highest first)
                let bidsHtml = '';
                const bids = (ob.bids || []).slice(0, 6);
                for (const b of bids) {
                    const isMyQuote = myBid === b.price;
                    const barW = (b.quantity / maxQty * 60).toFixed(1);
                    bidsHtml += '<div class="ob-row bid' + (isMyQuote ? ' my-quote' : '') + '">' +
                        '<div class="depth-bar" style="width:' + barW + '%"></div>' +
                        '<span class="ob-price">' + b.price + 'c' + (isMyQuote ? '<span class="my-tag">YOU</span>' : '') + '</span>' +
                        '<span class="ob-qty">' + b.quantity + '</span></div>';
                }
                document.getElementById('ob-bids').innerHTML = bidsHtml || '<div class="empty-state">No bids</div>';
            }

            // ---- Quote Display ----
            if (selectedTicker && d.quotes[selectedTicker]) {
                const q = d.quotes[selectedTicker];
                document.getElementById('quote-display').innerHTML =
                    '<div class="quote-visual">' +
                        '<div class="qv-section"><div class="qv-label">Bid</div>' +
                            '<div class="qv-price c-green">' + q.bid_price + 'c</div>' +
                            '<div class="qv-qty">' + q.bid_qty + ' contracts</div></div>' +
                        '<div class="qv-arrow">&larr; ' + q.spread + 'c &rarr;</div>' +
                        '<div class="qv-section"><div class="qv-label">Ask</div>' +
                            '<div class="qv-price c-red">' + q.ask_price + 'c</div>' +
                            '<div class="qv-qty">' + q.ask_qty + ' contracts</div></div>' +
                    '</div>';

                // AS Model
                document.getElementById('as-reservation').textContent = fmt(q.reservation_price) + 'c';
                document.getElementById('as-mid').textContent = fmt(q.mid_price) + 'c';
                const shift = q.reservation_price - q.mid_price;
                const shiftEl = document.getElementById('as-shift');
                shiftEl.textContent = (shift >= 0 ? '+' : '') + fmt(shift) + 'c';
                shiftEl.className = 'as-item-value ' + (Math.abs(shift) < 0.1 ? 'c-muted' : shift > 0 ? 'c-green' : 'c-red');
                document.getElementById('as-spread').textContent = q.spread + 'c';
            } else {
                document.getElementById('quote-display').innerHTML = '<div class="empty-state">Waiting for quotes...</div>';
            }

            // ---- Positions ----
            let posHtml = '';
            for (const [ticker, pos] of Object.entries(d.positions)) {
                if (pos.quantity === 0) continue;
                const color = pos.quantity > 0 ? 'c-green' : 'c-red';
                const pnlColor = (pos.unrealized_pnl || 0) >= 0 ? 'c-green' : 'c-red';
                const pnlSign = (pos.unrealized_pnl || 0) >= 0 ? '+' : '';
                posHtml += '<div class="pos-row">' +
                    '<div><div class="pos-ticker">' + ticker + '</div>' +
                    '<div class="pos-meta">' + pos.side + ' @ ' + (pos.avg_price || '--') + 'c avg</div></div>' +
                    '<div class="pos-details">' +
                    '<span class="pos-qty ' + color + '">' + (pos.quantity > 0 ? '+' : '') + pos.quantity + '</span>' +
                    '<span class="pos-pnl ' + pnlColor + '">' + pnlSign + fmt(pos.unrealized_pnl || 0) + 'c</span>' +
                    '</div></div>';
            }
            document.getElementById('positions-display').innerHTML = posHtml || '<div class="empty-state">No positions</div>';

            // ---- Flow Analysis ----
            if (selectedTicker && d.flow_states[selectedTicker]) {
                const f = d.flow_states[selectedTicker];
                const tox = f.toxicity;

                document.getElementById('flow-score').textContent = tox;
                const bar = document.getElementById('flow-bar');
                bar.style.width = tox + '%';
                bar.style.background = tox < 40 ? 'var(--accent-green)' :
                    tox < 60 ? 'var(--accent-yellow)' :
                    tox < 80 ? 'var(--accent-red)' : '#dc2626';

                const actionBadge = document.getElementById('flow-action-badge');
                const actionColors = {
                    normal: ['var(--green-dim)', 'var(--accent-green)'],
                    reduce: ['rgba(245,158,11,0.15)', 'var(--accent-yellow)'],
                    widen: ['var(--red-dim)', 'var(--accent-red)'],
                    pull: ['#dc2626', '#fff'],
                };
                const ac = actionColors[f.action] || actionColors.normal;
                actionBadge.textContent = f.action.toUpperCase();
                actionBadge.style.background = ac[0];
                actionBadge.style.color = ac[1];

                document.getElementById('flow-run').textContent = f.max_run;
                document.getElementById('flow-imbalance').textContent = f.imbalance.toFixed(2);
                document.getElementById('flow-momentum').textContent = fmt(f.momentum);
            }

            // ---- Inventory Gauge ----
            if (selectedTicker) {
                const pos = d.positions[selectedTicker];
                const qty = pos ? pos.quantity : 0;
                const maxPos = 100; // Default, could come from config
                const pct = Math.min(Math.abs(qty) / maxPos, 1);
                const gaugeEl = document.getElementById('inv-bar-fill');
                const gaugeLabel = document.getElementById('inv-gauge-value');
                gaugeLabel.textContent = (qty > 0 ? '+' : '') + qty + ' contracts';
                if (qty >= 0) {
                    gaugeEl.style.left = '50%';
                    gaugeEl.style.width = (pct * 50) + '%';
                    gaugeEl.style.background = 'var(--accent-green)';
                } else {
                    gaugeEl.style.left = (50 - pct * 50) + '%';
                    gaugeEl.style.width = (pct * 50) + '%';
                    gaugeEl.style.background = 'var(--accent-red)';
                }
            }
        });

        // ---- Events ----
        socket.on('event', function(evt) {
            eventCount++;
            document.getElementById('event-count').textContent = eventCount + ' events';

            const eventsEl = document.getElementById('events');
            const qhEl = document.getElementById('quote-history-log');
            let tag = '', cls = '', content = '';

            if (evt.type === 'quote') {
                tag = '<span class="evt-tag evt-tag-quote">QUOTE</span>';
                if (evt.data.dry_run) tag += '<span class="evt-tag evt-tag-dry">DRY</span>';
                cls = 'evt-quote';
                content = '<strong>' + evt.data.ticker + '</strong> ' +
                    '<span class="c-green">' + evt.data.bid + 'c</span> x' + evt.data.bid_qty +
                    ' / <span class="c-red">' + evt.data.ask + 'c</span> x' + evt.data.ask_qty +
                    ' <span class="c-muted">(r=' + evt.data.reservation + ', sprd=' + evt.data.spread + 'c)</span>';

                qhEl.insertAdjacentHTML('afterbegin',
                    '<div class="evt ' + cls + '">' +
                    '<span class="evt-time">' + fmtTime(evt.timestamp) + '</span>' +
                    '<span class="evt-content">' + content + '</span></div>');
                while (qhEl.children.length > 30) qhEl.removeChild(qhEl.lastChild);

            } else if (evt.type === 'trade') {
                tag = '<span class="evt-tag evt-tag-trade">FILL</span>';
                cls = 'evt-trade';
                content = '<strong>' + evt.data.ticker + '</strong> Position: ' +
                    evt.data.old_qty + ' &rarr; ' + evt.data.new_qty +
                    ' <span class="c-green">(+' + evt.data.delta + ' fills)</span>';
            } else if (evt.type === 'error') {
                tag = '<span class="evt-tag evt-tag-error">ERR</span>';
                cls = 'evt-error';
                content = evt.data.message;
            }

            eventsEl.insertAdjacentHTML('afterbegin',
                '<div class="evt ' + cls + '">' +
                '<span class="evt-time">' + fmtTime(evt.timestamp) + '</span>' +
                tag + ' ' +
                '<span class="evt-content">' + content + '</span></div>');

            while (eventsEl.children.length > 50) eventsEl.removeChild(eventsEl.lastChild);
        });

        function renderTabs() {
            const container = document.getElementById('market-tabs');
            container.innerHTML = allTickers.map(t =>
                '<div class="market-tab' + (t === selectedTicker ? ' active' : '') + '" onclick="selectTicker(\'' + t + '\')">' + t + '</div>'
            ).join('');
        }

        function selectTicker(t) {
            selectedTicker = t;
            renderTabs();
        }

        socket.on('connect', () => console.log('Connected to dashboard'));
        socket.on('disconnect', () => console.log('Disconnected'));
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
        # Read private key from file
        with open(key_file, 'r') as f:
            private_key = f.read()
        # Test client initialization (will be created again in trading thread)
        test_client = KalshiClient(key_id=key_id, private_key=private_key, host=host)
        print("  Client initialized successfully")
        client_ready = True
    except Exception as e:
        print(f"  Warning: Could not initialize client: {e}")
        print("  Running in offline mode (dashboard only)")
        client_ready = False
        private_key = None

    # Start trading thread if credentials are available
    if client_ready:
        trading_thread = threading.Thread(
            target=trading_loop,
            args=(key_id, private_key, host),
            daemon=True
        )
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
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt (for automated deployments)')

    args = parser.parse_args()

    if args.live and args.env == 'prod' and not args.yes:
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
