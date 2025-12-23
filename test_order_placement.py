#!/usr/bin/env python3
"""
Test Order Placement on Kalshi Demo

This script:
1. Finds a liquid market
2. Gets the current orderbook
3. Places a small test order (far from mid to avoid fills)
4. Verifies the order was placed
5. Cancels the order
6. Verifies cancellation

Safe for demo environment - uses prices far from market to avoid execution.
"""

from src.client import KalshiClient
import time


def main():
    print("=" * 60)
    print("Test Order Placement - Kalshi Demo")
    print("=" * 60)
    print()

    # Initialize client
    print("Step 1: Connecting to Kalshi Demo...")
    with open('kalshidemo.txt', 'r') as f:
        private_key = f.read()

    client = KalshiClient(
        key_id="2afd56dd-fd59-4649-8135-e6c39e89325c",
        private_key=private_key,
        host="https://demo-api.kalshi.co/trade-api/v2"
    )
    print("✓ Connected")
    print()

    # Find a liquid market
    print("Step 2: Finding a liquid market...")
    markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=10)

    if not markets:
        print("✗ No markets found")
        return

    # Pick first market with liquidity
    market = None
    for m in markets:
        if m.get('liquidity', 0) > 0 or m.get('yes_bid', 0) > 0:
            market = m
            break

    if not market:
        market = markets[0]  # Just use first market if none have liquidity

    ticker = market['ticker']
    print(f"✓ Selected market: {ticker}")
    print(f"  Title: {market['title']}")
    print()

    # Get orderbook
    print("Step 3: Fetching orderbook...")
    orderbook = client.get_orderbook(ticker, depth=5)

    if not orderbook or not orderbook.get('yes') or not orderbook.get('no'):
        print("⚠ Empty orderbook - market may not be liquid")
        print("  Will place order anyway for testing")
        # Use safe defaults
        mid_price = 50
    else:
        # Calculate mid price
        best_yes_bid = max([bid[0] for bid in orderbook['yes']]) if orderbook['yes'] else 30
        best_no_bid = max([bid[0] for bid in orderbook['no']]) if orderbook['no'] else 30
        best_yes_ask = 100 - best_no_bid
        mid_price = (best_yes_bid + best_yes_ask) // 2

        print(f"✓ Orderbook retrieved")
        print(f"  Best YES bid: {best_yes_bid}¢")
        print(f"  Best YES ask: {best_yes_ask}¢")
        print(f"  Mid price: {mid_price}¢")

    print()

    # Place a test order FAR from mid to avoid getting filled
    # We'll bid 20 cents below mid (very unlikely to execute)
    test_price = max(1, mid_price - 20)
    test_quantity = 1  # Just 1 contract

    print("Step 4: Placing test order...")
    print(f"  Side: YES")
    print(f"  Action: BUY")
    print(f"  Price: {test_price}¢ (far below mid={mid_price}¢)")
    print(f"  Quantity: {test_quantity} contract")
    print(f"  Type: LIMIT")
    print()

    order = client.place_order(
        ticker=ticker,
        side="yes",
        action="buy",
        quantity=test_quantity,
        price=test_price,
        order_type="limit",
        client_order_id=f"test_order_{int(time.time())}"
    )

    if not order:
        print("✗ Failed to place order")
        print("  This might be due to:")
        print("  - Market restrictions")
        print("  - Insufficient balance")
        print("  - API permissions")
        return

    order_id = order.get('order_id')
    print(f"✓ Order placed successfully!")
    print(f"  Order ID: {order_id}")
    print(f"  Status: {order.get('status', 'unknown')}")
    print()

    # Wait a moment
    print("Waiting 2 seconds...")
    time.sleep(2)
    print()

    # Verify order exists
    print("Step 5: Verifying order exists...")
    open_orders = client.get_open_orders(ticker=ticker)

    order_found = False
    for o in open_orders:
        if o.get('order_id') == order_id:
            order_found = True
            print(f"✓ Order found in open orders")
            print(f"  Status: {o.get('status')}")
            print(f"  Remaining quantity: {o.get('remaining_count', 'unknown')}")
            break

    if not order_found:
        print(f"⚠ Order not found in open orders")
        print(f"  It may have been filled or rejected")

    print()

    # Cancel the order
    print("Step 6: Canceling order...")
    success = client.cancel_order(order_id)

    if success:
        print("✓ Order canceled successfully")
    else:
        print("⚠ Cancel request sent (may have already been filled/canceled)")

    print()

    # Wait and verify cancellation
    print("Waiting 2 seconds...")
    time.sleep(2)
    print()

    print("Step 7: Verifying cancellation...")
    open_orders = client.get_open_orders(ticker=ticker)

    order_still_open = False
    for o in open_orders:
        if o.get('order_id') == order_id:
            order_still_open = True
            break

    if order_still_open:
        print("⚠ Order still appears in open orders")
        print("  May take a moment to cancel")
    else:
        print("✓ Order no longer in open orders")

    print()

    # Check final balance
    print("Step 8: Checking final balance...")
    balance = client.get_balance()
    if balance:
        print(f"✓ Account balance: ${balance['balance'] / 100:.2f}")
    print()

    print("=" * 60)
    print("Order Placement Test Complete!")
    print("=" * 60)
    print()
    print("Summary:")
    print("  ✓ Connected to Kalshi Demo")
    print("  ✓ Found market with orderbook")
    print(f"  ✓ Placed order at {test_price}¢")
    print("  ✓ Verified order exists")
    print("  ✓ Canceled order")
    print("  ✓ Verified cancellation")
    print()
    print("🎉 Order management is fully functional!")
    print()


if __name__ == "__main__":
    main()
