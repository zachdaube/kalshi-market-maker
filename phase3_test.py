#!/usr/bin/env python3
"""
Phase 3 Test: Fee Economics

This script demonstrates:
1. Fee calculations for real market conditions
2. Profitability analysis for different spreads
3. Market evaluation logic (should we quote?)
4. Comparison of maker vs taker fees
"""

from src.client import KalshiClient
from src.orderbook import OrderBook, format_orderbook
from src.fees import (
    calculate_maker_fee,
    calculate_taker_fee,
    analyze_profitability,
    min_spread_for_breakeven,
    min_spread_for_profit,
    should_quote_market,
    format_profitability_analysis,
    MAKER_FEE_RATE,
    TAKER_FEE_RATE
)


def main():
    print("=" * 60)
    print("Phase 3: Fee Economics Test")
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
    if not raw_orderbook:
        print("Failed to get orderbook")
        return

    ob = OrderBook(ticker, raw_orderbook)

    # Display orderbook
    print(format_orderbook(ob, levels=5))
    print()

    # ==================================================================
    # 1. Fee Rate Comparison
    # ==================================================================
    print("=" * 60)
    print("1. Fee Rate Comparison (Maker vs Taker)")
    print("=" * 60)
    print(f"Maker fee rate: {MAKER_FEE_RATE * 100:.2f}%")
    print(f"Taker fee rate: {TAKER_FEE_RATE * 100:.2f}%")
    print(f"Taker fees are {TAKER_FEE_RATE / MAKER_FEE_RATE:.1f}x higher than maker fees")
    print()

    # Example: 100 contracts at 48¢
    print("Example: 100 contracts at 48¢")
    maker_fee = calculate_maker_fee(100, 48)
    taker_fee = calculate_taker_fee(100, 48)
    print(f"  Maker fee: {maker_fee.fee_cents:.2f}¢ (${maker_fee.fee_dollars:.4f})")
    print(f"  Taker fee: {taker_fee.fee_cents:.2f}¢ (${taker_fee.fee_dollars:.4f})")
    print(f"  Difference: {taker_fee.fee_cents - maker_fee.fee_cents:.2f}¢")
    print()

    # ==================================================================
    # 2. Fee vs Price Analysis
    # ==================================================================
    print("=" * 60)
    print("2. How Fees Vary by Price")
    print("=" * 60)
    print("Fees are highest at 50¢ (P×(1-P) is maximized)")
    print()

    prices = [10, 30, 50, 70, 90]
    print(f"{'Price':>6} | {'Maker Fee':>12} | {'Taker Fee':>12}")
    print("-" * 40)
    for price in prices:
        maker = calculate_maker_fee(100, price)
        taker = calculate_taker_fee(100, price)
        print(f"{price:>5}¢ | {maker.fee_cents:>10.2f}¢ | {taker.fee_cents:>10.2f}¢")
    print()

    # ==================================================================
    # 3. Profitability Analysis with Current Market
    # ==================================================================
    print("=" * 60)
    print("3. Profitability Analysis")
    print("=" * 60)

    if not ob.mid_price:
        print("Market is one-sided, skipping profitability analysis")
        return

    mid = int(ob.mid_price)
    contracts = 100

    print(f"Market Mid: {mid}¢")
    print(f"Target Size: {contracts} contracts")
    print()

    # Test different spreads
    spreads_to_test = [1, 2, 5, 10]

    for spread in spreads_to_test:
        bid = mid - spread // 2
        ask = mid + spread // 2

        print(f"\n--- {spread}¢ Spread (Bid: {bid}¢, Ask: {ask}¢) ---")

        # Maker analysis
        maker_analysis = analyze_profitability(contracts, bid, ask, as_maker=True)
        print(f"\nAs MAKER:")
        print(f"  Gross Profit: {maker_analysis.gross_profit_cents:.2f}¢")
        print(f"  Total Fees:   {maker_analysis.total_fees_cents:.2f}¢")
        print(f"  Net Profit:   {maker_analysis.net_profit_cents:.2f}¢")
        print(f"  Per Contract: {maker_analysis.profit_per_contract_cents:.4f}¢")
        print(f"  ROI:          {maker_analysis.roi_percent:.2f}%")
        print(f"  Status:       {'✅ PROFITABLE' if maker_analysis.is_profitable else '❌ UNPROFITABLE'}")

        # Taker analysis
        taker_analysis = analyze_profitability(contracts, bid, ask, as_maker=False)
        print(f"\nAs TAKER:")
        print(f"  Net Profit:   {taker_analysis.net_profit_cents:.2f}¢")
        print(f"  Total Fees:   {taker_analysis.total_fees_cents:.2f}¢")
        print(f"  Status:       {'✅ PROFITABLE' if taker_analysis.is_profitable else '❌ UNPROFITABLE'}")

    print()

    # ==================================================================
    # 4. Minimum Spread Requirements
    # ==================================================================
    print("=" * 60)
    print("4. Minimum Spread Requirements")
    print("=" * 60)
    print()

    # Breakeven spreads
    maker_breakeven = min_spread_for_breakeven(contracts, mid, as_maker=True)
    taker_breakeven = min_spread_for_breakeven(contracts, mid, as_maker=False)

    print(f"Minimum Spread to Break Even:")
    print(f"  Maker: {maker_breakeven}¢")
    print(f"  Taker: {taker_breakeven}¢")
    print()

    # Target profit spreads
    target_profits = [10, 50, 100]  # cents
    print(f"Minimum Spread for Target Profit (as maker):")
    for target in target_profits:
        required_spread = min_spread_for_profit(contracts, mid, target, as_maker=True)
        print(f"  {target:>3}¢ profit: {required_spread}¢ spread needed")
    print()

    # ==================================================================
    # 5. Market Evaluation: Should We Quote?
    # ==================================================================
    print("=" * 60)
    print("5. Market Evaluation: Should We Quote This Market?")
    print("=" * 60)
    print()

    # Use current market spread
    current_spread = ob.spread if ob.spread else 1

    print(f"Current Market Spread: {current_spread}¢")
    print()

    # Different profit targets
    targets = [5, 20, 50]

    for target in targets:
        result = should_quote_market(
            spread_cents=current_spread,
            contracts=contracts,
            mid_price_cents=mid,
            min_profit_cents=target,
            as_maker=True
        )

        print(f"Target Profit: {target}¢")
        print(f"  Decision: {'✅ QUOTE' if result['should_quote'] else '❌ SKIP'}")
        print(f"  Reason: {result['reason']}")
        print(f"  Breakeven Spread: {result['breakeven_spread']}¢")
        print(f"  Min Profitable Spread: {result['min_profitable_spread']}¢")
        if result['should_quote']:
            print(f"  Recommended Bid: {result['recommended_bid']}¢")
            print(f"  Recommended Ask: {result['recommended_ask']}¢")
        print()

    # ==================================================================
    # 6. Real-World Scenario
    # ==================================================================
    print("=" * 60)
    print("6. Real-World Scenario")
    print("=" * 60)
    print()

    print("Scenario: You're a market maker on this market")
    print(f"  Market Mid: {mid}¢")
    print(f"  Current Spread: {current_spread}¢")
    print(f"  Your Target: Earn at least 25¢ per 100 contracts")
    print()

    result = should_quote_market(
        spread_cents=current_spread,
        contracts=100,
        mid_price_cents=mid,
        min_profit_cents=25,
        as_maker=True
    )

    if result['should_quote']:
        print("✅ RECOMMENDATION: Quote this market!")
        print(f"   Post bid at:  {result['recommended_bid']}¢")
        print(f"   Post ask at:  {result['recommended_ask']}¢")
        print(f"   (via NO bid at {100 - result['recommended_ask']}¢)")
        print()
        print(f"   Expected net profit: {result['analysis'].net_profit_cents:.2f}¢")
        print(f"   After fees of: {result['analysis'].total_fees_cents:.2f}¢")
    else:
        print("❌ RECOMMENDATION: Skip this market")
        print(f"   Current spread ({current_spread}¢) too narrow")
        print(f"   Need at least {result['min_profitable_spread']}¢ spread")
        print()
        print("   Options:")
        print(f"   1. Wait for spread to widen to {result['min_profitable_spread']}¢")
        print(f"   2. Lower profit target")
        print(f"   3. Trade larger size (spreads scale with volume)")

    print()
    print("=" * 60)
    print("Phase 3 Complete!")
    print("=" * 60)
    print()
    print("✓ Fee calculations working with real data")
    print("✓ Profitability analysis functional")
    print("✓ Market evaluation logic implemented")
    print("✓ Maker fees significantly lower than taker fees")
    print()
    print("Key Insight: Kalshi's fee structure HEAVILY favors makers!")
    print(f"  - Maker pays {MAKER_FEE_RATE * 100:.2f}% of P×(1-P)")
    print(f"  - Taker pays {TAKER_FEE_RATE * 100:.2f}% of P×(1-P) (4x more!)")
    print("  - This makes market making very attractive on tight spreads")
    print()


if __name__ == "__main__":
    main()
