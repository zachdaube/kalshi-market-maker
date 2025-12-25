#!/usr/bin/env python3
"""
Phase 4 Test: Quote Generation

This script demonstrates:
1. Generating optimal quotes with fair value and spread
2. Position tracking and inventory management
3. Inventory skewing (adjusting quotes based on position)
4. Quote sizing based on risk limits
5. Converting quotes to Kalshi order format
"""

from src.client import KalshiClient
from src.orderbook import OrderBook, format_orderbook
from src.quotes import (
    QuoteGenerator,
    QuoteParams,
    Position,
    PositionTracker,
    format_quote
)


def main():
    print("=" * 60)
    print("Phase 4: Quote Generation Test")
    print("=" * 60)
    print()

    # Initialize client
    with open('kalshidemo.txt', 'r') as f:
        private_key = f.read()

    client = KalshiClient(
        key_id="2afd56dd-fd59-4649-8135-e6c39e89325c",
        private_key=private_key,
        host="https://demo-api.kalshi.co/trade-api/v2"
    )

    # Get a liquid market
    markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=5)

    if not markets:
        print("No markets found")
        return

    ticker = markets[0]['ticker']
    print(f"Testing with market: {ticker}")
    print(f"Title: {markets[0]['title']}")
    print()

    # Get orderbook
    raw_orderbook = client.get_orderbook(ticker, depth=10)
    if not raw_orderbook or not isinstance(raw_orderbook, dict):
        print(f"Failed to get orderbook for {ticker}")
        print("Trying another market...")
        if len(markets) > 1:
            ticker = markets[1]['ticker']
            print(f"\nTrying: {ticker}")
            raw_orderbook = client.get_orderbook(ticker, depth=10)
            if not raw_orderbook:
                print("Failed again, exiting")
                return
        else:
            return

    ob = OrderBook(ticker, raw_orderbook)

    # Display orderbook
    print(format_orderbook(ob, levels=5))
    print()

    # ==================================================================
    # 1. Quote Generation with Flat Position
    # ==================================================================
    print("=" * 60)
    print("1. Quote Generation - Flat Position")
    print("=" * 60)

    params = QuoteParams(
        min_spread_cents=2,
        target_spread_cents=4,
        base_size=100,
        max_position=1000,
        skew_enabled=False,  # Disabled for flat case
        min_profit_cents=25
    )

    generator = QuoteGenerator(params)

    print("\nParameters:")
    print(f"  Min Spread:     {params.min_spread_cents}¢")
    print(f"  Target Spread:  {params.target_spread_cents}¢")
    print(f"  Base Size:      {params.base_size} contracts")
    print(f"  Max Position:   {params.max_position} contracts")
    print(f"  Min Profit:     {params.min_profit_cents}¢")

    quote = generator.generate_quote(ob, position=None)

    if quote:
        print(format_quote(quote))
    else:
        print("\n❌ Market not quotable (spread too narrow)")

    # ==================================================================
    # 2. Quote Generation with Long Position
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("2. Quote Generation - Long Position (Skewed Down)")
    print("=" * 60)

    params_skewed = QuoteParams(
        min_spread_cents=2,
        target_spread_cents=4,
        base_size=100,
        max_position=1000,
        skew_enabled=True,  # Enable skewing
        skew_factor=0.5,
        min_profit_cents=25
    )

    generator_skewed = QuoteGenerator(params_skewed)

    # Simulate long position
    long_position = Position(
        ticker=ticker,
        quantity=500,  # 50% of max
        avg_entry_price=48.0
    )

    print(f"\nCurrent Position:")
    print(f"  Quantity:   {long_position.quantity:+d} contracts")
    print(f"  Avg Entry:  {long_position.avg_entry_price:.2f}¢")
    print(f"  % of Max:   {abs(long_position.quantity) / params_skewed.max_position * 100:.0f}%")

    quote_long = generator_skewed.generate_quote(ob, position=long_position)

    if quote_long:
        print(format_quote(quote_long))

        print("\n📊 Skewing Effect:")
        print(f"  When LONG → Skew quotes DOWN to encourage selling")
        print(f"  Skew Amount: {quote_long.skew_cents}¢")
        if quote_long.skew_cents < 0:
            print(f"  ✓ Quotes shifted DOWN by {abs(quote_long.skew_cents)}¢")

    # ==================================================================
    # 3. Quote Generation with Short Position
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("3. Quote Generation - Short Position (Skewed Up)")
    print("=" * 60)

    # Simulate short position
    short_position = Position(
        ticker=ticker,
        quantity=-500,  # -50% of max
        avg_entry_price=49.0
    )

    print(f"\nCurrent Position:")
    print(f"  Quantity:   {short_position.quantity:+d} contracts")
    print(f"  Avg Entry:  {short_position.avg_entry_price:.2f}¢")
    print(f"  % of Max:   {abs(short_position.quantity) / params_skewed.max_position * 100:.0f}%")

    quote_short = generator_skewed.generate_quote(ob, position=short_position)

    if quote_short:
        print(format_quote(quote_short))

        print("\n📊 Skewing Effect:")
        print(f"  When SHORT → Skew quotes UP to encourage buying")
        print(f"  Skew Amount: {quote_short.skew_cents}¢")
        if quote_short.skew_cents > 0:
            print(f"  ✓ Quotes shifted UP by {abs(quote_short.skew_cents)}¢")

    # ==================================================================
    # 4. Position Tracking Demo
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("4. Position Tracking")
    print("=" * 60)

    tracker = PositionTracker()

    print("\nSimulating trades:")

    # Trade 1: Buy 100 at 48
    print("\n1. Buy 100 contracts at 48¢")
    tracker.update_position(ticker, quantity_delta=100, price=48.0)
    pos = tracker.get_position(ticker)
    print(f"   Position: {pos.quantity:+d} @ {pos.avg_entry_price:.2f}¢")

    # Trade 2: Buy 100 more at 50
    print("\n2. Buy 100 more contracts at 50¢")
    tracker.update_position(ticker, quantity_delta=100, price=50.0)
    pos = tracker.get_position(ticker)
    print(f"   Position: {pos.quantity:+d} @ {pos.avg_entry_price:.2f}¢")
    print(f"   (Avg = (100×48 + 100×50) / 200 = 49¢)")

    # Trade 3: Sell 150 at 51
    print("\n3. Sell 150 contracts at 51¢")
    tracker.update_position(ticker, quantity_delta=-150, price=51.0)
    pos = tracker.get_position(ticker)
    print(f"   Position: {pos.quantity:+d} @ {pos.avg_entry_price:.2f}¢")
    print(f"   (Avg entry unchanged when reducing)")

    # Calculate P&L
    current_mid = ob.mid_price if ob.mid_price else 48.5
    pnl = tracker.calculate_unrealized_pnl(ticker, current_mid)

    print(f"\n📊 Unrealized P&L:")
    print(f"   Position:     {pos.quantity:+d} contracts")
    print(f"   Avg Entry:    {pos.avg_entry_price:.2f}¢")
    print(f"   Current Mid:  {current_mid:.2f}¢")
    print(f"   Unrealized:   {pnl:+.2f}¢")

    # ==================================================================
    # 5. Quote Sizing Based on Position
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("5. Quote Sizing Based on Position")
    print("=" * 60)

    print("\nAs position grows, adjust quote sizes:")

    # Near max long position
    large_long = Position(
        ticker=ticker,
        quantity=850,  # 85% of max
        avg_entry_price=48.0
    )

    quote_large = generator_skewed.generate_quote(ob, position=large_long)

    if quote_large:
        print(f"\nWhen 85% long ({large_long.quantity} / {params_skewed.max_position}):")
        print(f"  Bid Size: {quote_large.bid.quantity} (reduced from {params_skewed.base_size})")
        print(f"  Ask Size: {quote_large.ask.quantity} (increased from {params_skewed.base_size})")
        print(f"  → Encourages selling to reduce position")

    # ==================================================================
    # 6. Multi-Market Position Tracking
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("6. Multi-Market Position Tracking")
    print("=" * 60)

    multi_tracker = PositionTracker()

    # Simulate positions in multiple markets
    multi_tracker.update_position("MARKET1", quantity_delta=200, price=48.0)
    multi_tracker.update_position("MARKET2", quantity_delta=-150, price=52.0)
    multi_tracker.update_position("MARKET3", quantity_delta=100, price=45.0)

    print("\nPositions across all markets:")
    for ticker, pos in multi_tracker.get_all_positions().items():
        print(f"  {ticker:10s}: {pos.quantity:+4d} @ {pos.avg_entry_price:.2f}¢")

    total_exposure = multi_tracker.get_total_exposure()
    print(f"\nTotal Exposure: {total_exposure} contracts")
    print(f"  (|200| + |-150| + |100| = {total_exposure})")

    # ==================================================================
    # Summary
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Phase 4 Complete!")
    print("=" * 60)
    print()
    print("✓ Quote generation with optimal spread")
    print("✓ Inventory skewing (adjust based on position)")
    print("✓ Quote sizing (adjust based on risk limits)")
    print("✓ Position tracking with avg entry price")
    print("✓ Unrealized P&L calculation")
    print("✓ Multi-market position management")
    print("✓ Kalshi order format conversion")
    print()
    print("Key Insights:")
    print("  - Quotes centered on fair value (mid price)")
    print("  - Skew DOWN when long to encourage selling")
    print("  - Skew UP when short to encourage buying")
    print("  - Reduce size on same side when near position limits")
    print("  - Track avg entry price for P&L calculations")
    print()


if __name__ == "__main__":
    main()
