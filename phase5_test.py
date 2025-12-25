#!/usr/bin/env python3
"""
Phase 5 Test: Flow Detection & Toxic Flow Protection

This script demonstrates:
1. Analyzing real trade flow from Kalshi
2. Detecting runs (consecutive trades in same direction)
3. Detecting trade imbalance (heavy buying/selling)
4. Detecting price momentum
5. Calculating toxicity scores
6. Recommending quote adjustments based on flow
"""

from datetime import datetime, timedelta
from src.client import KalshiClient
from src.flow import (
    FlowAnalyzer,
    FlowConfig,
    Trade,
    parse_kalshi_trades,
    format_flow_metrics,
    format_adjustment
)


def simulate_toxic_flow_scenarios():
    """
    Demonstrate flow detection with simulated scenarios.

    This is useful for understanding how the system responds to
    different types of toxic flow patterns.
    """
    print("=" * 60)
    print("Simulated Flow Scenarios")
    print("=" * 60)

    analyzer = FlowAnalyzer()

    # ==================================================================
    # Scenario 1: Normal Flow (Balanced Trading)
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Scenario 1: Normal Flow")
    print("=" * 60)
    print("\nSimulating balanced trading with alternating buy/sell...")

    trades = []
    base_time = datetime.now() - timedelta(seconds=10)

    for i in range(6):
        side = "yes" if i % 2 == 0 else "no"
        trades.append(Trade(
            ticker="SCENARIO1",
            price=50,
            quantity=100,
            side=side,
            timestamp=base_time + timedelta(seconds=i)
        ))

    analyzer.add_trades(trades)
    metrics = analyzer.analyze_flow("SCENARIO1")

    if metrics:
        print(format_flow_metrics(metrics))
        adj = analyzer.recommend_adjustment("SCENARIO1")
        print(format_adjustment(adj))

    # ==================================================================
    # Scenario 2: Toxic Run (Consecutive Buys)
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Scenario 2: Toxic Run (7 Consecutive Buys)")
    print("=" * 60)
    print("\nSimulating informed buying - someone knows something!")

    analyzer.clear_history()  # Reset
    trades = []
    base_time = datetime.now() - timedelta(seconds=7)

    for i in range(7):
        trades.append(Trade(
            ticker="SCENARIO2",
            price=48 + i,  # Price rising
            quantity=150,
            side="yes",  # All buys
            timestamp=base_time + timedelta(seconds=i)
        ))

    analyzer.add_trades(trades)
    metrics = analyzer.analyze_flow("SCENARIO2")

    if metrics:
        print(format_flow_metrics(metrics))
        adj = analyzer.recommend_adjustment("SCENARIO2")
        print(format_adjustment(adj))

        print("\n💡 Insight:")
        print("   7 consecutive buys suggests informed trader")
        print("   Price rising confirms strong demand")
        print("   → Pull quotes or widen significantly to avoid adverse selection")

    # ==================================================================
    # Scenario 3: Heavy Imbalance
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Scenario 3: Heavy Imbalance (80% Sell Pressure)")
    print("=" * 60)
    print("\nSimulating heavy selling pressure...")

    analyzer.clear_history()
    trades = []
    base_time = datetime.now() - timedelta(seconds=10)

    # 8 sells, 2 buys
    for i in range(8):
        trades.append(Trade(
            ticker="SCENARIO3",
            price=50 - i,  # Price falling
            quantity=100,
            side="no",  # Selling (buying NO = selling YES)
            timestamp=base_time + timedelta(seconds=i)
        ))

    for i in range(2):
        trades.append(Trade(
            ticker="SCENARIO3",
            price=45,
            quantity=50,
            side="yes",
            timestamp=base_time + timedelta(seconds=8 + i)
        ))

    analyzer.add_trades(trades)
    metrics = analyzer.analyze_flow("SCENARIO3")

    if metrics:
        print(format_flow_metrics(metrics))
        adj = analyzer.recommend_adjustment("SCENARIO3")
        print(format_adjustment(adj))

    # ==================================================================
    # Scenario 4: Price Momentum
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Scenario 4: Sharp Price Movement")
    print("=" * 60)
    print("\nSimulating rapid price increase (10¢ in 5 trades)...")

    analyzer.clear_history()
    trades = []
    base_time = datetime.now() - timedelta(seconds=5)

    for i in range(5):
        trades.append(Trade(
            ticker="SCENARIO4",
            price=45 + (i * 2),  # 45, 47, 49, 51, 53
            quantity=200,
            side="yes",
            timestamp=base_time + timedelta(seconds=i)
        ))

    analyzer.add_trades(trades)
    metrics = analyzer.analyze_flow("SCENARIO4")

    if metrics:
        print(format_flow_metrics(metrics))
        adj = analyzer.recommend_adjustment("SCENARIO4")
        print(format_adjustment(adj))

        print("\n💡 Insight:")
        print(f"   Price moved {metrics.price_change}¢ in {metrics.trades_count} trades")
        print(f"   Velocity: {metrics.price_velocity:.2f}¢ per trade")
        print("   → Rapid price movement suggests new information")

    # ==================================================================
    # Scenario 5: Evolving Flow
    # ==================================================================
    print("\n\n" + "=" * 60)
    print("Scenario 5: Evolving Flow (Normal → Toxic)")
    print("=" * 60)
    print("\nShowing how flow can change over time...")

    analyzer.clear_history()

    # Start with normal flow
    print("\nPhase 1: Normal trading")
    trades = []
    base_time = datetime.now() - timedelta(seconds=10)

    for i in range(4):
        side = "yes" if i % 2 == 0 else "no"
        trades.append(Trade(
            ticker="SCENARIO5",
            price=50,
            quantity=100,
            side=side,
            timestamp=base_time + timedelta(seconds=i)
        ))

    analyzer.add_trades(trades)
    metrics1 = analyzer.analyze_flow("SCENARIO5")

    if metrics1:
        print(f"   Toxicity: {metrics1.toxicity_score:.0f}/100 ({metrics1.trades_count} trades)")
        adj1 = analyzer.recommend_adjustment("SCENARIO5")
        print(f"   Action: {adj1.action.upper()}")

    # Add toxic flow
    print("\nPhase 2: Toxic flow develops (5 consecutive buys)")
    toxic_trades = []
    for i in range(5):
        toxic_trades.append(Trade(
            ticker="SCENARIO5",
            price=51 + i,
            quantity=200,
            side="yes",
            timestamp=base_time + timedelta(seconds=4 + i)
        ))

    analyzer.add_trades(toxic_trades)
    metrics2 = analyzer.analyze_flow("SCENARIO5")

    if metrics2:
        print(f"   Toxicity: {metrics2.toxicity_score:.0f}/100 ({metrics2.trades_count} trades)")
        adj2 = analyzer.recommend_adjustment("SCENARIO5")
        print(f"   Action: {adj2.action.upper()}")

        print("\n💡 Insight:")
        print(f"   Toxicity increased from {metrics1.toxicity_score:.0f} → {metrics2.toxicity_score:.0f}")
        print(f"   Action changed from {adj1.action} → {adj2.action}")
        print("   → System adapts to changing market conditions")


