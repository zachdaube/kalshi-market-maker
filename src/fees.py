"""
Kalshi Fee Calculations

Kalshi fees:
- Maker: 1.75% of potential profit = 0.0175 × C × P × (1-P)
- Taker: 7.00% of potential profit = 0.07 × C × P × (1-P)

Where C = contracts, P = price in decimal (0.48 for 48¢)
"""

from dataclasses import dataclass

MAKER_FEE_RATE = 0.0175
TAKER_FEE_RATE = 0.07


@dataclass
class FeeResult:
    """Fee calculation result."""
    contracts: int
    price_cents: int
    fee_cents: float
    fee_rate: float


def calculate_fee(contracts: int, price_cents: int, as_maker: bool = True) -> FeeResult:
    """
    Calculate Kalshi fee.

    Formula: fee = rate × contracts × P × (1-P)
    """
    rate = MAKER_FEE_RATE if as_maker else TAKER_FEE_RATE
    p = price_cents / 100.0
    fee_dollars = rate * contracts * p * (1 - p)

    return FeeResult(
        contracts=contracts,
        price_cents=price_cents,
        fee_cents=fee_dollars * 100,
        fee_rate=rate
    )


def round_trip_fee(contracts: int, bid: int, ask: int, as_maker: bool = True) -> float:
    """Total fees for buy at bid, sell at ask."""
    entry = calculate_fee(contracts, bid, as_maker)
    exit_fee = calculate_fee(contracts, ask, as_maker)
    return entry.fee_cents + exit_fee.fee_cents


def net_profit(contracts: int, bid: int, ask: int, as_maker: bool = True) -> float:
    """Net profit after fees for a round trip."""
    gross = (ask - bid) * contracts
    fees = round_trip_fee(contracts, bid, ask, as_maker)
    return gross - fees
