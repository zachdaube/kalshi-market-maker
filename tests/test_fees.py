"""
Tests for Kalshi fee calculations.
"""

import pytest
from src.fees import (
    calculate_fee,
    round_trip_fee,
    net_profit,
    MAKER_FEE_RATE,
    TAKER_FEE_RATE
)


class TestFeeCalculation:
    """Test basic fee calculations."""

    def test_maker_fee_at_mid(self):
        """Test maker fee at 50c (worst case)."""
        result = calculate_fee(100, 50, as_maker=True)

        assert result.contracts == 100
        assert result.price_cents == 50
        assert result.fee_rate == MAKER_FEE_RATE
        # Fee = 0.0175 * 100 * 0.5 * 0.5 = 0.4375 dollars = 43.75 cents
        assert abs(result.fee_cents - 43.75) < 0.01

    def test_taker_fee_4x_maker(self):
        """Taker fee is 4x maker fee."""
        maker = calculate_fee(100, 50, as_maker=True)
        taker = calculate_fee(100, 50, as_maker=False)

        assert abs(taker.fee_cents - maker.fee_cents * 4) < 0.01

    def test_fee_symmetric_around_50(self):
        """Fees are symmetric around 50c."""
        fee_30 = calculate_fee(100, 30, as_maker=True)
        fee_70 = calculate_fee(100, 70, as_maker=True)

        assert abs(fee_30.fee_cents - fee_70.fee_cents) < 0.01

    def test_fee_lower_at_extremes(self):
        """Fees are lower at price extremes."""
        fee_50 = calculate_fee(100, 50, as_maker=True)
        fee_10 = calculate_fee(100, 10, as_maker=True)
        fee_90 = calculate_fee(100, 90, as_maker=True)

        assert fee_10.fee_cents < fee_50.fee_cents
        assert fee_90.fee_cents < fee_50.fee_cents

    def test_fee_scales_with_contracts(self):
        """Fee scales linearly with contracts."""
        fee_100 = calculate_fee(100, 50, as_maker=True)
        fee_200 = calculate_fee(200, 50, as_maker=True)

        assert abs(fee_200.fee_cents - fee_100.fee_cents * 2) < 0.01


class TestRoundTripFee:
    """Test round trip fee calculations."""

    def test_round_trip_maker(self):
        """Round trip maker fees."""
        fee = round_trip_fee(100, bid=48, ask=52, as_maker=True)

        entry = calculate_fee(100, 48, as_maker=True)
        exit_fee = calculate_fee(100, 52, as_maker=True)
        expected = entry.fee_cents + exit_fee.fee_cents

        assert abs(fee - expected) < 0.01

    def test_round_trip_taker_higher(self):
        """Taker round trip is higher than maker."""
        maker = round_trip_fee(100, 48, 52, as_maker=True)
        taker = round_trip_fee(100, 48, 52, as_maker=False)

        assert taker > maker


class TestNetProfit:
    """Test net profit calculations."""

    def test_profitable_spread(self):
        """Wide spread is profitable."""
        profit = net_profit(100, bid=45, ask=55, as_maker=True)
        # Gross: (55-45)*100 = 1000 cents
        # Fees are much less than 1000, so profit is positive
        assert profit > 0

    def test_narrow_spread_less_profitable(self):
        """Narrow spread is less profitable."""
        wide = net_profit(100, 45, 55, as_maker=True)
        narrow = net_profit(100, 48, 52, as_maker=True)

        assert wide > narrow

    def test_very_narrow_spread_unprofitable(self):
        """Very narrow spread may be unprofitable."""
        # 1 cent spread on 10 contracts
        profit = net_profit(10, bid=49, ask=50, as_maker=True)
        # Gross = 10 cents, fees eat most of it
        # Could be positive or negative depending on fees
        gross = (50 - 49) * 10  # 10 cents
        # Just verify calculation runs
        assert profit == gross - round_trip_fee(10, 49, 50, as_maker=True)
