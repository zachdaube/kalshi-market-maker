#!/usr/bin/env python3
"""
Simple Market Maker - REAL ORDER PLACEMENT

This script:
1. Gets a live orderbook from Kalshi
2. Analyzes profitability
3. Generates optimal quotes with Phase 4 logic
4. ACTUALLY PLACES ORDERS on the market

WARNING: This places REAL orders on your demo account!
"""

import sys
import time
from src.client import KalshiClient
from src.orderbook import OrderBook, format_orderbook
from src.quotes import QuoteGenerator, QuoteParams, Position, format_quote
from src.fees import should_quote_market


def get_current_position(client, ticker):
    """
    Get current position for a ticker.

    In a real implementation, this would query the Kalshi API.
    For now, we'll start with a flat position.
    """
    # TODO: In Phase 5/6, implement real position tracking from API
    return Position(ticker=ticker, quantity=0)


def cancel_existing_orders(client, ticker):
    """
    Cancel all existing orders for this ticker.

    This prevents us from having multiple overlapping quotes.
    """
    print(f"\n🔄 Checking for existing orders on {ticker}...")

    open_orders = client.get_open_orders()

    ticker_orders = [o for o in open_orders if o.get('ticker') == ticker]

    if not ticker_orders:
        print("   No existing orders to cancel")
        return 0

    print(f"   Found {len(ticker_orders)} existing orders")

    cancelled = 0
    for order in ticker_orders:
        order_id = order.get('order_id')
        if order_id:
            result = client.cancel_order(order_id)
            if result:
                cancelled += 1
                print(f"   ✓ Cancelled order {order_id}")
            else:
                print(f"   ✗ Failed to cancel {order_id}")

    return cancelled


def place_market_making_orders(client, ticker, dry_run=True):
    """
    Complete market making workflow:
    1. Get orderbook
    2. Analyze profitability
    3. Generate quotes
    4. Place orders (if not dry_run)

    Args:
        client: KalshiClient instance
        ticker: Market ticker
        dry_run: If True, don't actually place orders

    Returns:
        True if orders placed, False otherwise
    """
    print("\n" + "="*60)
    print(f"Market Making on {ticker}")
    print("="*60)

    # 1. Get orderbook
    print("\n📊 Fetching orderbook...")
    raw_orderbook = client.get_orderbook(ticker, depth=10)

    if not raw_orderbook or not isinstance(raw_orderbook, dict):
        print(f"❌ Failed to get orderbook for {ticker}")
        return False

    ob = OrderBook(ticker, raw_orderbook)

    # Check if market is quotable
    if ob.is_empty():
        print("❌ Orderbook is empty")
        return False

    if ob.is_one_sided():
        print("⚠️  Market is one-sided (no asks or no bids)")
        print("   Can't generate two-sided quote")
        return False

    print(format_orderbook(ob, levels=5))

    # 2. Get current position
    position = get_current_position(client, ticker)
    print(f"\n📍 Current Position: {position.quantity:+d} contracts")

    # 3. Set up quote parameters
    params = QuoteParams(
        min_spread_cents=2,      # Need at least 2¢ to be profitable
        target_spread_cents=3,   # Try for 3¢ spread
        base_size=10,            # Small size for safety (10 contracts)
        max_position=100,        # Max 100 contracts long or short
        skew_enabled=True,       # Enable inventory skewing
        skew_factor=0.5,         # Moderate skewing
        min_profit_cents=5       # Want at least 5¢ profit per round trip
    )

    print("\n⚙️  Quote Parameters:")
    print(f"   Target Spread: {params.target_spread_cents}¢")
    print(f"   Quote Size:    {params.base_size} contracts")
    print(f"   Min Profit:    {params.min_profit_cents}¢")

    # 4. Generate quote
    print("\n🎯 Generating quote...")
    generator = QuoteGenerator(params)
    quote = generator.generate_quote(ob, position)

    if not quote:
        print("❌ Market not quotable (spread too narrow or unprofitable)")
        return False

    print(format_quote(quote))

    # 5. Verify profitability one more time
    if quote.expected_profit_cents < params.min_profit_cents:
        print(f"\n❌ Expected profit ({quote.expected_profit_cents:.2f}¢) "
              f"below minimum ({params.min_profit_cents}¢)")
        return False

    # 6. Convert to Kalshi orders
    yes_bid, no_bid = quote.to_kalshi_orders()

    print("\n📝 Orders to place:")
    print(f"   1. YES BID: Buy {yes_bid['quantity']} @ {yes_bid['price']}¢")
    print(f"   2. NO BID:  Buy {no_bid['quantity']} @ {no_bid['price']}¢")
    print(f"      (implements YES ask @ {quote.ask.price_cents}¢)")

    # 7. Place orders (if not dry run)
    if dry_run:
        print("\n🔒 DRY RUN MODE - Orders NOT placed")
        print("   Set dry_run=False to actually place orders")
        return False

    # Cancel existing orders first
    cancel_existing_orders(client, ticker)

    print("\n🚀 Placing orders on Kalshi...")

    # Place YES bid
    print("\n1️⃣  Placing YES bid...")
    yes_order = client.place_order(
        ticker=ticker,
        side="yes",
        action="buy",
        quantity=yes_bid['quantity'],
        price=yes_bid['price'],
        order_type="limit",
        client_order_id=f"mm_yes_bid_{ticker}_{int(time.time())}"
    )

    if yes_order:
        print(f"   ✅ YES bid placed: Order ID {yes_order.get('order_id')}")
        print(f"      Status: {yes_order.get('status')}")
    else:
        print("   ❌ Failed to place YES bid")
        return False

    time.sleep(0.5)  # Small delay between orders

    # Place NO bid (implements YES ask)
    print("\n2️⃣  Placing NO bid (YES ask)...")
    no_order = client.place_order(
        ticker=ticker,
        side="no",
        action="buy",
        quantity=no_bid['quantity'],
        price=no_bid['price'],
        order_type="limit",
        client_order_id=f"mm_no_bid_{ticker}_{int(time.time())}"
    )

    if no_order:
        print(f"   ✅ NO bid placed: Order ID {no_order.get('order_id')}")
        print(f"      Status: {no_order.get('status')}")
    else:
        print("   ❌ Failed to place NO bid")
        # Cancel the YES bid since we couldn't place both sides
        print("   ⚠️  Cancelling YES bid (couldn't place both sides)")
        client.cancel_order(yes_order.get('order_id'))
        return False

    print("\n✅ TWO-SIDED MARKET MADE!")
    print(f"   Bid: {quote.bid.price_cents}¢ × {quote.bid.quantity}")
    print(f"   Ask: {quote.ask.price_cents}¢ × {quote.ask.quantity}")
    print(f"   Expected Profit: {quote.expected_profit_cents:.2f}¢")

    return True


