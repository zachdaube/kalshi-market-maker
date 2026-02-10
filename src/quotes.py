"""
Avellaneda-Stoikov Market Making Model for Kalshi

Implements the optimal quoting strategy from:
"High-frequency trading in a limit order book" (Avellaneda & Stoikov, 2006)

Key equations:
- Reservation price: r = s - q * gamma * sigma^2
- Optimal spread: delta = (2/gamma) * ln(1 + gamma/k)

Where:
  s = mid price
  q = inventory (positive = long)
  gamma = risk aversion (higher = more conservative)
  sigma = volatility (price uncertainty)
  k = order arrival intensity parameter
"""

from typing import Optional, Dict, Tuple
from dataclasses import dataclass
import math

# Kalshi maker fee rate
MAKER_FEE_RATE = 0.0175


@dataclass
class Position:
    """Current position in a market."""
    ticker: str
    quantity: int  # Positive = long, negative = short
    avg_entry_price: Optional[float] = None


@dataclass
class ASParams:
    """Avellaneda-Stoikov model parameters."""
    gamma: float = 0.1      # Risk aversion (higher = wider spreads, tighter inventory)
    sigma: float = 2.0      # Volatility estimate (cents per time unit)
    k: float = 1.5          # Order arrival intensity decay parameter
    max_position: int = 100 # Maximum inventory limit
    base_size: int = 10     # Default order size


@dataclass
class Quote:
    """A single quote."""
    price_cents: int
    quantity: int
    side: str  # "bid" or "ask"


@dataclass
class TwoSidedQuote:
    """Two-sided market quote."""
    ticker: str
    bid: Quote
    ask: Quote
    reservation_price: float  # Inventory-adjusted fair value
    mid_price: float         # Market mid price
    spread_cents: int        # Total spread

    def to_kalshi_orders(self) -> Tuple[Dict, Dict]:
        """Convert to Kalshi order format."""
        yes_bid = {
            'side': 'yes',
            'action': 'buy',
            'price': self.bid.price_cents,
            'quantity': self.bid.quantity
        }
        # YES ask via NO bid at (100 - ask_price)
        no_bid = {
            'side': 'no',
            'action': 'buy',
            'price': 100 - self.ask.price_cents,
            'quantity': self.ask.quantity
        }
        return yes_bid, no_bid


def calculate_reservation_price(mid: float, q: int, gamma: float, sigma: float) -> float:
    """
    Calculate reservation/indifference price.

    From eq 3.17: r(s,q,t) = s - q * gamma * sigma^2 * (T-t)

    For continuous operation, we use stationary version:
    r = s - q * gamma * sigma^2

    The reservation price shifts based on inventory:
    - Long (q > 0): reservation price BELOW mid (want to sell)
    - Short (q < 0): reservation price ABOVE mid (want to buy)
    """
    return mid - q * gamma * (sigma ** 2)


def calculate_optimal_spread(gamma: float, k: float) -> float:
    """
    Calculate optimal bid-ask spread.

    From eq 3.18 (stationary part):
    spread = (2/gamma) * ln(1 + gamma/k)

    This is the inventory-independent component.
    Higher gamma (risk aversion) -> wider spread
    Higher k (faster order decay) -> narrower spread
    """
    return (2.0 / gamma) * math.log(1 + gamma / k)


def generate_quote(
    ticker: str,
    mid_price: float,
    position: Position,
    params: ASParams
) -> Optional[TwoSidedQuote]:
    """
    Generate optimal two-sided quote using Avellaneda-Stoikov model.

    Args:
        ticker: Market ticker
        mid_price: Current orderbook mid price (cents)
        position: Current inventory
        params: Model parameters

    Returns:
        TwoSidedQuote or None if invalid
    """
    if mid_price is None or mid_price <= 0 or mid_price >= 100:
        return None

    q = position.quantity
    gamma = params.gamma
    sigma = params.sigma
    k = params.k

    # Step 1: Calculate reservation price (inventory-adjusted fair value)
    reservation = calculate_reservation_price(mid_price, q, gamma, sigma)

    # Step 2: Calculate optimal spread
    spread = calculate_optimal_spread(gamma, k)

    # Step 3: Set bid/ask around reservation price
    half_spread = spread / 2
    bid_price = reservation - half_spread
    ask_price = reservation + half_spread

    # Round to integers (Kalshi uses whole cents)
    bid_cents = int(round(bid_price))
    ask_cents = int(round(ask_price))

    # Fee-aware minimum spread: ensure spread covers round-trip maker fees
    # Fee per side = MAKER_FEE_RATE * P * (1-P), where P = price/100
    # Round-trip fee ~= 2 * MAKER_FEE_RATE * mid/100 * (1 - mid/100) * 100 (in cents)
    mid_decimal = mid_price / 100.0
    min_spread_cents = math.ceil(2 * MAKER_FEE_RATE * mid_decimal * (1 - mid_decimal) * 100) + 1

    # Ensure minimum spread (at least 1 cent, fee-aware floor)
    min_spread = max(1, min_spread_cents)
    if ask_cents - bid_cents < min_spread:
        half = min_spread / 2.0
        bid_cents = int(math.floor(reservation - half))
        ask_cents = int(math.ceil(reservation + half))

    # Clamp to valid Kalshi range [1, 99]
    bid_cents = max(1, min(98, bid_cents))
    ask_cents = max(2, min(99, ask_cents))

    # Final validation
    if bid_cents >= ask_cents:
        return None

    # Determine size (reduce if near position limit)
    position_ratio = abs(q) / params.max_position if params.max_position > 0 else 0

    if position_ratio > 0.8:
        # Near limit: reduce size on side that would increase position
        if q > 0:  # Long, reduce bid size
            bid_size = max(1, params.base_size // 2)
            ask_size = params.base_size
        else:  # Short, reduce ask size
            bid_size = params.base_size
            ask_size = max(1, params.base_size // 2)
    else:
        bid_size = params.base_size
        ask_size = params.base_size

    return TwoSidedQuote(
        ticker=ticker,
        bid=Quote(bid_cents, bid_size, "bid"),
        ask=Quote(ask_cents, ask_size, "ask"),
        reservation_price=reservation,
        mid_price=mid_price,
        spread_cents=ask_cents - bid_cents
    )


class PositionTracker:
    """Track positions across markets."""

    def __init__(self):
        self.positions: Dict[str, Position] = {}

    def get_position(self, ticker: str) -> Position:
        """Get position for ticker (flat if not tracked)."""
        return self.positions.get(ticker, Position(ticker=ticker, quantity=0))

    def update_position(self, ticker: str, delta: int, price: Optional[float] = None):
        """Update position after fill."""
        if ticker not in self.positions:
            self.positions[ticker] = Position(ticker=ticker, quantity=0)

        pos = self.positions[ticker]
        old_qty = pos.quantity
        new_qty = old_qty + delta

        # Update average entry
        if price and new_qty != 0:
            if old_qty == 0:
                pos.avg_entry_price = price
            elif (old_qty > 0 and delta > 0) or (old_qty < 0 and delta < 0):
                total = (old_qty * (pos.avg_entry_price or 0)) + (delta * price)
                pos.avg_entry_price = total / new_qty

        pos.quantity = new_qty
        if new_qty == 0:
            pos.avg_entry_price = None

    def get_total_exposure(self) -> int:
        """Total absolute position across all markets."""
        return sum(abs(p.quantity) for p in self.positions.values())

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all non-flat positions."""
        return {t: p for t, p in self.positions.items() if p.quantity != 0}
