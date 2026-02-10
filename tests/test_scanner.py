"""
Tests for the market scanner module.
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.scanner import (
    MarketScore, ScanConfig,
    score_spread, score_volume, score_fee_efficiency, score_expiry,
    score_liquidity, score_price_level, suggest_parameters,
    parse_market_data, score_market, filter_market, scan_markets,
    format_results, generate_config_yaml,
)


# ==================== Scoring Function Tests ====================

class TestScoreSpread:
    def test_zero_spread(self):
        assert score_spread(0) == 0.0

    def test_one_cent_spread(self):
        assert score_spread(1) == 10.0

    def test_two_cent_spread(self):
        assert score_spread(2) == 30.0

    def test_three_cent_spread(self):
        assert score_spread(3) == 60.0

    def test_sweet_spot_spread(self):
        """4-8c is ideal for market making."""
        for s in [4, 5, 6, 7, 8]:
            assert score_spread(s) == 100.0

    def test_wide_spread(self):
        assert score_spread(10) == 75.0
        assert score_spread(15) == 50.0

    def test_very_wide_spread(self):
        assert score_spread(25) == 25.0


class TestScoreVolume:
    def test_zero_volume(self):
        assert score_volume(0) == 0.0

    def test_low_volume(self):
        assert score_volume(5) == 5.0

    def test_moderate_volume(self):
        assert score_volume(300) == 70.0

    def test_ideal_volume(self):
        """1k-10k is the sweet spot."""
        assert score_volume(5000) == 100.0

    def test_high_volume(self):
        """Very high volume markets are too competitive."""
        assert score_volume(20000) == 60.0

    def test_extreme_volume(self):
        assert score_volume(100000) == 35.0


class TestScoreFeeEfficiency:
    def test_zero_spread_returns_zero(self):
        assert score_fee_efficiency(50.0, 0) == 0.0

    def test_invalid_mid_price(self):
        assert score_fee_efficiency(0, 5) == 0.0
        assert score_fee_efficiency(100, 5) == 0.0

    def test_wide_spread_at_50c(self):
        """At 50c, round-trip fee is ~1.75c. 10c spread should have high efficiency."""
        result = score_fee_efficiency(50.0, 10)
        assert result > 80.0

    def test_tight_spread_at_50c(self):
        """At 50c, round-trip fee ~0.875c, 2c spread has decent but not great efficiency."""
        result = score_fee_efficiency(50.0, 2)
        # fee = 2 * 0.0175 * 0.5 * 0.5 * 100 = 0.875c. ratio = 1 - 0.875/2 = 0.5625
        assert 50.0 < result < 60.0

    def test_away_from_50c_better_efficiency(self):
        """Markets at 20c have lower fees, so same spread has better efficiency."""
        score_20c = score_fee_efficiency(20.0, 5)
        score_50c = score_fee_efficiency(50.0, 5)
        assert score_20c > score_50c

    def test_extreme_price_high_efficiency(self):
        """At 10c, fees are very low, almost all spread is profit."""
        result = score_fee_efficiency(10.0, 5)
        assert result > 90.0


class TestScoreExpiry:
    def test_none_expiry(self):
        assert score_expiry(None) == 50.0

    def test_very_short_expiry(self):
        assert score_expiry(0.3) == 0.0

    def test_one_day(self):
        assert score_expiry(0.8) == 15.0

    def test_few_days(self):
        assert score_expiry(2.0) == 40.0

    def test_one_week(self):
        assert score_expiry(5.0) == 70.0

    def test_sweet_spot(self):
        """7-30 days is ideal."""
        assert score_expiry(15.0) == 100.0

    def test_months_out(self):
        assert score_expiry(60.0) == 80.0

    def test_very_far(self):
        assert score_expiry(200.0) == 45.0


class TestScoreLiquidity:
    def test_zero_liquidity(self):
        assert score_liquidity(0, 0.0) == 0.0

    def test_moderate_oi_no_dollars(self):
        result = score_liquidity(200, 0.0)
        assert result == 30.0  # (60 + 0) / 2

    def test_high_both(self):
        result = score_liquidity(2000, 20000.0)
        assert result == 100.0

    def test_mixed(self):
        # OI 50 => 40, liq 5000 => 80 => avg = 60
        result = score_liquidity(50, 5000.0)
        assert result == 60.0


class TestScorePriceLevel:
    def test_near_settled(self):
        assert score_price_level(3.0) == 5.0
        assert score_price_level(97.0) == 5.0

    def test_extreme(self):
        assert score_price_level(8.0) == 30.0
        assert score_price_level(92.0) == 30.0

    def test_moderate(self):
        assert score_price_level(20.0) == 70.0
        assert score_price_level(80.0) == 70.0

    def test_center(self):
        assert score_price_level(50.0) == 100.0

    def test_good_range(self):
        # 40c is in the 35-65 center band
        assert score_price_level(40.0) == 100.0
        # 30c is in the 25-35 band
        assert score_price_level(30.0) == 85.0


# ==================== Parameter Suggestion Tests ====================

class TestSuggestParameters:
    def _make_market(self, spread=5, volume=500, **kwargs):
        return MarketScore(
            ticker="TEST", event_ticker="", title="Test",
            yes_bid=48, yes_ask=48 + spread, spread=spread,
            mid_price=48 + spread / 2, volume_24h=volume,
            open_interest=100, liquidity_dollars=1000.0,
            **kwargs,
        )

    def test_tight_spread_aggressive(self):
        m = self._make_market(spread=2, volume=5000)
        gamma, sigma, k, size, max_pos = suggest_parameters(m)
        assert gamma == 0.05
        assert k == 2.0  # 1001-10000 range

    def test_wide_spread_conservative(self):
        m = self._make_market(spread=12, volume=50)
        gamma, sigma, k, size, max_pos = suggest_parameters(m)
        assert gamma == 0.2
        assert k == 0.7

    def test_volume_scales_size(self):
        m_low = self._make_market(volume=50)
        m_high = self._make_market(volume=5000)
        _, _, _, size_low, _ = suggest_parameters(m_low)
        _, _, _, size_high, _ = suggest_parameters(m_high)
        assert size_high > size_low

    def test_max_position_capped(self):
        m = self._make_market(volume=50000)
        _, _, _, _, max_pos = suggest_parameters(m)
        assert max_pos == 100  # Capped


# ==================== Market Parsing Tests ====================

class TestParseMarketData:
    def test_basic_parsing(self):
        raw = {
            'ticker': 'TEST-MKT',
            'event_ticker': 'TEST-EVT',
            'title': 'Will it rain tomorrow?',
            'yes_bid': 45,
            'yes_ask': 52,
            'volume_24h': 500,
            'open_interest': 200,
            'liquidity': '1500.50',
            'close_time': '2026-03-15T12:00:00Z',
        }
        m = parse_market_data(raw)
        assert m is not None
        assert m.ticker == 'TEST-MKT'
        assert m.yes_bid == 45
        assert m.yes_ask == 52
        assert m.spread == 7
        assert m.mid_price == 48.5
        assert m.volume_24h == 500
        assert m.liquidity_dollars == 1500.50
        assert m.days_to_expiry is not None
        assert m.days_to_expiry > 0

    def test_no_bid_to_yes_ask_conversion(self):
        """If yes_ask is missing, derive from no_bid."""
        raw = {
            'ticker': 'TEST',
            'yes_bid': 45,
            'yes_ask': 0,
            'no_bid': 48,  # = YES ask at 52
        }
        m = parse_market_data(raw)
        assert m is not None
        assert m.yes_ask == 52
        assert m.spread == 7

    def test_missing_ticker(self):
        assert parse_market_data({}) is None

    def test_no_bid_or_ask(self):
        assert parse_market_data({'ticker': 'X', 'yes_bid': 0, 'yes_ask': 0}) is None

    def test_crossed_market(self):
        raw = {'ticker': 'X', 'yes_bid': 55, 'yes_ask': 50}
        assert parse_market_data(raw) is None

    def test_iso_close_time(self):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        raw = {
            'ticker': 'X', 'yes_bid': 40, 'yes_ask': 50,
            'close_time': future.isoformat(),
        }
        m = parse_market_data(raw)
        assert m.days_to_expiry is not None
        assert 9.0 < m.days_to_expiry < 11.0

    def test_epoch_close_time(self):
        future = datetime.now(timezone.utc) + timedelta(days=5)
        raw = {
            'ticker': 'X', 'yes_bid': 40, 'yes_ask': 50,
            'close_time': future.timestamp(),
        }
        m = parse_market_data(raw)
        assert m.days_to_expiry is not None
        assert 4.0 < m.days_to_expiry < 6.0

    def test_volume_fallback_to_volume(self):
        raw = {'ticker': 'X', 'yes_bid': 40, 'yes_ask': 50, 'volume': 300}
        m = parse_market_data(raw)
        assert m.volume_24h == 300

    def test_string_liquidity(self):
        raw = {'ticker': 'X', 'yes_bid': 40, 'yes_ask': 50, 'liquidity': '5432.10'}
        m = parse_market_data(raw)
        assert m.liquidity_dollars == 5432.10


# ==================== Filtering Tests ====================

class TestFilterMarket:
    def _make(self, **overrides):
        defaults = dict(
            ticker="T", event_ticker="", title="",
            yes_bid=45, yes_ask=52, spread=7, mid_price=48.5,
            volume_24h=500, open_interest=100, liquidity_dollars=1000.0,
            days_to_expiry=15.0,
        )
        defaults.update(overrides)
        return MarketScore(**defaults)

    def test_passes_all_filters(self):
        m = self._make()
        assert filter_market(m, ScanConfig()) is True

    def test_spread_too_narrow(self):
        m = self._make(spread=1)
        assert filter_market(m, ScanConfig(min_spread=2)) is False

    def test_volume_too_low(self):
        m = self._make(volume_24h=5)
        assert filter_market(m, ScanConfig(min_volume_24h=10)) is False

    def test_price_too_low(self):
        m = self._make(mid_price=3.0)
        assert filter_market(m, ScanConfig(min_price=5)) is False

    def test_price_too_high(self):
        m = self._make(mid_price=97.0)
        assert filter_market(m, ScanConfig(max_price=95)) is False

    def test_expiry_too_soon(self):
        m = self._make(days_to_expiry=0.5)
        assert filter_market(m, ScanConfig(min_days_to_expiry=1.0)) is False

    def test_expiry_too_far(self):
        m = self._make(days_to_expiry=400.0)
        assert filter_market(m, ScanConfig(max_days_to_expiry=365.0)) is False

    def test_none_expiry_passes(self):
        m = self._make(days_to_expiry=None)
        assert filter_market(m, ScanConfig()) is True


# ==================== Full Scan Pipeline Tests ====================

class TestScanMarkets:
    def _make_raw(self, ticker, bid, ask, volume=500, oi=100, **extra):
        future = datetime.now(timezone.utc) + timedelta(days=15)
        d = {
            'ticker': ticker, 'yes_bid': bid, 'yes_ask': ask,
            'volume_24h': volume, 'open_interest': oi,
            'liquidity': '1000.0',
            'close_time': future.isoformat(),
            'title': f'Market {ticker}',
            'event_ticker': f'EVT-{ticker}',
        }
        d.update(extra)
        return d

    def test_scan_returns_sorted(self):
        """Markets are sorted by total score descending."""
        raw = [
            self._make_raw('A', 45, 55, volume=50),   # 10c spread, low vol
            self._make_raw('B', 47, 53, volume=2000),  # 6c spread, good vol
            self._make_raw('C', 48, 52, volume=500),   # 4c spread, moderate vol
        ]
        results = scan_markets(raw)
        assert len(results) == 3
        # B should score highest (sweet spot spread + good volume)
        assert results[0].total_score >= results[1].total_score
        assert results[1].total_score >= results[2].total_score

    def test_scan_filters_applied(self):
        raw = [
            self._make_raw('GOOD', 45, 52, volume=500),
            self._make_raw('LOW_VOL', 45, 52, volume=1),
            self._make_raw('TIGHT', 49, 50, volume=500),  # 1c spread
        ]
        config = ScanConfig(min_spread=2, min_volume_24h=10)
        results = scan_markets(raw, config)
        tickers = [m.ticker for m in results]
        assert 'GOOD' in tickers
        assert 'LOW_VOL' not in tickers
        assert 'TIGHT' not in tickers

    def test_scan_top_n(self):
        raw = [self._make_raw(f'M{i}', 45, 52, volume=500 + i) for i in range(30)]
        config = ScanConfig(top_n=5)
        results = scan_markets(raw, config)
        assert len(results) == 5

    def test_empty_input(self):
        assert scan_markets([]) == []

    def test_all_filtered_out(self):
        raw = [self._make_raw('X', 49, 50)]  # 1c spread
        config = ScanConfig(min_spread=3)
        assert scan_markets(raw, config) == []

    def test_parameters_populated(self):
        raw = [self._make_raw('TEST', 45, 52, volume=1000)]
        results = scan_markets(raw)
        m = results[0]
        assert m.suggested_gamma > 0
        assert m.suggested_sigma > 0
        assert m.suggested_k > 0
        assert m.suggested_base_size >= 1
        assert m.suggested_max_position >= 10


# ==================== Formatting Tests ====================

class TestFormatResults:
    def test_empty_results(self):
        result = format_results([])
        assert "No markets found" in result

    def test_format_with_results(self):
        m = MarketScore(
            ticker="TEST-MKT", event_ticker="EVT", title="Test Market",
            yes_bid=45, yes_ask=52, spread=7, mid_price=48.5,
            volume_24h=1000, open_interest=500, liquidity_dollars=5000.0,
            days_to_expiry=15.0, total_score=85.3,
            suggested_gamma=0.1, suggested_sigma=4.2, suggested_k=1.5,
            suggested_base_size=5, suggested_max_position=25,
        )
        result = format_results([m])
        assert "TEST-MKT" in result
        assert "85.3" in result
        assert "Suggested Parameters" in result

    def test_generates_yaml(self):
        m = MarketScore(
            ticker="TEST-MKT", event_ticker="EVT", title="Test Market",
            yes_bid=45, yes_ask=52, spread=7, mid_price=48.5,
            volume_24h=1000, open_interest=500, liquidity_dollars=5000.0,
            days_to_expiry=15.0, total_score=85.3,
            suggested_gamma=0.1, suggested_sigma=4.2, suggested_k=1.5,
            suggested_base_size=5, suggested_max_position=25,
        )
        yaml_out = generate_config_yaml([m])
        assert "markets:" in yaml_out
        assert "ticker: TEST-MKT" in yaml_out
        assert "gamma: 0.1" in yaml_out
        assert "max_loss_cents: 100.0" in yaml_out


# ==================== Client Pagination Tests ====================

class TestClientPagination:
    """Test that get_markets returns (markets, cursor) tuple."""

    def test_get_markets_returns_tuple(self):
        """Verify the updated signature returns a tuple."""
        from unittest.mock import MagicMock, patch
        from src.client import KalshiClient

        with patch.object(KalshiClient, '__init__', lambda self, **kwargs: None):
            client = KalshiClient(key_id='', private_key='', host='')
            client.host = 'https://demo-api.kalshi.co/trade-api/v2'
            client.client = MagicMock()

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b'{"markets": [{"ticker": "A"}], "cursor": "abc123"}'
            client.client.call_api.return_value = mock_response

            markets, cursor = client.get_markets(limit=100, status="open")
            assert len(markets) == 1
            assert markets[0]['ticker'] == 'A'
            assert cursor == 'abc123'

    def test_get_all_markets_paginates(self):
        """Verify get_all_markets follows cursor pagination."""
        from unittest.mock import MagicMock, patch, call
        from src.client import KalshiClient

        with patch.object(KalshiClient, '__init__', lambda self, **kwargs: None):
            client = KalshiClient(key_id='', private_key='', host='')
            client.host = 'https://demo-api.kalshi.co/trade-api/v2'
            client.client = MagicMock()

            # Page 1: returns cursor
            resp1 = MagicMock()
            resp1.status = 200
            resp1.read.return_value = b'{"markets": [{"ticker": "A"}, {"ticker": "B"}], "cursor": "page2"}'

            # Page 2: no cursor (last page)
            resp2 = MagicMock()
            resp2.status = 200
            resp2.read.return_value = b'{"markets": [{"ticker": "C"}], "cursor": null}'

            client.client.call_api.side_effect = [resp1, resp2]

            results = client.get_all_markets(status="open")
            assert len(results) == 3
            assert [m['ticker'] for m in results] == ['A', 'B', 'C']
            assert client.client.call_api.call_count == 2