def analyze_real_market_flow():
    """
    Analyze real trade flow from a Kalshi market.

    This demonstrates the full workflow with live data.
    """
    print("\n\n" + "=" * 60)
    print("Real Market Flow Analysis")
    print("=" * 60)

    # Initialize client
    try:
        with open('kalshidemo.txt', 'r') as f:
            private_key = f.read()
    except FileNotFoundError:
        print("\n⚠️  Could not find kalshidemo.txt")
        print("   Skipping real market analysis")
        return

    client = KalshiClient(
        key_id="2afd56dd-fd59-4649-8135-e6c39e89325c",
        private_key=private_key,
        host="https://demo-api.kalshi.co/trade-api/v2"
    )

    # Get active markets
    print("\n🔍 Finding active markets...")
    markets = client.get_markets(status="open", series_ticker="KXNFLGAME", limit=5)

    if not markets:
        print("❌ No markets found")
        return

    # Analyze first market with trade history
    print(f"✅ Found {len(markets)} markets\n")

    for market in markets[:3]:  # Try first 3 markets
        ticker = market['ticker']
        title = market.get('title', ticker)

        print(f"\n{'='*60}")
        print(f"Market: {ticker}")
        print(f"Title: {title}")
        print(f"{'='*60}")

        # Get recent trades
        print("\n📊 Fetching recent trades...")
        raw_trades = client.get_trades(ticker, limit=20)

        if not raw_trades:
            print("   No trades found, trying next market...")
            continue

        print(f"   Found {len(raw_trades)} trades")

        # Parse trades
        trades = parse_kalshi_trades(raw_trades)

        if len(trades) < 2:
            print("   Insufficient trades for analysis")
            continue

        # Analyze flow
        analyzer = FlowAnalyzer()
        analyzer.add_trades(trades)

        metrics = analyzer.analyze_flow(ticker)

        if metrics:
            print(format_flow_metrics(metrics))

            # Get recommendation
            adj = analyzer.recommend_adjustment(ticker)
            print(format_adjustment(adj))

            # Interpretation
            print("\n💡 Market Maker Interpretation:")

            if adj.action == "normal":
                print("   ✅ Safe to quote with normal parameters")
                print("   Flow appears balanced and non-toxic")

            elif adj.action == "reduce":
                print(f"   ⚡ Quote with caution:")
                print(f"      - Widen spread to {adj.spread_multiplier:.1f}x normal")
                print(f"      - Reduce size to {adj.size_multiplier:.1f}x normal")
                print(f"      - Monitor for further deterioration")

            elif adj.action == "widen":
                print(f"   ⚠️  Elevated risk detected:")
                print(f"      - Widen spread to {adj.spread_multiplier:.1f}x normal")
                print(f"      - Reduce size to {adj.size_multiplier:.1f}x normal")
                print(f"      - Wait {adj.cooldown_seconds:.0f}s before requoting")
                print(f"      - Consider sitting out temporarily")

            elif adj.action == "pull":
                print(f"   🛑 TOXIC FLOW - PULL QUOTES IMMEDIATELY")
                print(f"      - Remove all quotes from this market")
                print(f"      - Wait {adj.cooldown_seconds:.0f}s before reconsidering")
                print(f"      - Likely informed trader in the market")
                print(f"      - Protect capital by not participating")

            # Break after first successful analysis
            break

    else:
        print("\n⚠️  Could not find markets with sufficient trade history")


