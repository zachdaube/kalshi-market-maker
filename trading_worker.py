#!/usr/bin/env python3
"""
Standalone trading worker - runs separately from the Flask dashboard.
This avoids SDK compatibility issues with Flask-SocketIO.
"""

import time
import sys
import os
import signal
import yaml

from src.client import KalshiClient
from src.orderbook import OrderBook
from src.quotes import generate_quote, ASParams, Position, PositionTracker
from src.execution import ExecutionConfig, MarketConfig
from src.flow import FlowAnalyzer, FlowConfig, parse_kalshi_trades


def load_config(env: str):
    """Load configuration with env var expansion."""
    from src.config_loader import ConfigLoader
    loader = ConfigLoader()
    return loader.load(env)


def cancel_all_active_orders(client, active_orders):
    """Cancel all tracked active orders."""
    for ticker, orders in active_orders.items():
        for order_id in [orders.get('yes_order_id'), orders.get('no_order_id')]:
            if order_id:
                try:
                    client.cancel_order(order_id)
                    print(f"[WORKER] Cancelled {order_id}")
                except Exception:
                    pass
    active_orders.clear()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Kalshi Trading Worker')
    parser.add_argument('--env', choices=['demo', 'prod'], default='demo')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()

    # Wait for network to be fully ready at container startup
    print("[WORKER] Waiting for network...", flush=True)
    time.sleep(5)

    cfg = load_config(args.env)
    dry_run = not args.live

    # API setup
    api_cfg = cfg['api']
    key_id = os.environ.get('KALSHI_KEY_ID', api_cfg.get('key_id', ''))
    key_file = api_cfg.get('private_key_file', 'kalshidemo.txt')
    host = api_cfg.get('host', 'https://demo-api.kalshi.co/trade-api/v2')

    with open(key_file, 'r') as f:
        private_key = f.read()

    client = KalshiClient(key_id=key_id, private_key=private_key, host=host)
    print(f"[WORKER] Client initialized - {host}")
    print(f"[WORKER] Dry run: {dry_run}")

    # Build market configs
    markets = {}
    for m in cfg['markets']:
        if m.get('enabled', True):
            ticker = m['ticker']
            markets[ticker] = MarketConfig(
                ticker=ticker,
                enabled=True,
                gamma=m.get('gamma', 0.1),
                sigma=m.get('sigma', 2.0),
                k=m.get('k', 1.5),
                base_size=m.get('base_size', 10),
                max_position=m.get('max_position', 100),
                max_loss_cents=m.get('max_loss_cents', 500.0)
            )

    exec_cfg = cfg['execution']
    quote_interval = exec_cfg.get('quote_interval', 1.0)
    position_sync_interval = exec_cfg.get('position_sync_interval', 5.0)
    cancel_threshold = exec_cfg.get('cancel_threshold', 1)
    total_max_position = exec_cfg.get('total_max_position', 500)

    position_tracker = PositionTracker()
    last_quotes = {}
    active_orders = {}  # ticker -> {'yes_order_id': ..., 'no_order_id': ...}
    flow_analyzer = FlowAnalyzer(FlowConfig())
    flow_cooldowns = {}  # ticker -> cooldown_until timestamp
    running = True

    # Signal handler for graceful shutdown (SIGTERM from docker stop)
    def shutdown(signum, frame):
        nonlocal running
        print(f"\n[WORKER] Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"[WORKER] Markets: {list(markets.keys())}")
    print(f"[WORKER] Total max position: {total_max_position}")
    print(f"[WORKER] Starting trading loop...")

    last_sync = 0
    loop_count = 0

    try:
        while running:
            loop_count += 1

            # Sync positions periodically
            if time.time() - last_sync > position_sync_interval:
                try:
                    positions = client.get_positions()
                    for p in positions:
                        ticker = p.get('ticker')
                        qty = p.get('position', 0)
                        avg_price = p.get('average_price_paid') or p.get('avg_price')
                        current = position_tracker.get_position(ticker)
                        position_tracker.positions[ticker] = Position(
                            ticker, qty, avg_price if avg_price else current.avg_entry_price
                        )
                    print(f"[WORKER] Positions synced: {len(positions)} markets")
                except Exception as e:
                    print(f"[WORKER] Position sync error: {e}")
                last_sync = time.time()

            # Check global position limit
            total_exposure = position_tracker.get_total_exposure()
            if total_exposure > total_max_position:
                print(f"[WORKER] Position limit exceeded ({total_exposure}/{total_max_position}), pulling all quotes")
                cancel_all_active_orders(client, active_orders)
                time.sleep(quote_interval)
                continue

            # Update each market
            for ticker, mc in markets.items():
                try:
                    # Fetch orderbook
                    raw_ob = client.get_orderbook(ticker, depth=10)
                    if not raw_ob or (not raw_ob.get('yes') and not raw_ob.get('no')):
                        continue

                    ob = OrderBook(ticker, raw_ob)
                    if ob.mid_price is None:
                        continue

                    # Get position
                    pos = position_tracker.get_position(ticker)

                    # Stop loss check
                    if pos.quantity != 0 and pos.avg_entry_price:
                        pnl = (ob.mid_price - pos.avg_entry_price) * pos.quantity
                        if pnl < -mc.max_loss_cents:
                            print(f"[WORKER] Stop loss {ticker}: PnL={pnl:.0f}c (limit={-mc.max_loss_cents}c)")
                            # Cancel orders for this market
                            if ticker in active_orders:
                                for order_id in [active_orders[ticker].get('yes_order_id'), active_orders[ticker].get('no_order_id')]:
                                    if order_id:
                                        try:
                                            client.cancel_order(order_id)
                                        except Exception:
                                            pass
                                active_orders[ticker] = {}
                            continue

                    # Flow detection
                    flow_adjustment = flow_analyzer.recommend_adjustment(ticker)
                    try:
                        raw_trades = client.get_trades(ticker, limit=20)
                        if raw_trades:
                            trades = parse_kalshi_trades(raw_trades)
                            flow_analyzer.add_trades(trades)
                            flow_adjustment = flow_analyzer.recommend_adjustment(ticker)
                    except Exception as e:
                        print(f"[WORKER] Flow analysis error {ticker}: {e}")

                    if flow_adjustment.action == "pull":
                        print(f"[WORKER] Flow PULL {ticker}: {flow_adjustment.reason}")
                        if ticker in active_orders:
                            for order_id in [active_orders[ticker].get('yes_order_id'), active_orders[ticker].get('no_order_id')]:
                                if order_id:
                                    try:
                                        client.cancel_order(order_id)
                                    except Exception:
                                        pass
                            active_orders[ticker] = {}
                        flow_cooldowns[ticker] = time.time() + flow_adjustment.cooldown_seconds
                        continue

                    if time.time() < flow_cooldowns.get(ticker, 0):
                        continue

                    # Generate quote
                    params = ASParams(
                        gamma=mc.gamma,
                        sigma=mc.sigma,
                        k=mc.k,
                        max_position=mc.max_position,
                        base_size=mc.base_size
                    )
                    quote = generate_quote(ticker, ob.mid_price, pos, params)

                    if not quote:
                        continue

                    # Apply flow adjustments (widen spread, reduce size)
                    if flow_adjustment.spread_multiplier != 1.0 or flow_adjustment.size_multiplier != 1.0:
                        print(f"[WORKER] Flow adjust {ticker}: {flow_adjustment.action} "
                              f"(spread x{flow_adjustment.spread_multiplier}, size x{flow_adjustment.size_multiplier})")
                        mid = quote.reservation_price
                        half_spread = (quote.ask.price_cents - quote.bid.price_cents) / 2.0
                        new_half = half_spread * flow_adjustment.spread_multiplier
                        new_bid = max(1, min(98, int(round(mid - new_half))))
                        new_ask = max(2, min(99, int(round(mid + new_half))))
                        if new_bid >= new_ask:
                            new_bid = max(1, int(mid) - 1)
                            new_ask = min(99, int(mid) + 1)
                        if new_bid >= new_ask:
                            continue
                        quote.bid.price_cents = new_bid
                        quote.ask.price_cents = new_ask
                        quote.spread_cents = new_ask - new_bid
                        quote.bid.quantity = max(1, int(quote.bid.quantity * flow_adjustment.size_multiplier))
                        quote.ask.quantity = max(1, int(quote.ask.quantity * flow_adjustment.size_multiplier))

                    # Check if quote changed significantly
                    if ticker in last_quotes:
                        lq = last_quotes[ticker]
                        bid_diff = abs(quote.bid.price_cents - lq.bid.price_cents)
                        ask_diff = abs(quote.ask.price_cents - lq.ask.price_cents)
                        if bid_diff < cancel_threshold and ask_diff < cancel_threshold:
                            continue

                    # Cancel existing orders
                    if ticker in active_orders:
                        for order_id in [active_orders[ticker].get('yes_order_id'), active_orders[ticker].get('no_order_id')]:
                            if order_id:
                                try:
                                    client.cancel_order(order_id)
                                except Exception:
                                    pass
                        active_orders[ticker] = {}

                    print(f"[WORKER] {ticker}: bid={quote.bid.price_cents}c, ask={quote.ask.price_cents}c, mid={ob.mid_price}, pos={pos.quantity}")

                    if dry_run:
                        last_quotes[ticker] = quote
                        continue

                    # Place real orders
                    yes_bid, no_bid = quote.to_kalshi_orders()
                    active_orders[ticker] = {}

                    resp = client.place_order(
                        ticker=ticker,
                        side=yes_bid['side'],
                        action=yes_bid['action'],
                        quantity=yes_bid['quantity'],
                        price=yes_bid['price'],
                        order_type="limit"
                    )
                    if resp:
                        active_orders[ticker]['yes_order_id'] = resp.get('order_id')
                        print(f"[WORKER] Placed YES order: {resp.get('order_id')}")

                    resp = client.place_order(
                        ticker=ticker,
                        side=no_bid['side'],
                        action=no_bid['action'],
                        quantity=no_bid['quantity'],
                        price=no_bid['price'],
                        order_type="limit"
                    )
                    if resp:
                        active_orders[ticker]['no_order_id'] = resp.get('order_id')
                        print(f"[WORKER] Placed NO order: {resp.get('order_id')}")

                    last_quotes[ticker] = quote

                except Exception as e:
                    print(f"[WORKER] Error updating {ticker}: {e}")

            time.sleep(quote_interval)

    except Exception as e:
        print(f"[WORKER] Fatal error: {e}")
    finally:
        print("[WORKER] Cancelling all orders...")
        cancel_all_active_orders(client, active_orders)
        print("[WORKER] Shutdown complete.")


if __name__ == '__main__':
    main()
