"""
Quote Generation for Kalshi Market Making

Generates optimal bid/ask quotes with inventory management and risk controls.

Key concepts:
- Fair value: Mid price from orderbook
- Spread: How wide to quote (based on profitability requirements)
- Skew: Adjust quotes based on inventory position
- Size: How many contracts to quote (based on liquidity and limits)
"""

from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from src.orderbook import OrderBook
from src.fees import should_quote_market, analyze_profitability


@dataclass
class Position:
    """Current position in a market."""
    ticker: str
    quantity: int  # Positive = long, negative = short, 0 = flat
    avg_entry_price: Optional[float] = None  # Average price paid
    unrealized_pnl: Optional[float] = None  # Mark-to-market P&L


@dataclass
class QuoteParams:
    """Parameters for quote generation."""
    # Spread configuration
    min_spread_cents: int  # Minimum profitable spread
    target_spread_cents: int  # Desired spread (wider = more profit, less fills)

    # Size configuration
    base_size: int  # Base quote size in contracts
    max_position: int  # Maximum position size (long or short)

    # Inventory skewing
    skew_enabled: bool = True  # Whether to skew quotes based on position
    skew_factor: float = 0.5  # How aggressively to skew (0-1)

    # Profitability
    min_profit_cents: float = 10.0  # Minimum profit per round trip


@dataclass
class Quote:
    """A single quote (bid or ask)."""
    price_cents: int  # Price in cents
    quantity: int  # Number of contracts
    side: str  # "bid" or "ask"


