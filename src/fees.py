"""
Fee Economics for Kalshi Market Making

Kalshi's fee structure (as of 2024):
- Maker fee: 1.75% of potential profit = 0.0175 × C × P × (1-P)
- Taker fee: 7.00% of potential profit = 0.07 × C × P × (1-P)

Where:
  C = number of contracts
  P = price in decimal (0.48 for 48¢)

The fee formula C × P × (1-P) represents the "at risk" amount:
- If you buy YES at 48¢, you risk 48¢ per contract
- If YES wins, you profit 52¢ per contract
- Fee is charged on min(risk, profit) = min(48¢, 52¢) = 48¢

Key insights:
1. Fees are symmetric around 50¢ (worst at mid, better at extremes)
2. Maker fees are 4x lower than taker fees
3. Round-trip maker fees: 2 × 0.0175 = 3.5% of risk
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class FeeCalculation:
    """Result of fee calculation."""
    contracts: int
    price_cents: int
    price_decimal: float
    risk_per_contract: float  # min(price, 1-price) in dollars
    total_risk: float  # Total amount at risk in dollars
    fee_dollars: float  # Fee in dollars
    fee_cents: float  # Fee in cents (for easier comparison)
    fee_rate: float  # Effective fee rate (e.g., 0.0175)


@dataclass
class ProfitabilityAnalysis:
    """Analysis of trade profitability including fees."""
    contracts: int
    entry_price_cents: int
    exit_price_cents: int
    spread_cents: int

    # Gross P&L (before fees)
    gross_profit_cents: float
    gross_profit_dollars: float

    # Fees
    entry_fee: FeeCalculation
    exit_fee: FeeCalculation
    total_fees_cents: float
    total_fees_dollars: float

    # Net P&L (after fees)
    net_profit_cents: float
    net_profit_dollars: float

    # Profitability metrics
    is_profitable: bool
    profit_per_contract_cents: float
    roi_percent: float  # Return on investment


# Fee rates
MAKER_FEE_RATE = 0.0175  # 1.75%
TAKER_FEE_RATE = 0.07    # 7.00%


def calculate_fee(
    contracts: int,
    price_cents: int,
    fee_rate: float = MAKER_FEE_RATE
) -> FeeCalculation:
    """
    Calculate Kalshi fee for a trade.

    Formula: fee = fee_rate × contracts × price × (1 - price)

    Args:
        contracts: Number of contracts
        price_cents: Price in cents (0-100)
        fee_rate: Fee rate (0.0175 for maker, 0.07 for taker)

    Returns:
        FeeCalculation with detailed breakdown

    Examples:
        >>> calc = calculate_fee(100, 48, MAKER_FEE_RATE)
        >>> calc.fee_cents  # 4.368 cents

        >>> calc = calculate_fee(100, 50, MAKER_FEE_RATE)
        >>> calc.fee_cents  # 4.375 cents (worst case, at mid)

        >>> calc = calculate_fee(100, 10, MAKER_FEE_RATE)
        >>> calc.fee_cents  # 1.575 cents (better at extremes)
    """
    # Convert to decimal (48¢ → 0.48)
    price_decimal = price_cents / 100.0

    # Calculate risk per contract (the smaller of price and 1-price)
    # This represents potential profit OR potential loss
    risk_per_contract = min(price_decimal, 1 - price_decimal)

    # Total at-risk amount
    total_risk = contracts * risk_per_contract

    # Calculate fee: rate × contracts × P × (1-P)
    fee_dollars = fee_rate * contracts * price_decimal * (1 - price_decimal)
    fee_cents = fee_dollars * 100

    return FeeCalculation(
        contracts=contracts,
        price_cents=price_cents,
        price_decimal=price_decimal,
        risk_per_contract=risk_per_contract,
        total_risk=total_risk,
        fee_dollars=fee_dollars,
        fee_cents=fee_cents,
        fee_rate=fee_rate
    )


def calculate_maker_fee(contracts: int, price_cents: int) -> FeeCalculation:
    """Calculate maker fee (for providing liquidity)."""
    return calculate_fee(contracts, price_cents, MAKER_FEE_RATE)


def calculate_taker_fee(contracts: int, price_cents: int) -> FeeCalculation:
    """Calculate taker fee (for taking liquidity)."""
    return calculate_fee(contracts, price_cents, TAKER_FEE_RATE)


def calculate_round_trip_fee(
    contracts: int,
    entry_price_cents: int,
    exit_price_cents: int,
    as_maker: bool = True
) -> float:
    """
    Calculate total fees for a round-trip trade (entry + exit).

    Args:
        contracts: Number of contracts
        entry_price_cents: Entry price in cents
        exit_price_cents: Exit price in cents
        as_maker: True if both legs are maker, False if both are taker

    Returns:
        Total fees in cents

    Example:
        >>> # Buy at 48¢, sell at 49¢ (both maker)
        >>> fee = calculate_round_trip_fee(100, 48, 49, as_maker=True)
        >>> fee  # ~8.73 cents total
    """
    fee_rate = MAKER_FEE_RATE if as_maker else TAKER_FEE_RATE

    entry_fee = calculate_fee(contracts, entry_price_cents, fee_rate)
    exit_fee = calculate_fee(contracts, exit_price_cents, fee_rate)

    return entry_fee.fee_cents + exit_fee.fee_cents


def analyze_profitability(
    contracts: int,
    entry_price_cents: int,
    exit_price_cents: int,
    as_maker: bool = True
) -> ProfitabilityAnalysis:
    """
    Comprehensive profitability analysis for a round-trip trade.

    Args:
        contracts: Number of contracts
        entry_price_cents: Entry price in cents
        exit_price_cents: Exit price in cents
        as_maker: True if trading as maker, False if as taker

    Returns:
        ProfitabilityAnalysis with gross/net P&L, fees, and metrics

    Example:
        >>> # Market making: buy at 48¢, sell at 49¢
        >>> analysis = analyze_profitability(100, 48, 49, as_maker=True)
        >>> analysis.gross_profit_cents  # 100 cents (1¢ × 100 contracts)
        >>> analysis.total_fees_cents    # ~8.73 cents
        >>> analysis.net_profit_cents    # ~91.27 cents
        >>> analysis.is_profitable       # True
    """
    fee_rate = MAKER_FEE_RATE if as_maker else TAKER_FEE_RATE

    # Spread
    spread_cents = exit_price_cents - entry_price_cents

    # Gross profit (before fees)
    gross_profit_cents = spread_cents * contracts
    gross_profit_dollars = gross_profit_cents / 100.0

    # Fees
    entry_fee = calculate_fee(contracts, entry_price_cents, fee_rate)
    exit_fee = calculate_fee(contracts, exit_price_cents, fee_rate)
    total_fees_cents = entry_fee.fee_cents + exit_fee.fee_cents
    total_fees_dollars = total_fees_cents / 100.0

    # Net profit (after fees)
    net_profit_cents = gross_profit_cents - total_fees_cents
    net_profit_dollars = net_profit_cents / 100.0

    # Metrics
    is_profitable = net_profit_cents > 0
    profit_per_contract_cents = net_profit_cents / contracts if contracts > 0 else 0

    # ROI: net profit / capital at risk
    capital_at_risk = (entry_price_cents * contracts) / 100.0  # in dollars
    roi_percent = (net_profit_dollars / capital_at_risk * 100) if capital_at_risk > 0 else 0

    return ProfitabilityAnalysis(
        contracts=contracts,
        entry_price_cents=entry_price_cents,
        exit_price_cents=exit_price_cents,
        spread_cents=spread_cents,
        gross_profit_cents=gross_profit_cents,
        gross_profit_dollars=gross_profit_dollars,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        total_fees_cents=total_fees_cents,
        total_fees_dollars=total_fees_dollars,
        net_profit_cents=net_profit_cents,
        net_profit_dollars=net_profit_dollars,
        is_profitable=is_profitable,
        profit_per_contract_cents=profit_per_contract_cents,
        roi_percent=roi_percent
    )


def min_spread_for_breakeven(
    contracts: int,
    mid_price_cents: int,
    as_maker: bool = True
) -> int:
    """
    Calculate minimum spread (in cents) to break even after fees.

    Args:
        contracts: Number of contracts
        mid_price_cents: Mid price in cents (where we'll quote around)
        as_maker: True if maker, False if taker

    Returns:
        Minimum spread in cents to break even

    Example:
        >>> # At 50¢ mid (worst case for fees)
        >>> min_spread = min_spread_for_breakeven(100, 50, as_maker=True)
        >>> min_spread  # ~9 cents

        >>> # At 30¢ mid (better for fees)
        >>> min_spread = min_spread_for_breakeven(100, 30, as_maker=True)
        >>> min_spread  # ~8 cents
    """
    # Binary search for minimum profitable spread
    for spread in range(1, 50):  # Max spread is 50¢
        bid = mid_price_cents - spread // 2
        ask = mid_price_cents + spread // 2

        # Ensure valid prices
        if bid < 1 or ask > 99:
            continue

        analysis = analyze_profitability(contracts, bid, ask, as_maker)

        if analysis.is_profitable:
            return spread

    return 50  # Fallback (shouldn't reach here)


def min_spread_for_profit(
    contracts: int,
    mid_price_cents: int,
    target_profit_cents: float,
    as_maker: bool = True
) -> int:
    """
    Calculate minimum spread to achieve target profit after fees.

    Args:
        contracts: Number of contracts
        mid_price_cents: Mid price in cents
        target_profit_cents: Desired net profit in cents
        as_maker: True if maker, False if taker

    Returns:
        Minimum spread in cents to achieve target profit

    Example:
        >>> # Want to make 50¢ profit after fees
        >>> spread = min_spread_for_profit(100, 50, target_profit_cents=50)
        >>> spread  # ~14 cents
    """
    for spread in range(1, 50):
        bid = mid_price_cents - spread // 2
        ask = mid_price_cents + spread // 2

        if bid < 1 or ask > 99:
            continue

        analysis = analyze_profitability(contracts, bid, ask, as_maker)

        if analysis.net_profit_cents >= target_profit_cents:
            return spread

    return 50  # Fallback


def expected_profit_per_round_trip(
    spread_cents: int,
    contracts: int,
    mid_price_cents: int,
    as_maker: bool = True
) -> float:
    """
    Calculate expected net profit for a round-trip at given spread.

    Args:
        spread_cents: Spread in cents
        contracts: Number of contracts
        mid_price_cents: Mid price in cents
        as_maker: True if maker, False if taker

    Returns:
        Net profit in cents (can be negative if unprofitable)

    Example:
        >>> # 1¢ spread, 100 contracts at 48¢ mid
        >>> profit = expected_profit_per_round_trip(1, 100, 48, as_maker=True)
        >>> profit  # ~91 cents net
    """
    bid = mid_price_cents - spread_cents // 2
    ask = mid_price_cents + spread_cents // 2

    # Clamp to valid range
    bid = max(1, bid)
    ask = min(99, ask)

    analysis = analyze_profitability(contracts, bid, ask, as_maker)
    return analysis.net_profit_cents


def should_quote_market(
    spread_cents: int,
    contracts: int,
    mid_price_cents: int,
    min_profit_cents: float = 10.0,
    as_maker: bool = True
) -> Dict[str, Any]:
    """
    Determine if a market is worth quoting based on profitability.

    Args:
        spread_cents: Current spread in cents
        contracts: Target position size
        mid_price_cents: Mid price in cents
        min_profit_cents: Minimum acceptable profit in cents
        as_maker: True if maker, False if taker

    Returns:
        Dict with:
            - should_quote: bool
            - reason: str
            - analysis: ProfitabilityAnalysis
            - recommended_bid: int
            - recommended_ask: int

    Example:
        >>> result = should_quote_market(
        ...     spread_cents=2,
        ...     contracts=100,
        ...     mid_price_cents=48,
        ...     min_profit_cents=50
        ... )
        >>> result['should_quote']  # True if spread is wide enough
    """
    bid = mid_price_cents - spread_cents // 2
    ask = mid_price_cents + spread_cents // 2

    # Clamp to valid range
    bid = max(1, bid)
    ask = min(99, ask)

    analysis = analyze_profitability(contracts, bid, ask, as_maker)

    # Decision logic
    should_quote = analysis.net_profit_cents >= min_profit_cents

    if should_quote:
        reason = f"Profitable: {analysis.net_profit_cents:.2f}¢ net profit (target: {min_profit_cents}¢)"
    else:
        breakeven_spread = min_spread_for_breakeven(contracts, mid_price_cents, as_maker)
        profitable_spread = min_spread_for_profit(contracts, mid_price_cents, min_profit_cents, as_maker)
        reason = (f"Unprofitable: {analysis.net_profit_cents:.2f}¢ < {min_profit_cents}¢. "
                 f"Need {profitable_spread}¢ spread (current: {spread_cents}¢, "
                 f"breakeven: {breakeven_spread}¢)")

    return {
        'should_quote': should_quote,
        'reason': reason,
        'analysis': analysis,
        'recommended_bid': bid,
        'recommended_ask': ask,
        'min_profitable_spread': min_spread_for_profit(contracts, mid_price_cents, min_profit_cents, as_maker),
        'breakeven_spread': min_spread_for_breakeven(contracts, mid_price_cents, as_maker)
    }


def format_fee_calculation(calc: FeeCalculation) -> str:
    """Pretty-print a fee calculation."""
    lines = []
    lines.append(f"Fee Calculation:")
    lines.append(f"  Contracts:     {calc.contracts}")
    lines.append(f"  Price:         {calc.price_cents}¢ ({calc.price_decimal:.2f})")
    lines.append(f"  Fee Rate:      {calc.fee_rate * 100:.2f}%")
    lines.append(f"  Risk/Contract: ${calc.risk_per_contract:.4f}")
    lines.append(f"  Total Risk:    ${calc.total_risk:.2f}")
    lines.append(f"  Fee:           {calc.fee_cents:.4f}¢ (${calc.fee_dollars:.6f})")
    return "\n".join(lines)


def format_profitability_analysis(analysis: ProfitabilityAnalysis) -> str:
    """Pretty-print a profitability analysis."""
    lines = []
    lines.append("=" * 60)
    lines.append("Profitability Analysis")
    lines.append("=" * 60)
    lines.append(f"\nTrade Details:")
    lines.append(f"  Contracts:     {analysis.contracts}")
    lines.append(f"  Entry:         {analysis.entry_price_cents}¢")
    lines.append(f"  Exit:          {analysis.exit_price_cents}¢")
    lines.append(f"  Spread:        {analysis.spread_cents}¢")

    lines.append(f"\nGross P&L (before fees):")
    lines.append(f"  Total:         {analysis.gross_profit_cents:.2f}¢ (${analysis.gross_profit_dollars:.4f})")
    lines.append(f"  Per Contract:  {analysis.spread_cents}¢")

    lines.append(f"\nFees:")
    lines.append(f"  Entry Fee:     {analysis.entry_fee.fee_cents:.4f}¢ (${analysis.entry_fee.fee_dollars:.6f})")
    lines.append(f"  Exit Fee:      {analysis.exit_fee.fee_cents:.4f}¢ (${analysis.exit_fee.fee_dollars:.6f})")
    lines.append(f"  Total Fees:    {analysis.total_fees_cents:.4f}¢ (${analysis.total_fees_dollars:.6f})")

    lines.append(f"\nNet P&L (after fees):")
    lines.append(f"  Total:         {analysis.net_profit_cents:.2f}¢ (${analysis.net_profit_dollars:.4f})")
    lines.append(f"  Per Contract:  {analysis.profit_per_contract_cents:.4f}¢")
    lines.append(f"  ROI:           {analysis.roi_percent:.2f}%")

    status = "✅ PROFITABLE" if analysis.is_profitable else "❌ UNPROFITABLE"
    lines.append(f"\nStatus: {status}")
    lines.append("=" * 60)

    return "\n".join(lines)
