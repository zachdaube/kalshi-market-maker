"""
Tests for Avellaneda-Stoikov Quote Generation
"""

import pytest
import math
from src.quotes import (
    ASParams,
    Position,
    Quote,
    TwoSidedQuote,
    calculate_reservation_price,
    calculate_optimal_spread,
    generate_quote,
    PositionTracker
)


class TestReservationPrice:
    """Test reservation price calculation."""

    def test_flat_position(self):
        """Flat position: reservation = mid."""
        result = calculate_reservation_price(mid=50, q=0, gamma=0.1, sigma=2.0)
        assert result == 50.0

    def test_long_position_shifts_down(self):
        """Long position shifts reservation below mid."""
        mid = 50
        result = calculate_reservation_price(mid=mid, q=10, gamma=0.1, sigma=2.0)
        # r = 50 - 10 * 0.1 * 4 = 50 - 4 = 46
        assert result < mid
        assert result == 46.0

    def test_short_position_shifts_up(self):
        """Short position shifts reservation above mid."""
        mid = 50
        result = calculate_reservation_price(mid=mid, q=-10, gamma=0.1, sigma=2.0)
        # r = 50 - (-10) * 0.1 * 4 = 50 + 4 = 54
        assert result > mid
        assert result == 54.0

    def test_higher_gamma_larger_shift(self):
        """Higher gamma = larger inventory adjustment."""
        r1 = calculate_reservation_price(mid=50, q=10, gamma=0.1, sigma=2.0)
        r2 = calculate_reservation_price(mid=50, q=10, gamma=0.2, sigma=2.0)
        assert r2 < r1  # More aggressive skew

    def test_higher_sigma_larger_shift(self):
        """Higher volatility = larger inventory adjustment."""
        r1 = calculate_reservation_price(mid=50, q=10, gamma=0.1, sigma=2.0)
        r2 = calculate_reservation_price(mid=50, q=10, gamma=0.1, sigma=3.0)
        assert r2 < r1


class TestOptimalSpread:
    """Test optimal spread calculation."""

    def test_spread_formula(self):
        """Test AS spread formula."""
        gamma = 0.1
        k = 1.5
        expected = (2.0 / gamma) * math.log(1 + gamma / k)
        result = calculate_optimal_spread(gamma, k)
        assert abs(result - expected) < 0.001

    def test_spread_decreases_with_gamma(self):
        """Spread formula: (2/gamma)*ln(1+gamma/k) decreases with gamma."""
        # This is counterintuitive but correct per the AS formula
        # The spread component here is inventory-independent
        # Higher gamma means more aggressive inventory reversion
        s1 = calculate_optimal_spread(gamma=0.1, k=1.5)
        s2 = calculate_optimal_spread(gamma=0.5, k=1.5)
        assert s2 < s1  # Spread actually decreases with gamma in this formula

    def test_higher_k_narrower_spread(self):
        """Higher order arrival decay = narrower spread."""
        s1 = calculate_optimal_spread(gamma=0.1, k=1.0)
        s2 = calculate_optimal_spread(gamma=0.1, k=2.0)
        assert s2 < s1


