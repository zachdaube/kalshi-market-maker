"""
Unit tests for quote generation.
"""

import pytest
from src.quotes import (
    QuoteGenerator,
    QuoteParams,
    Position,
    PositionTracker,
    TwoSidedQuote,
    Quote
)
from src.orderbook import OrderBook


class TestQuoteGeneration:
    """Test basic quote generation."""

    def test_generate_quote_flat_position(self):
        """Test generating quote with flat position."""
        # Create orderbook
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        # Create quote generator
        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,  # Disable skew for this test
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # Generate quote
        quote = generator.generate_quote(ob, position=None)

        assert quote is not None
        assert quote.ticker == "TEST"
        assert quote.bid.side == "bid"
        assert quote.ask.side == "ask"
        assert quote.bid.price_cents < quote.ask.price_cents
        assert quote.spread_cents == quote.ask.price_cents - quote.bid.price_cents

    def test_quote_centered_on_mid(self):
        """Test that quotes are centered on mid price."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        quote = generator.generate_quote(ob)

        # Mid is 48.5, spread is 4, so bid=46.5→46, ask=50.5→50
        assert abs((quote.bid.price_cents + quote.ask.price_cents) / 2 - ob.mid_price) <= 1

    def test_quote_size_matches_params(self):
        """Test that quote size matches parameters."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=50,
            max_position=1000,
            skew_enabled=False,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        quote = generator.generate_quote(ob)

        assert quote.bid.quantity == 50
        assert quote.ask.quantity == 50

    def test_no_quote_for_empty_orderbook(self):
        """Don't quote if orderbook is empty."""
        raw = {"yes": [], "no": []}
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        quote = generator.generate_quote(ob)

        assert quote is None


class TestInventorySkewing:
    """Test inventory skewing functionality."""

    def test_skew_down_when_long(self):
        """Skew quotes down when long to encourage selling."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=True,
            skew_factor=0.5,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # Long 500 contracts (50% of max)
        position = Position(ticker="TEST", quantity=500, avg_entry_price=48.0)

        quote = generator.generate_quote(ob, position)

        # Should skew down (negative skew)
        assert quote.skew_cents < 0

    def test_skew_up_when_short(self):
        """Skew quotes up when short to encourage buying."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=True,
            skew_factor=0.5,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # Short 500 contracts
        position = Position(ticker="TEST", quantity=-500, avg_entry_price=48.0)

        quote = generator.generate_quote(ob, position)

        # Should skew up (positive skew)
        assert quote.skew_cents > 0

    def test_no_skew_when_flat(self):
        """No skew when position is flat."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=True,
            skew_factor=0.5,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        position = Position(ticker="TEST", quantity=0)

        quote = generator.generate_quote(ob, position)

        assert quote.skew_cents == 0

    def test_skew_disabled(self):
        """Skewing can be disabled."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,  # Disabled
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        position = Position(ticker="TEST", quantity=500, avg_entry_price=48.0)

        quote = generator.generate_quote(ob, position)

        # No skew even with position
        assert quote.skew_cents == 0


