"""
Unit tests for OrderBook class
"""

import pytest
from src.orderbook import OrderBook, Quote, format_orderbook


class TestOrderBookBasic:
    """Test basic orderbook parsing and conversion."""

    def test_empty_orderbook(self):
        """Test handling of empty orderbook."""
        ob = OrderBook("TEST", {"yes": [], "no": []})

        assert ob.is_empty()
        assert ob.best_bid is None
        assert ob.best_ask is None
        assert ob.mid_price is None
        assert ob.spread is None
        assert ob.bid_depth == 0
        assert ob.ask_depth == 0

    def test_simple_orderbook(self):
        """Test basic orderbook with one level on each side."""
        raw = {
            "yes": [[48, 100]],  # YES bid at 48¢
            "no": [[51, 200]]     # NO bid at 51¢ → YES ask at 49¢
        }

        ob = OrderBook("TEST", raw)

        assert not ob.is_empty()
        assert ob.best_bid == 48
        assert ob.best_ask == 49  # 100 - 51 = 49
        assert ob.mid_price == 48.5
        assert ob.spread == 1
        assert ob.bid_depth == 100
        assert ob.ask_depth == 200

    def test_no_bid_conversion(self):
        """Test that NO bids are correctly converted to YES asks."""
        raw = {
            "yes": [],
            "no": [[40, 100], [60, 200], [70, 300]]
        }

        ob = OrderBook("TEST", raw)

        # NO bid at 40¢ → YES ask at 60¢
        # NO bid at 60¢ → YES ask at 40¢
        # NO bid at 70¢ → YES ask at 30¢

        assert len(ob.yes_asks) == 3
        assert ob.best_ask == 30  # Lowest ask (from highest NO bid)

        # Check all conversions
        ask_prices = sorted([ask.price for ask in ob.yes_asks])
        assert ask_prices == [30, 40, 60]

    def test_multi_level_orderbook(self):
        """Test orderbook with multiple price levels."""
        raw = {
            "yes": [[48, 307], [47, 319], [46, 326], [45, 333], [44, 600]],
            "no": [[51, 873], [49, 306], [48, 312], [47, 319], [46, 326]]
        }

        ob = OrderBook("TEST", raw)

        assert ob.best_bid == 48
        assert ob.best_ask == 49  # 100 - 51 = 49
        assert ob.spread == 1
        assert ob.mid_price == 48.5

        # Check depth
        assert ob.bid_depth == 307 + 319 + 326 + 333 + 600
        assert ob.ask_depth == 873 + 306 + 312 + 319 + 326


class TestOrderBookEdgeCases:
    """Test edge cases and error conditions."""

    def test_crossed_market(self):
        """Test detection of crossed market (bid > ask)."""
        raw = {
            "yes": [[60, 100]],  # YES bid at 60¢
            "no": [[50, 100]]     # NO bid at 50¢ → YES ask at 50¢
        }

        ob = OrderBook("TEST", raw)

        assert ob.is_crossed()
        assert ob.best_bid == 60
        assert ob.best_ask == 50
        # Spread is negative in crossed market
        assert ob.spread == -10

    def test_one_sided_bids_only(self):
        """Test orderbook with only bids."""
        raw = {
            "yes": [[48, 100], [47, 200]],
            "no": []
        }

        ob = OrderBook("TEST", raw)

        assert ob.is_one_sided()
        assert ob.best_bid == 48
        assert ob.best_ask is None
        assert ob.mid_price is None
        assert ob.bid_depth == 300
        assert ob.ask_depth == 0

    def test_one_sided_asks_only(self):
        """Test orderbook with only asks."""
        raw = {
            "yes": [],
            "no": [[51, 100], [52, 200]]
        }

        ob = OrderBook("TEST", raw)

        assert ob.is_one_sided()
        assert ob.best_bid is None
        assert ob.best_ask == 48  # 100 - 52 = 48 (best ask from worst NO bid)
        assert ob.mid_price is None


