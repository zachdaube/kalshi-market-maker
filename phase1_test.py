#!/usr/bin/env python3
"""
Phase 1 Test: Kalshi API Connection and Basic Data Retrieval

This script:
1. Authenticates with Kalshi (demo environment)
2. Fetches a list of open markets
3. Gets the orderbook for one market
4. Prints the best bid, best ask, and spread
"""

from src.client import KalshiClient


def main():
    print("=" * 60)
    print("Phase 1: Kalshi API Connection Test")
    print("=" * 60)
    print()

    # Step 1: Read the private key from file
    print("Step 1: Loading API credentials...")
    with open('kalshidemo.txt', 'r') as f:
        private_key = f.read()

    # Demo API Key ID
    key_id = "2afd56dd-fd59-4649-8135-e6c39e89325c"

    print(f"✓ Loaded private key ({len(private_key)} characters)")
    print(f"✓ Using API Key ID: {key_id}")
    print()

    # Step 2: Initialize the Kalshi client
    print("Step 2: Connecting to Kalshi Demo API...")
    client = KalshiClient(
        key_id=key_id,
        private_key=private_key,
        host="https://demo-api.kalshi.co/trade-api/v2"
    )
    print("✓ Client initialized")
    print()

    # Step 3: Fetch open markets
    print("Step 3: Fetching open markets...")
    markets = client.get_markets(status="open", limit=10, series_ticker="KXNFLGAME")

    if not markets:
        print("✗ No markets found or API error")
        return

    print(f"✓ Found {len(markets)} open markets")
    print()
    print("Sample markets:")
    for i, market in enumerate(markets[:5], 1):
        ticker = market.get('ticker', 'N/A')
        title = market.get('title', 'N/A')
        print(f"  {i}. {ticker}: {title}")
    print()

    # Step 4: Get orderbook for the first market
    if markets:
        ticker = markets[0].get('ticker')
        print(f"Step 4: Fetching orderbook for {ticker}...")

        orderbook = client.get_orderbook(ticker, depth=5)

        if orderbook:
            print("✓ Order book retrieved")
            print()
            print("Raw order book format:")
            print(f"  YES bids: {orderbook.get('yes', [])}")
            print(f"  NO bids:  {orderbook.get('no', [])}")
            print()

            # Step 5: Calculate and display best bid, ask, and spread
            print("Step 5: Analyzing order book...")
            print()

            yes_bids = orderbook.get('yes', [])
            no_bids = orderbook.get('no', [])

            # Best YES bid is the highest price someone will pay for YES
            best_yes_bid = max([bid[0] for bid in yes_bids]) if yes_bids else None

            # Best YES ask comes from NO bids
            # A NO bid at price X means someone will pay X for NO
            # This is equivalent to selling YES at (100 - X)
            best_yes_ask = min([100 - bid[0] for bid in no_bids]) if no_bids else None

            print("Market Analysis:")
            print(f"  Best YES bid:  {best_yes_bid}¢" if best_yes_bid else "  Best YES bid:  None")
            print(f"  Best YES ask:  {best_yes_ask}¢" if best_yes_ask else "  Best YES ask:  None")

            if best_yes_bid and best_yes_ask:
                spread = best_yes_ask - best_yes_bid
                mid = (best_yes_bid + best_yes_ask) / 2
                print(f"  Spread:        {spread}¢")
                print(f"  Mid price:     {mid:.2f}¢")
                print()

                # Explain the math
                print("Understanding the order book:")
                print(f"  - YES bid at {best_yes_bid}¢ means: 'I'll pay {best_yes_bid}¢ for YES'")
                if no_bids:
                    # The HIGHEST NO bid gives us the LOWEST YES ask (tightest spread)
                    highest_no_bid = max([bid[0] for bid in no_bids])
                    print(f"  - NO bid at {highest_no_bid}¢ means: 'I'll pay {highest_no_bid}¢ for NO'")
                    print(f"    → Equivalent to: 'I'll sell YES at {100 - highest_no_bid}¢'")
                    print(f"    → So the best YES ask is {100 - highest_no_bid}¢")
            print()
        else:
            print("✗ Failed to retrieve order book")
            print()

    # Step 6: Get account balance
    print("Step 6: Checking account balance...")
    balance = client.get_balance()
    if balance:
        print(f"✓ Account balance: ${balance.get('balance', 0) / 100:.2f}")
    else:
        print("✗ Failed to retrieve balance")
    print()

    print("=" * 60)
    print("Phase 1 Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
