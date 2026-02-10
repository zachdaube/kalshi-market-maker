#!/usr/bin/env python3
"""
Kalshi Market Scanner CLI

Scans all open Kalshi markets and ranks them by profitability
for the Avellaneda-Stoikov market making strategy.

Usage:
    python scan_markets.py --env demo
    python scan_markets.py --env prod --top 10 --min-volume 100
    python scan_markets.py --env prod --yaml  # Output suggested config
"""

import argparse
import os
import time

from src.client import KalshiClient
from src.config_loader import ConfigLoader
from src.scanner import ScanConfig, scan_markets, format_results, generate_config_yaml


def main():
    parser = argparse.ArgumentParser(description='Kalshi Market Scanner')
    parser.add_argument('--env', choices=['demo', 'prod'], default='demo',
                        help='Environment (demo or prod)')
    parser.add_argument('--top', type=int, default=20,
                        help='Number of top markets to display')
    parser.add_argument('--min-spread', type=int, default=2,
                        help='Minimum spread in cents')
    parser.add_argument('--min-volume', type=int, default=10,
                        help='Minimum 24h volume')
    parser.add_argument('--min-days', type=float, default=1.0,
                        help='Minimum days to expiry')
    parser.add_argument('--max-days', type=float, default=365.0,
                        help='Maximum days to expiry')
    parser.add_argument('--yaml', action='store_true',
                        help='Output YAML config for top markets')
    parser.add_argument('--yaml-count', type=int, default=5,
                        help='Number of markets in YAML output')
    parser.add_argument('--series', type=str, default=None,
                        help='Filter by series ticker')
    parser.add_argument('--event', type=str, default=None,
                        help='Filter by event ticker')
    args = parser.parse_args()

    # Load config and create client
    loader = ConfigLoader()
    cfg = loader.load(args.env)
    api_cfg = cfg['api']

    key_id = os.environ.get('KALSHI_KEY_ID', api_cfg.get('key_id', ''))
    key_file = api_cfg.get('private_key_file', 'kalshidemo.txt')
    host = api_cfg.get('host', 'https://demo-api.kalshi.co/trade-api/v2')

    with open(key_file, 'r') as f:
        private_key = f.read()

    client = KalshiClient(key_id=key_id, private_key=private_key, host=host)
    print(f"[SCANNER] Connected to {host}")

    # Fetch all open markets
    print("[SCANNER] Fetching open markets...")
    start = time.time()
    raw_markets = client.get_all_markets(
        status="open",
        series_ticker=args.series,
        event_ticker=args.event,
    )
    elapsed = time.time() - start
    print(f"[SCANNER] Fetched {len(raw_markets)} open markets in {elapsed:.1f}s")

    # Configure scanner
    scan_config = ScanConfig(
        min_spread=args.min_spread,
        min_volume_24h=args.min_volume,
        min_days_to_expiry=args.min_days,
        max_days_to_expiry=args.max_days,
        top_n=args.top,
    )

    # Run scan
    print("[SCANNER] Scoring markets...")
    results = scan_markets(raw_markets, scan_config)
    print(f"[SCANNER] Found {len(results)} markets matching criteria\n")

    if args.yaml:
        print(generate_config_yaml(results, top_n=args.yaml_count))
    else:
        print(format_results(results))


if __name__ == '__main__':
    main()