def demonstrate_custom_configuration():
    """Show how to customize flow detection parameters."""
    print("\n\n" + "=" * 60)
    print("Custom Configuration")
    print("=" * 60)
    print("\nDemonstrating custom detection thresholds...")

    # Strict configuration (more sensitive)
    strict_config = FlowConfig(
        toxic_run_length=3,  # Trigger at 3 instead of 5
        toxic_imbalance=0.6,  # 60% instead of 70%
        toxic_price_change=3,  # 3¢ instead of 5¢
        run_weight=0.40,  # More weight on runs
        imbalance_weight=0.35,
        momentum_weight=0.20,
        volume_weight=0.05
    )

    # Relaxed configuration (less sensitive)
    relaxed_config = FlowConfig(
        toxic_run_length=7,  # Trigger at 7 instead of 5
        toxic_imbalance=0.8,  # 80% instead of 70%
        toxic_price_change=8,  # 8¢ instead of 5¢
        run_weight=0.25,
        imbalance_weight=0.25,
        momentum_weight=0.30,
        volume_weight=0.20
    )

    # Same flow pattern
    trades = []
    base_time = datetime.now() - timedelta(seconds=5)

    for i in range(5):
        trades.append(Trade(
            ticker="TEST",
            price=48 + i,
            quantity=150,
            side="yes",
            timestamp=base_time + timedelta(seconds=i)
        ))

    # Analyze with default config
    print("\n1️⃣  Default Configuration:")
    default_analyzer = FlowAnalyzer()
    default_analyzer.add_trades(trades)
    default_metrics = default_analyzer.analyze_flow("TEST")

    if default_metrics:
        print(f"   Toxicity: {default_metrics.toxicity_score:.0f}/100")
        default_adj = default_analyzer.recommend_adjustment("TEST")
        print(f"   Action: {default_adj.action.upper()}")

    # Analyze with strict config
    print("\n2️⃣  Strict Configuration (more sensitive):")
    strict_analyzer = FlowAnalyzer(strict_config)
    strict_analyzer.add_trades(trades)
    strict_metrics = strict_analyzer.analyze_flow("TEST")

    if strict_metrics:
        print(f"   Toxicity: {strict_metrics.toxicity_score:.0f}/100")
        strict_adj = strict_analyzer.recommend_adjustment("TEST")
        print(f"   Action: {strict_adj.action.upper()}")

    # Analyze with relaxed config
    print("\n3️⃣  Relaxed Configuration (less sensitive):")
    relaxed_analyzer = FlowAnalyzer(relaxed_config)
    relaxed_analyzer.add_trades(trades)
    relaxed_metrics = relaxed_analyzer.analyze_flow("TEST")

    if relaxed_metrics:
        print(f"   Toxicity: {relaxed_metrics.toxicity_score:.0f}/100")
        relaxed_adj = relaxed_analyzer.recommend_adjustment("TEST")
        print(f"   Action: {relaxed_adj.action.upper()}")

    print("\n💡 Insight:")
    print("   Same flow pattern, different responses based on risk tolerance")
    print("   - Strict: Better protection, more false positives")
    print("   - Relaxed: More uptime, higher risk of adverse selection")
    print("   - Default: Balanced approach for most market makers")


def main():
    print("=" * 60)
    print("Phase 5: Flow Detection & Toxic Flow Protection")
    print("=" * 60)
    print()

    # Part 1: Simulated scenarios
    simulate_toxic_flow_scenarios()

    # Part 2: Real market analysis
    analyze_real_market_flow()

    # Part 3: Custom configuration
    demonstrate_custom_configuration()

    # Summary
    print("\n\n" + "=" * 60)
    print("Phase 5 Complete!")
    print("=" * 60)
    print()
    print("✓ Trade flow analysis")
    print("✓ Run detection (consecutive same-direction trades)")
    print("✓ Trade imbalance detection (buy/sell pressure)")
    print("✓ Price momentum tracking")
    print("✓ Toxicity scoring (0-100)")
    print("✓ Adaptive quote adjustments (normal/reduce/widen/pull)")
    print("✓ Multi-market flow tracking")
    print("✓ Configurable detection thresholds")
    print()
    print("Key Insights:")
    print("  - Toxic flow = informed traders who will pick you off")
    print("  - Runs of 5+ same-direction trades are suspicious")
    print("  - Heavy imbalance (>70%) suggests one-sided information")
    print("  - Sharp price moves (>5¢) indicate new information")
    print("  - When toxic: Pull quotes or widen significantly")
    print("  - Better to miss a fill than lose to adverse selection")
    print()


if __name__ == "__main__":
    main()