class TestGenerateQuote:
    """Test quote generation."""

    def test_basic_quote_generation(self):
        """Generate a basic quote."""
        pos = Position(ticker="TEST", quantity=0)
        params = ASParams(gamma=0.1, sigma=2.0, k=1.5)
        quote = generate_quote("TEST", mid_price=50.0, position=pos, params=params)

        assert quote is not None
        assert quote.ticker == "TEST"
        assert quote.bid.price_cents < quote.ask.price_cents
        assert 1 <= quote.bid.price_cents <= 98
        assert 2 <= quote.ask.price_cents <= 99

    def test_quote_with_long_position(self):
        """Long position skews quotes down."""
        flat_pos = Position(ticker="TEST", quantity=0)
        long_pos = Position(ticker="TEST", quantity=50)
        params = ASParams(gamma=0.1, sigma=2.0, k=1.5, max_position=100)

        flat_quote = generate_quote("TEST", 50.0, flat_pos, params)
        long_quote = generate_quote("TEST", 50.0, long_pos, params)

        # Long position should have lower bid/ask
        assert long_quote.bid.price_cents <= flat_quote.bid.price_cents
        assert long_quote.reservation_price < flat_quote.reservation_price

    def test_quote_with_short_position(self):
        """Short position skews quotes up."""
        flat_pos = Position(ticker="TEST", quantity=0)
        short_pos = Position(ticker="TEST", quantity=-50)
        params = ASParams(gamma=0.1, sigma=2.0, k=1.5, max_position=100)

        flat_quote = generate_quote("TEST", 50.0, flat_pos, params)
        short_quote = generate_quote("TEST", 50.0, short_pos, params)

        # Short position should have higher bid/ask
        assert short_quote.ask.price_cents >= flat_quote.ask.price_cents
        assert short_quote.reservation_price > flat_quote.reservation_price

    def test_invalid_mid_price(self):
        """Invalid mid prices return None."""
        pos = Position(ticker="TEST", quantity=0)
        params = ASParams()

        assert generate_quote("TEST", None, pos, params) is None
        assert generate_quote("TEST", 0, pos, params) is None
        assert generate_quote("TEST", 100, pos, params) is None
        assert generate_quote("TEST", -5, pos, params) is None

    def test_size_reduction_near_limit(self):
        """Size reduced when near position limit."""
        pos = Position(ticker="TEST", quantity=85)  # 85% of max
        params = ASParams(max_position=100, base_size=10)
        quote = generate_quote("TEST", 50.0, pos, params)

        # Bid size should be reduced (long, reduce buying)
        assert quote.bid.quantity < params.base_size

    def test_kalshi_order_conversion(self):
        """Test conversion to Kalshi order format."""
        pos = Position(ticker="TEST", quantity=0)
        params = ASParams()
        quote = generate_quote("TEST", 50.0, pos, params)

        yes_bid, no_bid = quote.to_kalshi_orders()

        assert yes_bid['side'] == 'yes'
        assert yes_bid['action'] == 'buy'
        assert yes_bid['price'] == quote.bid.price_cents

        assert no_bid['side'] == 'no'
        assert no_bid['action'] == 'buy'
        assert no_bid['price'] == 100 - quote.ask.price_cents


class TestPositionTracker:
    """Test position tracking."""

    def test_get_flat_position(self):
        """Get position for unknown ticker returns flat."""
        tracker = PositionTracker()
        pos = tracker.get_position("UNKNOWN")
        assert pos.quantity == 0
        assert pos.ticker == "UNKNOWN"

    def test_update_position(self):
        """Update position after fill."""
        tracker = PositionTracker()
        tracker.update_position("TEST", delta=10, price=50.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 10
        assert pos.avg_entry_price == 50.0

    def test_multiple_updates(self):
        """Multiple position updates."""
        tracker = PositionTracker()
        tracker.update_position("TEST", delta=10, price=50.0)
        tracker.update_position("TEST", delta=10, price=60.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 20
        # Avg = (10*50 + 10*60) / 20 = 55
        assert pos.avg_entry_price == 55.0

    def test_close_position(self):
        """Closing position resets avg entry."""
        tracker = PositionTracker()
        tracker.update_position("TEST", delta=10, price=50.0)
        tracker.update_position("TEST", delta=-10, price=55.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 0
        assert pos.avg_entry_price is None

    def test_total_exposure(self):
        """Total exposure across markets."""
        tracker = PositionTracker()
        tracker.update_position("A", delta=10)
        tracker.update_position("B", delta=-20)
        tracker.update_position("C", delta=30)

        assert tracker.get_total_exposure() == 60  # |10| + |-20| + |30|

    def test_get_all_positions(self):
        """Get all non-flat positions."""
        tracker = PositionTracker()
        tracker.update_position("A", delta=10)
        tracker.update_position("B", delta=0)
        tracker.update_position("C", delta=-5)

        positions = tracker.get_all_positions()
        assert "A" in positions
        assert "B" not in positions  # flat
        assert "C" in positions