def main():
    print("="*60)
    print("SIMPLE MARKET MAKER - REAL ORDER PLACEMENT")
    print("="*60)
    print()

    # Parse command line arguments
    dry_run = True  # Default to dry run
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        dry_run = False
        print("⚠️  LIVE MODE - Orders WILL be placed!")
        print()
        response = input("Are you sure? Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return
    else:
        print("🔒 DRY RUN MODE (use --live to actually place orders)")

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
    print(f"💰 Account Balance: ${balance['balance'] / 100:.2f}")
    print()

    # Find a liquid market
    print("🔍 Finding liquid markets...")
    markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=10)

    if not markets:
        print("❌ No markets found")
        return

    print(f"✅ Found {len(markets)} NFL markets")
    print()

    # Try to market make on the first market with a good orderbook
    success = False
    for i, market in enumerate(markets):
        ticker = market['ticker']
        title = market['title']

        print(f"\n📍 Attempting {i+1}/{len(markets)}: {title}")

        result = place_market_making_orders(client, ticker, dry_run=dry_run)

        if result:
            success = True
            break
        else:
            print(f"   ⏭️  Skipping to next market...")

    # Final summary
    print("\n\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    if not dry_run:
        # Show all open orders
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
        print(f"\n💰 Final Balance: ${final_balance['balance'] / 100:.2f}")

    if success:
        print("\n✅ Market making successful!")
        if dry_run:
            print("   Run with --live to actually place orders")
    else:
        print("\n⚠️  Could not find a suitable market to make")
        print("   Possible reasons:")
        print("   - All markets are one-sided")
        print("   - Spreads too narrow to be profitable")
        print("   - Markets are closed")

    print()


if __name__ == "__main__":
    main()