@dataclass
class TwoSidedQuote:
    """Two-sided market quote (bid and ask)."""
    ticker: str
    bid: Quote
    ask: Quote

    # Metadata
    fair_value_cents: float  # Mid price
    spread_cents: int  # ask - bid
    position: Position  # Current position
    skew_cents: int = 0  # How much we skewed (+ = skewed up, - = skewed down)

    # Profitability
    expected_profit_cents: float = 0.0  # Expected profit if both sides fill

    def to_kalshi_orders(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Convert to Kalshi order format.

        Returns:
            (yes_bid_order, no_bid_order) where no_bid implements the YES ask
        """
        # YES bid: Buy YES at bid price
        yes_bid = {
            'side': 'yes',
            'action': 'buy',
            'price': self.bid.price_cents,
            'quantity': self.bid.quantity
        }

        # YES ask: Sell YES at ask price
        # Implemented as: Buy NO at (100 - ask_price)
        no_bid = {
            'side': 'no',
            'action': 'buy',
            'price': 100 - self.ask.price_cents,
            'quantity': self.ask.quantity
        }

        return yes_bid, no_bid


class QuoteGenerator:
    """
    Generates optimal quotes for market making.

    Features:
    - Calculate fair value from orderbook
    - Determine optimal spread based on fees
    - Skew quotes based on inventory position
    - Size quotes based on risk limits
    """

    def __init__(self, params: QuoteParams):
        """
        Initialize quote generator.

        Args:
            params: Quote generation parameters
        """
        self.params = params

    def generate_quote(
        self,
        orderbook: OrderBook,
        position: Optional[Position] = None
    ) -> Optional[TwoSidedQuote]:
        """
        Generate two-sided quote for a market.

        Args:
            orderbook: Current orderbook
            position: Current position (None = flat)

        Returns:
            TwoSidedQuote or None if market shouldn't be quoted
        """
        # Default to flat position
        if position is None:
            position = Position(ticker=orderbook.ticker, quantity=0)

        # 1. Calculate fair value
        fair_value = self._calculate_fair_value(orderbook)
        if fair_value is None:
            return None

        # 2. Determine spread
        spread = self._determine_spread(orderbook, fair_value)
        if spread is None:
            return None

        # 3. Calculate base quotes (before skewing)
        base_bid = fair_value - spread / 2
        base_ask = fair_value + spread / 2

        # 4. Apply inventory skew
        bid_cents, ask_cents, skew = self._apply_inventory_skew(
            base_bid, base_ask, position
        )

        # 5. Determine quote size
        bid_size, ask_size = self._determine_quote_size(position)

        # 6. Validate quotes
        if not self._validate_quotes(bid_cents, ask_cents):
            return None

        # 7. Calculate expected profitability
        expected_profit = self._calculate_expected_profit(
            bid_cents, ask_cents, bid_size, ask_size
        )

        # Create quote objects
        bid = Quote(price_cents=bid_cents, quantity=bid_size, side="bid")
        ask = Quote(price_cents=ask_cents, quantity=ask_size, side="ask")

        return TwoSidedQuote(
            ticker=orderbook.ticker,
            bid=bid,
            ask=ask,
            fair_value_cents=fair_value,
            spread_cents=ask_cents - bid_cents,
            position=position,
            skew_cents=skew,
            expected_profit_cents=expected_profit
        )

    def _calculate_fair_value(self, orderbook: OrderBook) -> Optional[float]:
        """
        Calculate fair value from orderbook.

        Uses mid price if available, otherwise returns None.
        """
        if orderbook.mid_price is None:
            return None

        return orderbook.mid_price

    def _determine_spread(
        self,
        orderbook: OrderBook,
        fair_value: float
    ) -> Optional[int]:
        """
        Determine optimal spread.

        Uses target spread, but checks if it's profitable.
        Falls back to minimum profitable spread if needed.
        """
        # Start with target spread
        spread = self.params.target_spread_cents

        # Check if profitable
        result = should_quote_market(
            spread_cents=spread,
            contracts=self.params.base_size,
            mid_price_cents=int(fair_value),
            min_profit_cents=self.params.min_profit_cents,
            as_maker=True
        )

        if result['should_quote']:
            return spread

        # Try minimum spread
        min_spread = self.params.min_spread_cents
        result = should_quote_market(
            spread_cents=min_spread,
            contracts=self.params.base_size,
            mid_price_cents=int(fair_value),
            min_profit_cents=self.params.min_profit_cents,
            as_maker=True
        )

        if result['should_quote']:
            return min_spread

        # Not profitable at any spread
        return None

    def _apply_inventory_skew(
        self,
        base_bid: float,
        base_ask: float,
        position: Position
    ) -> Tuple[int, int, int]:
        """
        Apply inventory skew to quotes.

        Skewing logic:
        - If long (positive position): Skew quotes DOWN to encourage selling
        - If short (negative position): Skew quotes UP to encourage buying
        - If flat: No skew

        Args:
            base_bid: Base bid price
            base_ask: Base ask price
            position: Current position

        Returns:
            (bid_cents, ask_cents, skew_cents)
                skew_cents: Negative if skewed down, positive if skewed up
        """
        if not self.params.skew_enabled or position.quantity == 0:
            return int(base_bid), int(base_ask), 0

        # Calculate skew amount
        # Skew proportional to position as % of max position
        position_pct = position.quantity / self.params.max_position

        # Skew in cents (capped)
        max_skew = 5  # Maximum 5 cent skew
        raw_skew = position_pct * max_skew * self.params.skew_factor

        # Apply skew (shift both quotes in opposite direction of position)
        # Long position → negative skew (down)
        # Short position → positive skew (up)
        skew_cents = int(-raw_skew)  # Negate to get correct sign

        bid_cents = int(base_bid + skew_cents)
        ask_cents = int(base_ask + skew_cents)

        return bid_cents, ask_cents, skew_cents

    def _determine_quote_size(
        self,
        position: Position
    ) -> Tuple[int, int]:
        """
        Determine quote size based on position.

        Logic:
        - If near max position: Reduce size on same side, increase on opposite
        - If flat: Equal size both sides

        Returns:
            (bid_size, ask_size)
        """
        base_size = self.params.base_size

        # Check position limits
        position_pct = abs(position.quantity) / self.params.max_position

        if position_pct >= 0.8:  # Near limit
            if position.quantity > 0:  # Long, reduce bid size
                bid_size = max(1, int(base_size * 0.5))
                ask_size = int(base_size * 1.5)
            else:  # Short, reduce ask size
                bid_size = int(base_size * 1.5)
                ask_size = max(1, int(base_size * 0.5))
        else:
            bid_size = base_size
            ask_size = base_size

        return bid_size, ask_size

    def _validate_quotes(self, bid_cents: int, ask_cents: int) -> bool:
        """
        Validate that quotes are reasonable.

        Checks:
        - Prices in valid range (1-99)
        - Bid < ask (not crossed)
        - Spread > 0
        """
        if bid_cents < 1 or bid_cents > 99:
            return False

        if ask_cents < 1 or ask_cents > 99:
            return False

        if bid_cents >= ask_cents:
            return False

        return True

    def _calculate_expected_profit(
        self,
        bid_cents: int,
        ask_cents: int,
        bid_size: int,
        ask_size: int
    ) -> float:
        """
        Calculate expected profit if both sides fill.

        Simplified: Uses smaller of the two sizes.
        """
        size = min(bid_size, ask_size)

        analysis = analyze_profitability(
            contracts=size,
            entry_price_cents=bid_cents,
            exit_price_cents=ask_cents,
            as_maker=True
        )

        return analysis.net_profit_cents


class PositionTracker:
    """
    Track positions across multiple markets.

    In a real implementation, this would sync with Kalshi API.
    For now, it's a simple in-memory tracker.
    """

    def __init__(self):
        """Initialize position tracker."""
        self.positions: Dict[str, Position] = {}

    def get_position(self, ticker: str) -> Position:
        """
        Get current position for a ticker.

        Returns flat position if not tracked.
        """
        if ticker not in self.positions:
            return Position(ticker=ticker, quantity=0)

        return self.positions[ticker]

    def update_position(
        self,
        ticker: str,
        quantity_delta: int,
        price: Optional[float] = None
    ):
        """
        Update position after a fill.

        Args:
            ticker: Market ticker
            quantity_delta: Change in quantity (+ = bought, - = sold)
            price: Execution price (for avg entry calculation)
        """
        if ticker not in self.positions:
            self.positions[ticker] = Position(ticker=ticker, quantity=0)

        pos = self.positions[ticker]

        # Update quantity
        old_qty = pos.quantity
        new_qty = old_qty + quantity_delta

        # Update average entry price
        if price is not None and new_qty != 0:
            if old_qty == 0:
                # Opening position
                pos.avg_entry_price = price
            elif (old_qty > 0 and quantity_delta > 0) or (old_qty < 0 and quantity_delta < 0):
                # Adding to position
                total_cost = (old_qty * pos.avg_entry_price) + (quantity_delta * price)
                pos.avg_entry_price = total_cost / new_qty
            # If reducing/closing, keep same avg entry

        pos.quantity = new_qty

        # If flat, reset avg entry price
        if new_qty == 0:
            pos.avg_entry_price = None

    def calculate_unrealized_pnl(
        self,
        ticker: str,
        current_mid: float
    ) -> Optional[float]:
        """
        Calculate unrealized P&L for a position.

        Args:
            ticker: Market ticker
            current_mid: Current mid price

        Returns:
            Unrealized P&L in cents, or None if flat
        """
        pos = self.get_position(ticker)

        if pos.quantity == 0 or pos.avg_entry_price is None:
            return None

        # P&L = (current_price - entry_price) * quantity
        pnl_per_contract = current_mid - pos.avg_entry_price
        total_pnl = pnl_per_contract * pos.quantity

        return total_pnl

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all non-flat positions."""
        return {
            ticker: pos
            for ticker, pos in self.positions.items()
            if pos.quantity != 0
        }

    def get_total_exposure(self) -> int:
        """Get total absolute position across all markets."""
        return sum(abs(pos.quantity) for pos in self.positions.values())


def format_quote(quote: TwoSidedQuote) -> str:
    """Pretty-print a two-sided quote."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"Quote for {quote.ticker}")
    lines.append(f"{'='*60}")

    lines.append(f"\nFair Value: {quote.fair_value_cents:.2f}¢")
    lines.append(f"Spread:     {quote.spread_cents}¢")

    if quote.skew_cents != 0:
        direction = "DOWN" if quote.skew_cents < 0 else "UP"
        lines.append(f"Skew:       {abs(quote.skew_cents)}¢ {direction}")

    lines.append(f"\nPosition:   {quote.position.quantity:+d} contracts")
    if quote.position.avg_entry_price:
        lines.append(f"Avg Entry:  {quote.position.avg_entry_price:.2f}¢")

    lines.append(f"\nQuotes:")
    lines.append(f"  BID: {quote.bid.price_cents:2d}¢ × {quote.bid.quantity:3d} contracts")
    lines.append(f"  ASK: {quote.ask.price_cents:2d}¢ × {quote.ask.quantity:3d} contracts")

    lines.append(f"\nExpected Profit: {quote.expected_profit_cents:.2f}¢")

    lines.append(f"\nKalshi Orders:")
    yes_bid, no_bid = quote.to_kalshi_orders()
    lines.append(f"  1. Buy YES at {yes_bid['price']}¢ × {yes_bid['quantity']}")
    lines.append(f"  2. Buy NO at {no_bid['price']}¢ × {no_bid['quantity']}")
    lines.append(f"     (implements YES ask at {quote.ask.price_cents}¢)")

    lines.append(f"{'='*60}")

    return "\n".join(lines)
