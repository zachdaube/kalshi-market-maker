#!/usr/bin/env python3
"""
Place Demo Orders on Kalshi

This script places real limit orders on 2 different markets.
Orders are placed far from mid to avoid immediate fills.
Orders are NOT canceled - they will rest on the orderbook.

Strategy: Post quotes 15-20 cents from mid on both sides.
"""

from src.client import KalshiClient
from src.orderbook import OrderBook
import time


def place_orders_on_market(client, ticker, title):
    """Place two-sided quotes on a single market."""
    print(f"\n{'='*60}")
    print(f"Market: {ticker}")
    print(f"Title: {title}")
    print('='*60)

    # Get orderbook
    raw_orderbook = client.get_orderbook(ticker, depth=5)
    if not raw_orderbook:
        print("⚠ Could not get orderbook, skipping market")
        return False

    ob = OrderBook(ticker, raw_orderbook)

    # Display current market
    if ob.best_bid and ob.best_ask:
        print(f"\nCurrent Market:")
        print(f"  Best Bid: {ob.best_bid}¢")
        print(f"  Best Ask: {ob.best_ask}¢")
        print(f"  Mid:      {ob.mid_price:.1f}¢")
        print(f"  Spread:   {ob.spread}¢")
    else:
        print("\n⚠ No two-sided market, using default pricing")
        mid = 50

    # Calculate quote prices (far from mid to avoid fills)
    mid = ob.mid_price if ob.mid_price else 50

    # Our bid: 15 cents below mid (very unlikely to fill)
    our_bid_price = max(1, int(mid - 15))

    # Our ask: 15 cents above mid (very unlikely to fill)
    our_ask_price = min(99, int(mid + 15))

    quantity = 1  # Just 1 contract each

    print(f"\n📝 Placing Orders:")
    print(f"  BID:  {our_bid_price}¢ × {quantity} (buy YES)")
    print(f"  ASK:  {our_ask_price}¢ × {quantity} (sell YES via NO bid)")

    # Place BID order (buy YES)
    print(f"\n1️⃣  Placing BID order...")
    bid_order = client.place_order(
        ticker=ticker,
        side="yes",
        action="buy",
        quantity=quantity,
        price=our_bid_price,
        order_type="limit",
        client_order_id=f"demo_bid_{ticker}_{int(time.time())}"
    )

    if bid_order:
        print(f"   ✓ BID placed: Order ID {bid_order.get('order_id')}")
        print(f"     Status: {bid_order.get('status')}")
    else:
        print(f"   ✗ BID failed to place")
        return False

    time.sleep(1)  # Small delay between orders

    # Place ASK order (sell YES by buying NO at complementary price)
    # To sell YES at X¢, we buy NO at (100-X)¢
    no_bid_price = 100 - our_ask_price

    print(f"\n2️⃣  Placing ASK order (via NO bid at {no_bid_price}¢)...")
    ask_order = client.place_order(
        ticker=ticker,
        side="no",
        action="buy",
        quantity=quantity,
        price=no_bid_price,
        order_type="limit",
        client_order_id=f"demo_ask_{ticker}_{int(time.time())}"
    )

    if ask_order:
        print(f"   ✓ ASK placed: Order ID {ask_order.get('order_id')}")
        print(f"     Status: {ask_order.get('status')}")
        print(f"     (NO bid at {no_bid_price}¢ = YES ask at {our_ask_price}¢)")
    else:
        print(f"   ✗ ASK failed to place")
        return False

    print(f"\n✅ Two-sided market made on {ticker}")
    print(f"   Bid: {our_bid_price}¢  |  Ask: {our_ask_price}¢  |  Width: {our_ask_price - our_bid_price}¢")

    return True


def main():
    print("="*60)
    print("Place Demo Orders - Kalshi Market Making")
    print("="*60)
    print()
    print("⚠️  This will place REAL orders on demo markets")
    print("📌 Orders will NOT be canceled")
    print("💰 Using demo account balance")
    print()

    # Initialize client
    with open('kalshidemo.txt', 'r') as f:
        private_key = f.read()

    client = KalshiClient(
        key_id="2afd56dd-fd59-4649-8135-e6c39e89325c",
        private_key=private_key,
        host="https://demo-api.kalshi.co/trade-api/v2"
    )

    # Get balance
    balance = client.get_balance()
    print(f"Account Balance: ${balance['balance'] / 100:.2f}")
    print()

    # Find 2 liquid markets
    print("Finding markets...")
    markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=10)

    if len(markets) < 2:
        print("❌ Not enough markets found")
        return

    print(f"✓ Found {len(markets)} NFL markets")
    print()

    # Place orders on first 2 markets
    markets_traded = 0
    for i, market in enumerate(markets[:3]):  # Try up to 3 to get 2 successful
        ticker = market['ticker']
        title = market['title']

        success = place_orders_on_market(client, ticker, title)

        if success:
            markets_traded += 1

        if markets_traded >= 2:
            break

        time.sleep(2)  # Delay between markets

    # Final summary
    print(f"\n{'='*60}")
    print("Summary")
    print('='*60)

    # Check all open orders
    open_orders = client.get_open_orders()
    print(f"\n📊 Open Orders: {len(open_orders)}")

    for order in open_orders:
        ticker = order.get('ticker', 'UNKNOWN')
        side = order.get('side', '?')
        price = order.get('yes_price') if side == 'yes' else order.get('no_price')
        qty = order.get('remaining_count', order.get('count', '?'))
        status = order.get('status', '?')

        print(f"  • {ticker[:30]:30} | {side:3} {price:2}¢ × {qty:2} | {status}")

    # Final balance
    final_balance = client.get_balance()
    print(f"\nFinal Balance: ${final_balance['balance'] / 100:.2f}")

    print()
    print("="*60)
    print("✅ Demo Orders Placed Successfully!")
    print("="*60)
    print()
    print("Your orders are now resting on the Kalshi demo orderbook.")
    print("They will remain open until:")
    print("  1. They get filled (someone takes your liquidity)")
    print("  2. The market closes")
    print("  3. You manually cancel them")
    print()
    print("💡 You are now providing liquidity as a market maker!")
    print()


if __name__ == "__main__":
    main()