class TestVWAP:
    """Test Volume-Weighted Average Price calculations."""

    def test_vwap_bid_single_level(self):
        """Test VWAP when filling from single price level."""
        raw = {
            "yes": [[48, 500]],
            "no": []
        }

        ob = OrderBook("TEST", raw)

        # Fill 100 contracts at 48¢
        vwap = ob.get_vwap("bid", 100)
        assert vwap == 48.0

    def test_vwap_bid_multiple_levels(self):
        """Test VWAP across multiple price levels."""
        raw = {
            "yes": [[48, 100], [47, 200], [46, 300]],
            "no": []
        }

        ob = OrderBook("TEST", raw)

        # Fill 250 contracts: 100 at 48¢, 150 at 47¢
        vwap = ob.get_vwap("bid", 250)
        expected = (48 * 100 + 47 * 150) / 250
        assert abs(vwap - expected) < 0.01

    def test_vwap_ask_multiple_levels(self):
        """Test VWAP for ask side."""
        raw = {
            "yes": [],
            "no": [[51, 100], [50, 200], [49, 300]]  # YES asks at 49¢, 50¢, 51¢
        }

        ob = OrderBook("TEST", raw)

        # Fill 250 contracts: 100 at 49¢, 150 at 50¢
        vwap = ob.get_vwap("ask", 250)
        expected = (49 * 100 + 50 * 150) / 250
        assert abs(vwap - expected) < 0.01

    def test_vwap_insufficient_liquidity(self):
        """Test VWAP returns None when not enough liquidity."""
        raw = {
            "yes": [[48, 100]],
            "no": []
        }

        ob = OrderBook("TEST", raw)

        # Try to fill 200 contracts but only 100 available
        vwap = ob.get_vwap("bid", 200)
        assert vwap is None


class TestDepth:
    """Test depth analysis functions."""

    def test_cumulative_depth_bids(self):
        """Test cumulative depth calculation for bids."""
        raw = {
            "yes": [[48, 100], [47, 200], [46, 300], [45, 400]],
            "no": []
        }

        ob = OrderBook("TEST", raw)

        assert ob.get_cumulative_depth("bid", 1) == 100  # Top level only
        assert ob.get_cumulative_depth("bid", 2) == 300  # Top 2 levels
        assert ob.get_cumulative_depth("bid", 10) == 1000  # All levels

    def test_cumulative_depth_asks(self):
        """Test cumulative depth calculation for asks."""
        raw = {
            "yes": [],
            "no": [[51, 100], [50, 200], [49, 300]]
        }

        ob = OrderBook("TEST", raw)

        # NO bids convert to: 49¢ (100), 50¢ (200), 51¢ (300)
        assert ob.get_cumulative_depth("ask", 1) == 100  # Best ask (49¢)
        assert ob.get_cumulative_depth("ask", 2) == 300
        assert ob.get_cumulative_depth("ask", 10) == 600

    def test_depth_at_price(self):
        """Test getting depth at specific price."""
        raw = {
            "yes": [[48, 100], [47, 200], [48, 150]],  # Two levels at 48¢
            "no": []
        }

        ob = OrderBook("TEST", raw)

        assert ob.get_depth_at_price(48, "bid") == 250  # 100 + 150
        assert ob.get_depth_at_price(47, "bid") == 200
        assert ob.get_depth_at_price(46, "bid") == 0  # No depth at 46¢


class TestSnapshot:
    """Test orderbook snapshot functionality."""

    def test_snapshot_creation(self):
        """Test creating orderbook snapshot."""
        raw = {
            "yes": [[48, 100]],
            "no": [[51, 200]]
        }

        ob = OrderBook("TEST-TICKER", raw)
        snapshot = ob.get_snapshot()

        assert snapshot.ticker == "TEST-TICKER"
        assert snapshot.best_bid == 48
        assert snapshot.best_ask == 49
        assert snapshot.mid_price == 48.5
        assert snapshot.spread == 1
        assert snapshot.bid_depth == 100
        assert snapshot.ask_depth == 200

    def test_snapshot_is_copy(self):
        """Test that snapshot is independent copy."""
        raw = {"yes": [[48, 100]], "no": [[51, 200]]}

        ob = OrderBook("TEST", raw)
        snapshot = ob.get_snapshot()

        # Modify snapshot
        snapshot.yes_bids.append(Quote(price=47, quantity=999))

        # Original should be unchanged
        assert len(ob.yes_bids) == 1
        assert ob.yes_bids[0].quantity == 100


class TestFormatting:
    """Test orderbook formatting."""

    def test_format_orderbook(self):
        """Test pretty-printing orderbook."""
        raw = {
            "yes": [[48, 307], [47, 319]],
            "no": [[51, 873], [49, 306]]
        }

        ob = OrderBook("TEST-MARKET", raw)
        output = format_orderbook(ob, levels=2)

        # Check key elements are in output
        assert "TEST-MARKET" in output
        assert "48¢" in output
        assert "49¢" in output
        assert "307" in output

    def test_format_empty_orderbook(self):
        """Test formatting empty orderbook."""
        ob = OrderBook("EMPTY", {"yes": [], "no": []})
        output = format_orderbook(ob)

        assert "EMPTY ORDERBOOK" in output


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
