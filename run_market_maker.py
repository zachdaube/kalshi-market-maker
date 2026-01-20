#!/usr/bin/env python3
"""
Kalshi Market Maker - Avellaneda-Stoikov Model

Usage:
  python run_market_maker.py --env demo
  python run_market_maker.py --env demo --live
"""

import sys
import signal
import argparse
import yaml
from pathlib import Path

from src.client import KalshiClient
from src.execution import ExecutionEngine
from src.config_loader import load_config, ConfigLoader


def main():
    parser = argparse.ArgumentParser(description="Kalshi AS Market Maker")
    parser.add_argument('--env', type=str, default='demo', help='Environment (demo/prod)')
    parser.add_argument('--live', action='store_true', help='Enable live trading')
    args = parser.parse_args()

    print("=" * 50)
    print("Kalshi Market Maker (Avellaneda-Stoikov)")
    print("=" * 50)

    # Load config
    try:
        config = load_config(args.env)
        print(f"Loaded config: {args.env}")
    except Exception as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Override dry_run if --live
    if args.live:
        print("WARNING: LIVE MODE - Real money at risk!")
        config.dry_run = False

    print(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE'}")
    print(f"Markets: {list(config.markets.keys())}")

    # Load API config separately
    config_file = Path("config") / f"{args.env}.yaml"
    with open(config_file) as f:
        raw_config = yaml.safe_load(f)

    loader = ConfigLoader()
    raw_config = loader._expand_env_vars(raw_config)
    api = raw_config['api']

    # Create client
    try:
        with open(api['private_key_file']) as f:
            private_key = f.read()

        client = KalshiClient(
            key_id=api['key_id'],
            private_key=private_key,
            host=api['host']
        )
        print(f"Connected to {api['host']}")
    except Exception as e:
        print(f"API error: {e}")
        sys.exit(1)

    # Create and start engine
    engine = ExecutionEngine(client, config)

    def shutdown(sig, frame):
        print("\nShutting down...")
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Starting... (Ctrl+C to stop)")
    print("=" * 50)
    engine.start()


if __name__ == "__main__":
    main()