class TestQuoteSizing:
    """Test quote sizing logic."""

    def test_reduce_bid_size_when_long(self):
        """Reduce bid size when near max long position."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # Long 850 contracts (85% of max)
        position = Position(ticker="TEST", quantity=850, avg_entry_price=48.0)

        quote = generator.generate_quote(ob, position)

        # Bid size should be reduced, ask size increased
        assert quote.bid.quantity < 100
        assert quote.ask.quantity > 100

    def test_reduce_ask_size_when_short(self):
        """Reduce ask size when near max short position."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # Short 850 contracts
        position = Position(ticker="TEST", quantity=-850, avg_entry_price=48.0)

        quote = generator.generate_quote(ob, position)

        # Ask size should be reduced, bid size increased
        assert quote.bid.quantity > 100
        assert quote.ask.quantity < 100

    def test_equal_size_when_flat(self):
        """Equal size on both sides when flat."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            skew_enabled=False,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        position = Position(ticker="TEST", quantity=0)

        quote = generator.generate_quote(ob, position)

        assert quote.bid.quantity == 100
        assert quote.ask.quantity == 100


class TestPositionTracker:
    """Test position tracking."""

    def test_initial_position_is_flat(self):
        """Initial position should be flat."""
        tracker = PositionTracker()
        pos = tracker.get_position("TEST")

        assert pos.quantity == 0
        assert pos.avg_entry_price is None

    def test_update_position_buy(self):
        """Test updating position after buy."""
        tracker = PositionTracker()

        tracker.update_position("TEST", quantity_delta=100, price=48.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 100
        assert pos.avg_entry_price == 48.0

    def test_update_position_sell(self):
        """Test updating position after sell."""
        tracker = PositionTracker()

        tracker.update_position("TEST", quantity_delta=100, price=48.0)
        tracker.update_position("TEST", quantity_delta=-50, price=49.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 50
        # Avg entry should remain 48.0 (not affected by reduce)
        assert pos.avg_entry_price == 48.0

    def test_average_entry_price(self):
        """Test average entry price calculation."""
        tracker = PositionTracker()

        # Buy 100 at 48
        tracker.update_position("TEST", quantity_delta=100, price=48.0)

        # Buy 100 more at 50
        tracker.update_position("TEST", quantity_delta=100, price=50.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 200
        # Avg = (100*48 + 100*50) / 200 = 49
        assert pos.avg_entry_price == 49.0

    def test_position_goes_flat(self):
        """Test position going back to flat."""
        tracker = PositionTracker()

        tracker.update_position("TEST", quantity_delta=100, price=48.0)
        tracker.update_position("TEST", quantity_delta=-100, price=49.0)

        pos = tracker.get_position("TEST")
        assert pos.quantity == 0
        assert pos.avg_entry_price is None

    def test_unrealized_pnl(self):
        """Test unrealized P&L calculation."""
        tracker = PositionTracker()

        # Buy 100 at 48
        tracker.update_position("TEST", quantity_delta=100, price=48.0)

        # Current mid is 50
        pnl = tracker.calculate_unrealized_pnl("TEST", current_mid=50.0)

        # P&L = (50 - 48) * 100 = 200 cents
        assert pnl == 200.0

    def test_unrealized_pnl_short(self):
        """Test unrealized P&L for short position."""
        tracker = PositionTracker()

        # Sell 100 at 50
        tracker.update_position("TEST", quantity_delta=-100, price=50.0)

        # Current mid is 48 (favorable)
        pnl = tracker.calculate_unrealized_pnl("TEST", current_mid=48.0)

        # P&L = (48 - 50) * -100 = 200 cents (profit)
        assert pnl == 200.0

    def test_get_all_positions(self):
        """Test getting all non-flat positions."""
        tracker = PositionTracker()

        tracker.update_position("MARKET1", quantity_delta=100, price=48.0)
        tracker.update_position("MARKET2", quantity_delta=-50, price=52.0)
        tracker.update_position("MARKET3", quantity_delta=0, price=None)

        positions = tracker.get_all_positions()

        assert len(positions) == 2
        assert "MARKET1" in positions
        assert "MARKET2" in positions
        assert "MARKET3" not in positions

    def test_total_exposure(self):
        """Test total exposure calculation."""
        tracker = PositionTracker()

        tracker.update_position("MARKET1", quantity_delta=100, price=48.0)
        tracker.update_position("MARKET2", quantity_delta=-150, price=52.0)

        exposure = tracker.get_total_exposure()

        # |100| + |-150| = 250
        assert exposure == 250


class TestKalshiOrderConversion:
    """Test conversion to Kalshi order format."""

    def test_to_kalshi_orders(self):
        """Test converting quote to Kalshi orders."""
        bid = Quote(price_cents=47, quantity=100, side="bid")
        ask = Quote(price_cents=51, quantity=100, side="ask")

        position = Position(ticker="TEST", quantity=0)

        quote = TwoSidedQuote(
            ticker="TEST",
            bid=bid,
            ask=ask,
            fair_value_cents=49.0,
            spread_cents=4,
            position=position
        )

        yes_bid, no_bid = quote.to_kalshi_orders()

        # YES bid: Buy YES at 47
        assert yes_bid['side'] == 'yes'
        assert yes_bid['action'] == 'buy'
        assert yes_bid['price'] == 47
        assert yes_bid['quantity'] == 100

        # NO bid: Buy NO at 49 (implements YES ask at 51)
        assert no_bid['side'] == 'no'
        assert no_bid['action'] == 'buy'
        assert no_bid['price'] == 49  # 100 - 51
        assert no_bid['quantity'] == 100

    def test_complementary_prices(self):
        """Test that NO bid price is complementary to YES ask."""
        bid = Quote(price_cents=45, quantity=100, side="bid")
        ask = Quote(price_cents=55, quantity=100, side="ask")

        position = Position(ticker="TEST", quantity=0)

        quote = TwoSidedQuote(
            ticker="TEST",
            bid=bid,
            ask=ask,
            fair_value_cents=50.0,
            spread_cents=10,
            position=position
        )

        yes_bid, no_bid = quote.to_kalshi_orders()

        # NO bid at (100 - 55) = 45
        assert no_bid['price'] == 45
        # NO bid + YES ask should equal 100
        assert no_bid['price'] + ask.price_cents == 100


class TestQuoteValidation:
    """Test quote validation."""

    def test_reject_crossed_quotes(self):
        """Reject quotes where bid >= ask."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        # This should produce valid quotes
        quote = generator.generate_quote(ob)
        assert quote is not None
        assert quote.bid.price_cents < quote.ask.price_cents

    def test_prices_in_valid_range(self):
        """Ensure prices are in valid range (1-99)."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            min_profit_cents=10
        )
        generator = QuoteGenerator(params)

        quote = generator.generate_quote(ob)

        assert 1 <= quote.bid.price_cents <= 99
        assert 1 <= quote.ask.price_cents <= 99


class TestProfitabilityCalculation:
    """Test expected profitability calculations."""

    def test_expected_profit_positive(self):
        """Expected profit should be positive for valid quote."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        params = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            min_profit_cents=10,
            skew_enabled=False
        )
        generator = QuoteGenerator(params)

        quote = generator.generate_quote(ob)

        # Should have positive expected profit
        assert quote.expected_profit_cents > 0

    def test_expected_profit_scales_with_size(self):
        """Expected profit should scale with quote size."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 100]]
        }
        ob = OrderBook("TEST", raw)

        # Small size
        params_small = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=50,
            max_position=1000,
            min_profit_cents=5,
            skew_enabled=False
        )
        gen_small = QuoteGenerator(params_small)
        quote_small = gen_small.generate_quote(ob)

        # Large size
        params_large = QuoteParams(
            min_spread_cents=2,
            target_spread_cents=4,
            base_size=100,
            max_position=1000,
            min_profit_cents=10,
            skew_enabled=False
        )
        gen_large = QuoteGenerator(params_large)
        quote_large = gen_large.generate_quote(ob)

        # Larger size should have larger expected profit (roughly 2x)
        assert quote_large.expected_profit_cents > quote_small.expected_profit_cents
