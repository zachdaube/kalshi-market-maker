"""
Order Book Processing for Kalshi Markets

Converts Kalshi's bid-only format to a traditional YES-centric view
and provides utilities for spread/depth analysis.
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Quote:
    """A single price level in the orderbook."""
    price: int  # Price in cents (0-100)
    quantity: int  # Number of contracts


@dataclass
class OrderBookSnapshot:
    """A processed orderbook snapshot with calculated metrics."""
    ticker: str
    yes_bids: List[Quote]  # Bids to buy YES
    yes_asks: List[Quote]  # Asks to sell YES (derived from NO bids)

    # Calculated metrics
    best_bid: Optional[int] = None
    best_ask: Optional[int] = None
    mid_price: Optional[float] = None
    spread: Optional[int] = None

    # Depth metrics
    bid_depth: int = 0  # Total contracts on bid side
    ask_depth: int = 0  # Total contracts on ask side


class OrderBook:
    """
    Processes Kalshi orderbook data.

    Kalshi returns only bids for YES and NO. This class:
    1. Converts NO bids to YES asks (NO bid at X = YES ask at 100-X)
    2. Calculates spread, mid, depth metrics
    3. Handles edge cases (empty book, crossed market, etc.)
    """

    def __init__(self, ticker: str, raw_orderbook: dict):
        """
        Initialize from raw Kalshi orderbook.

        Args:
            ticker: Market ticker
            raw_orderbook: Dict with format {"yes": [[price, qty], ...], "no": [[price, qty], ...]}
        """
        self.ticker = ticker
        self.raw = raw_orderbook

        # Parse raw data
        self.yes_bids = self._parse_bids(raw_orderbook.get('yes', []))
        self.no_bids = self._parse_bids(raw_orderbook.get('no', []))

        # Convert NO bids to YES asks
        self.yes_asks = self._convert_no_bids_to_yes_asks(self.no_bids)

        # Calculate metrics
        self._calculate_metrics()

    def _parse_bids(self, bid_list: List[List[int]]) -> List[Quote]:
        """Convert list of [price, quantity] to Quote objects."""
        return [Quote(price=b[0], quantity=b[1]) for b in bid_list if len(b) >= 2]

    def _convert_no_bids_to_yes_asks(self, no_bids: List[Quote]) -> List[Quote]:
        """
        Convert NO bids to YES asks.

        A NO bid at price X means someone will pay X¢ for NO.
        This is equivalent to someone selling YES at (100-X)¢.

        Example:
            NO bid at 40¢ → YES ask at 60¢
            NO bid at 60¢ → YES ask at 40¢

        Returns:
            List of YES asks sorted by price (ascending)
        """
        yes_asks = [Quote(price=100 - bid.price, quantity=bid.quantity)
                    for bid in no_bids]

        # Sort by price ascending (best ask first)
        return sorted(yes_asks, key=lambda q: q.price)

    def _calculate_metrics(self):
        """Calculate best bid/ask, mid, spread."""
        # Initialize all attributes first
        self.best_bid = None
        self.best_ask = None
        self.mid_price = None
        self.spread = None

        # Best bid = highest price someone will pay for YES
        if self.yes_bids:
            self.best_bid = max(bid.price for bid in self.yes_bids)

        # Best ask = lowest price someone will sell YES
        if self.yes_asks:
            self.best_ask = min(ask.price for ask in self.yes_asks)

        # Mid price (average of best bid and ask)
        if self.best_bid is not None and self.best_ask is not None:
            self.mid_price = (self.best_bid + self.best_ask) / 2
            self.spread = self.best_ask - self.best_bid

        # Total depth
        self.bid_depth = sum(bid.quantity for bid in self.yes_bids)
        self.ask_depth = sum(ask.quantity for ask in self.yes_asks)

    def get_snapshot(self) -> OrderBookSnapshot:
        """Get a snapshot of current orderbook state."""
        return OrderBookSnapshot(
            ticker=self.ticker,
            yes_bids=self.yes_bids.copy(),
            yes_asks=self.yes_asks.copy(),
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            mid_price=self.mid_price,
            spread=self.spread,
            bid_depth=self.bid_depth,
            ask_depth=self.ask_depth
        )

    def get_vwap(self, side: str, quantity: int) -> Optional[float]:
        """
        Calculate Volume-Weighted Average Price to fill a given quantity.

        Args:
            side: "bid" or "ask"
            quantity: Number of contracts to fill

        Returns:
            Average price in cents, or None if insufficient liquidity

        Example:
            Bids: [(48, 100), (47, 200), (46, 300)]
            VWAP for 250 contracts = (48*100 + 47*150) / 250 = 47.4¢
        """
        levels = self.yes_bids if side == "bid" else self.yes_asks

        if not levels:
            return None

        # Sort appropriately
        if side == "bid":
            # For bids, take highest prices first (best execution)
            sorted_levels = sorted(levels, key=lambda q: q.price, reverse=True)
        else:
            # For asks, take lowest prices first (best execution)
            sorted_levels = sorted(levels, key=lambda q: q.price)

        total_value = 0
        total_quantity = 0

        for level in sorted_levels:
            if total_quantity >= quantity:
                break

            # How much can we take from this level?
            qty_to_take = min(level.quantity, quantity - total_quantity)
            total_value += level.price * qty_to_take
            total_quantity += qty_to_take

        # Check if we got enough liquidity
        if total_quantity < quantity:
            return None  # Not enough liquidity

        return total_value / total_quantity

    def get_cumulative_depth(self, side: str, levels: int) -> int:
        """
        Get cumulative depth across N price levels.

        Args:
            side: "bid" or "ask"
            levels: Number of price levels to sum

        Returns:
            Total quantity across those levels
        """
        quotes = self.yes_bids if side == "bid" else self.yes_asks

        if not quotes:
            return 0

        # Sort to get best levels first
        if side == "bid":
            sorted_quotes = sorted(quotes, key=lambda q: q.price, reverse=True)
        else:
            sorted_quotes = sorted(quotes, key=lambda q: q.price)

        return sum(q.quantity for q in sorted_quotes[:levels])

    def is_crossed(self) -> bool:
        """
        Check if the market is crossed (bid > ask).

        This shouldn't happen in normal markets, indicates arbitrage or stale data.
        """
        if self.best_bid is None or self.best_ask is None:
            return False

        return self.best_bid >= self.best_ask

    def is_empty(self) -> bool:
        """Check if orderbook has no liquidity."""
        return len(self.yes_bids) == 0 and len(self.yes_asks) == 0

    def is_one_sided(self) -> bool:
        """Check if orderbook only has bids or only asks."""
        return (len(self.yes_bids) == 0 and len(self.yes_asks) > 0) or \
               (len(self.yes_bids) > 0 and len(self.yes_asks) == 0)

    def get_depth_at_price(self, price: int, side: str) -> int:
        """
        Get total quantity available at a specific price.

        Args:
            price: Price in cents
            side: "bid" or "ask"

        Returns:
            Total quantity at that price level, or 0 if none
        """
        levels = self.yes_bids if side == "bid" else self.yes_asks

        total = 0
        for level in levels:
            if level.price == price:
                total += level.quantity

        return total

    def __repr__(self) -> str:
        """String representation of orderbook."""
        return (f"OrderBook({self.ticker}, "
                f"bid={self.best_bid}¢, ask={self.best_ask}¢, "
                f"mid={self.mid_price:.1f}¢ if self.mid_price else 'N/A', "
                f"spread={self.spread}¢)")


def format_orderbook(ob: OrderBook, levels: int = 5) -> str:
    """
    Pretty-print an orderbook.

    Args:
        ob: OrderBook instance
        levels: Number of price levels to show

    Returns:
        Formatted string representation
    """
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"Order Book: {ob.ticker}")
    lines.append(f"{'='*60}")

    # Market state
    if ob.is_empty():
        lines.append("⚠ EMPTY ORDERBOOK")
        return "\n".join(lines)

    if ob.is_crossed():
        lines.append("⚠ CROSSED MARKET (bid >= ask)")

    if ob.is_one_sided():
        lines.append("⚠ ONE-SIDED MARKET")

    # Stats
    lines.append(f"\nBest Bid:  {ob.best_bid}¢ (depth: {ob.bid_depth} contracts)")
    lines.append(f"Best Ask:  {ob.best_ask}¢ (depth: {ob.ask_depth} contracts)")
    if ob.mid_price:
        lines.append(f"Mid Price: {ob.mid_price:.2f}¢")
        lines.append(f"Spread:    {ob.spread}¢")

    # Show orderbook levels
    lines.append(f"\n{'ASKS (Sell YES)':^30} | {'BIDS (Buy YES)':^30}")
    lines.append("-" * 60)

    # Get top N levels
    asks_to_show = sorted(ob.yes_asks, key=lambda q: q.price)[:levels]
    bids_to_show = sorted(ob.yes_bids, key=lambda q: q.price, reverse=True)[:levels]

    max_len = max(len(asks_to_show), len(bids_to_show))

    for i in range(max_len):
        ask_str = ""
        bid_str = ""

        if i < len(asks_to_show):
            ask = asks_to_show[i]
            ask_str = f"{ask.price:3d}¢ × {ask.quantity:4d}"

        if i < len(bids_to_show):
            bid = bids_to_show[i]
            bid_str = f"{bid.price:3d}¢ × {bid.quantity:4d}"

        lines.append(f"{ask_str:^30} | {bid_str:^30}")

    lines.append("=" * 60)

    return "\n".join(lines)
