"""
Tests for flow detection and toxic flow protection.
"""

import pytest
from datetime import datetime, timedelta
from src.flow import (
    Trade,
    FlowAnalyzer,
    FlowConfig,
    FlowMetrics,
    QuoteAdjustment,
    parse_kalshi_trades,
    format_flow_metrics,
    format_adjustment
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def analyzer():
    """Create a flow analyzer with default config."""
    return FlowAnalyzer()


@pytest.fixture
def custom_analyzer():
    """Create analyzer with custom (stricter) config."""
    config = FlowConfig(
        toxic_run_length=3,
        toxic_imbalance=0.6,
        toxic_price_change=3
    )
    return FlowAnalyzer(config)


def create_trade(
    ticker: str = "TEST",
    price: int = 50,
    quantity: int = 100,
    side: str = "yes",
    timestamp: datetime = None
) -> Trade:
    """Helper to create a trade."""
    if timestamp is None:
        timestamp = datetime.now()

    return Trade(
        ticker=ticker,
        price=price,
        quantity=quantity,
        side=side,
        timestamp=timestamp
    )


def create_trade_sequence(
    ticker: str,
    count: int,
    side: str,
    start_price: int = 48,
    price_increment: int = 0,
    quantity: int = 100,
    time_spacing_seconds: float = 1.0
) -> list[Trade]:
    """Create a sequence of trades."""
    base_time = datetime.now() - timedelta(seconds=count * time_spacing_seconds)
    trades = []

    for i in range(count):
        price = start_price + (i * price_increment)
        timestamp = base_time + timedelta(seconds=i * time_spacing_seconds)

        trades.append(create_trade(
            ticker=ticker,
            price=price,
            quantity=quantity,
            side=side,
            timestamp=timestamp
        ))

    return trades


# ============================================================================
# Test Trade Model
# ============================================================================

class TestTrade:
    """Test the Trade model."""

    def test_yes_price_for_yes_trade(self):
        """YES trade returns price directly."""
        trade = create_trade(price=48, side="yes")
        assert trade.yes_price == 48

    def test_yes_price_for_no_trade(self):
        """NO trade converts to YES price."""
        trade = create_trade(price=52, side="no")
        assert trade.yes_price == 48  # 100 - 52

    def test_yes_direction(self):
        """YES trade has direction +1 (bullish)."""
        trade = create_trade(side="yes")
        assert trade.direction == 1

    def test_no_direction(self):
        """NO trade has direction -1 (bearish)."""
        trade = create_trade(side="no")
        assert trade.direction == -1


# ============================================================================
# Test Run Detection
# ============================================================================

class TestRunDetection:
    """Test detection of consecutive trades in same direction."""

    def test_no_run_alternating_trades(self, analyzer):
        """No run when trades alternate direction."""
        trades = [
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=3)),
            create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=2)),
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=1)),
        ]

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.run_length == 1
        assert metrics.run_direction == 1  # Last trade was YES (buy)

    def test_run_of_3_buys(self, analyzer):
        """Detect run of 3 buy trades."""
        trades = create_trade_sequence("TEST", count=3, side="yes")
        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.run_length == 3
        assert metrics.run_direction == 1  # Buying

    def test_run_of_5_sells(self, analyzer):
        """Detect run of 5 sell trades."""
        trades = create_trade_sequence("TEST", count=5, side="no")
        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.run_length == 5
        assert metrics.run_direction == -1  # Selling

    def test_max_run_tracks_longest(self, analyzer):
        """Max run tracks the longest run in history."""
        # Run of 5, then alternating, then run of 3
        trades = (
            create_trade_sequence("TEST", count=5, side="yes", time_spacing_seconds=1.0) +
            [create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=5))] +
            create_trade_sequence("TEST", count=3, side="yes", time_spacing_seconds=0.5)
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.max_run_length == 5
        assert metrics.run_length == 3  # Current run


# ============================================================================
# Test Trade Imbalance
# ============================================================================

class TestTradeImbalance:
    """Test detection of buy/sell imbalance."""

    def test_balanced_flow(self, analyzer):
        """Equal buys and sells = balanced."""
        trades = (
            create_trade_sequence("TEST", count=5, side="yes", quantity=100) +
            create_trade_sequence("TEST", count=5, side="no", quantity=100)
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert abs(metrics.trade_imbalance) < 0.01  # Nearly zero
        assert 0.9 < metrics.volume_imbalance_ratio < 1.1  # Nearly 1:1

    def test_buy_heavy_imbalance(self, analyzer):
        """More buys than sells = positive imbalance."""
        trades = (
            create_trade_sequence("TEST", count=7, side="yes", quantity=100) +
            create_trade_sequence("TEST", count=3, side="no", quantity=100)
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        # 700 buy, 300 sell = +400 / 1000 = +0.4 = 40% imbalance
        assert metrics.trade_imbalance == pytest.approx(0.4, abs=0.01)
        assert metrics.volume_imbalance_ratio == pytest.approx(700/300, abs=0.1)

    def test_sell_heavy_imbalance(self, analyzer):
        """More sells than buys = negative imbalance."""
        trades = (
            create_trade_sequence("TEST", count=2, side="yes", quantity=100) +
            create_trade_sequence("TEST", count=8, side="no", quantity=100)
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        # 200 buy, 800 sell = -600 / 1000 = -0.6 = 60% sell imbalance
        assert metrics.trade_imbalance == pytest.approx(-0.6, abs=0.01)


# ============================================================================
# Test Price Momentum
# ============================================================================

class TestPriceMomentum:
    """Test detection of price momentum."""

    def test_no_momentum_stable_price(self, analyzer):
        """No price change = no momentum."""
        trades = create_trade_sequence("TEST", count=5, side="yes", start_price=50, price_increment=0)

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.price_change == 0
        assert metrics.price_velocity == 0.0

    def test_upward_momentum(self, analyzer):
        """Prices rising = positive momentum."""
        # 5 trades: 48, 49, 50, 51, 52
        trades = create_trade_sequence("TEST", count=5, side="yes", start_price=48, price_increment=1)

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.price_change == 4  # 52 - 48
        assert metrics.price_velocity == pytest.approx(4/5, abs=0.01)  # 0.8¢ per trade

    def test_downward_momentum(self, analyzer):
        """Prices falling = negative momentum."""
        # 5 trades: 52, 51, 50, 49, 48
        trades = create_trade_sequence("TEST", count=5, side="yes", start_price=52, price_increment=-1)

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.price_change == -4  # 48 - 52
        assert metrics.price_velocity == pytest.approx(-4/5, abs=0.01)


# ============================================================================
# Test Volume Statistics
# ============================================================================

class TestVolumeStatistics:
    """Test volume calculations."""

    def test_total_volume(self, analyzer):
        """Total volume is sum of all trades."""
        trades = [
            create_trade("TEST", quantity=100),
            create_trade("TEST", quantity=200),
            create_trade("TEST", quantity=150),
        ]

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.total_volume == 450

    def test_average_trade_size(self, analyzer):
        """Average trade size calculated correctly."""
        trades = [
            create_trade("TEST", quantity=100),
            create_trade("TEST", quantity=200),
            create_trade("TEST", quantity=300),
        ]

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.avg_trade_size == pytest.approx(200.0)


# ============================================================================
# Test Toxicity Scoring
# ============================================================================

class TestToxicityScoring:
    """Test toxicity score calculation."""

    def test_normal_flow_low_toxicity(self, analyzer):
        """Normal trading = low toxicity score."""
        # Balanced, small trades, no runs
        trades = (
            [create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=6))] +
            [create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=5))] +
            [create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=4))] +
            [create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=3))]
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.toxicity_score < 30  # Low toxicity
        assert not metrics.is_toxic

    def test_long_run_high_toxicity(self, analyzer):
        """Long run of same direction = high toxicity."""
        # 6 consecutive buys
        trades = create_trade_sequence("TEST", count=6, side="yes")

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.toxicity_score >= 60  # High toxicity from run
        assert metrics.is_toxic

    def test_high_imbalance_high_toxicity(self, analyzer):
        """Heavy imbalance = high toxicity."""
        # 9 buys, 1 sell = 80% imbalance
        trades = (
            create_trade_sequence("TEST", count=9, side="yes") +
            [create_trade("TEST", side="no")]
        )

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert metrics.trade_imbalance == pytest.approx(0.8, abs=0.01)
        assert metrics.toxicity_score >= 40  # Elevated toxicity from imbalance

    def test_sharp_price_move_high_toxicity(self, analyzer):
        """Sharp price movement = high toxicity."""
        # Price moves from 45 to 55 (10 cent move)
        trades = create_trade_sequence("TEST", count=5, side="yes", start_price=45, price_increment=2)

        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        assert abs(metrics.price_change) >= 5
        assert metrics.toxicity_score >= 40  # Elevated toxicity


# ============================================================================
# Test Quote Adjustments
# ============================================================================

class TestQuoteAdjustments:
    """Test quote adjustment recommendations."""

    def test_normal_flow_no_adjustment(self, analyzer):
        """Normal flow = no adjustment needed."""
        # Balanced alternating trades
        trades = [
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=3)),
            create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=2)),
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=1)),
        ]

        analyzer.add_trades(trades)
        adj = analyzer.recommend_adjustment("TEST")

        assert adj.action == "normal"
        assert adj.spread_multiplier == 1.0
        assert adj.size_multiplier == 1.0

    def test_moderate_toxicity_reduce_action(self, analyzer):
        """Moderate toxicity = reduce size and widen spread."""
        # Run of 4 buys (moderate)
        trades = create_trade_sequence("TEST", count=4, side="yes")

        analyzer.add_trades(trades)
        adj = analyzer.recommend_adjustment("TEST")

        assert adj.action in ["reduce", "widen"]
        assert adj.spread_multiplier > 1.0
        assert adj.size_multiplier < 1.0

    def test_high_toxicity_widen_action(self, analyzer):
        """High toxicity = widen spreads significantly or pull."""
        # Run of 6 buys + price momentum
        trades = create_trade_sequence("TEST", count=6, side="yes", start_price=45, price_increment=1)

        analyzer.add_trades(trades)
        adj = analyzer.recommend_adjustment("TEST")

        # Could be either widen or pull depending on exact toxicity score
        assert adj.action in ["widen", "pull"]
        if adj.action == "widen":
            assert adj.spread_multiplier >= 2.0  # Double or more
            assert adj.size_multiplier <= 0.5  # Half or less

    def test_critical_toxicity_pull_quotes(self, analyzer):
        """Critical toxicity = pull quotes entirely."""
        # Extreme: 10 consecutive buys with momentum
        trades = create_trade_sequence("TEST", count=10, side="yes", start_price=40, price_increment=1)

        analyzer.add_trades(trades)
        adj = analyzer.recommend_adjustment("TEST")

        assert adj.action == "pull"
        assert adj.cooldown_seconds > 0

    def test_insufficient_data_normal(self, analyzer):
        """Insufficient data = quote normally."""
        # Only 1 trade
        analyzer.add_trade(create_trade("TEST"))
        adj = analyzer.recommend_adjustment("TEST")

        assert adj.action == "normal"


# ============================================================================
# Test Configuration
# ============================================================================

class TestFlowConfig:
    """Test custom configuration."""

    def test_custom_thresholds(self):
        """Custom config changes detection thresholds."""
        config = FlowConfig(
            toxic_run_length=3,
            toxic_imbalance=0.5,
            toxic_price_change=2
        )

        analyzer = FlowAnalyzer(config)

        # Run of 3 should now be toxic (default is 5)
        trades = create_trade_sequence("TEST", count=3, side="yes")
        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        # Should be more toxic with stricter config
        assert metrics.toxicity_score >= 50

    def test_time_window_filtering(self):
        """Trades outside time window are excluded."""
        config = FlowConfig(max_time_seconds=5.0)  # Only last 5 seconds
        analyzer = FlowAnalyzer(config)

        # Old trades (10 seconds ago)
        old_trades = [
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=10)),
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=9)),
        ]

        # Recent trades (2 seconds ago)
        recent_trades = [
            create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=2)),
            create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=1)),
        ]

        analyzer.add_trades(old_trades + recent_trades)
        metrics = analyzer.analyze_flow("TEST")

        # Should only analyze recent trades
        assert metrics.trades_count == 2
        assert metrics.run_direction == -1  # Recent trades were sells


# ============================================================================
# Test Kalshi Trade Parsing
# ============================================================================

class TestKalshiTradeParsing:
    """Test parsing of Kalshi API trade data."""

    def test_parse_simple_trade(self):
        """Parse a simple trade from Kalshi format."""
        raw_trades = [
            {
                'ticker': 'TESTMARKET',
                'yes_price': 52,
                'count': 150,
                'side': 'yes',
                'created_time': '2024-01-15T10:30:00Z'
            }
        ]

        trades = parse_kalshi_trades(raw_trades)

        assert len(trades) == 1
        assert trades[0].ticker == 'TESTMARKET'
        assert trades[0].price == 52
        assert trades[0].quantity == 150
        assert trades[0].side == 'yes'

    def test_parse_multiple_trades(self):
        """Parse multiple trades."""
        raw_trades = [
            {'ticker': 'TEST', 'yes_price': 48, 'count': 100, 'side': 'yes', 'created_time': '2024-01-15T10:00:00Z'},
            {'ticker': 'TEST', 'yes_price': 49, 'count': 200, 'side': 'no', 'created_time': '2024-01-15T10:01:00Z'},
        ]

        trades = parse_kalshi_trades(raw_trades)

        assert len(trades) == 2

    def test_parse_handles_missing_fields(self):
        """Gracefully handle missing fields."""
        raw_trades = [
            {'ticker': 'TEST'},  # Missing most fields
            {'ticker': 'TEST', 'price': 50, 'quantity': 100},  # Alternative field names
        ]

        trades = parse_kalshi_trades(raw_trades)

        # Should parse what it can
        assert len(trades) >= 1


# ============================================================================
# Test Multi-Market Tracking
# ============================================================================

class TestMultiMarketTracking:
    """Test tracking flow across multiple markets."""

    def test_separate_tracking_per_market(self, analyzer):
        """Each market tracked independently."""
        # Market 1: Toxic flow
        trades1 = create_trade_sequence("MARKET1", count=6, side="yes")
        analyzer.add_trades(trades1)

        # Market 2: Normal flow
        trades2 = [
            create_trade("MARKET2", side="yes", timestamp=datetime.now() - timedelta(seconds=2)),
            create_trade("MARKET2", side="no", timestamp=datetime.now() - timedelta(seconds=1)),
        ]
        analyzer.add_trades(trades2)

        # Market 1 should be toxic
        metrics1 = analyzer.analyze_flow("MARKET1")
        assert metrics1.is_toxic

        # Market 2 should be normal
        metrics2 = analyzer.analyze_flow("MARKET2")
        assert not metrics2.is_toxic

    def test_get_trade_count(self, analyzer):
        """Get trade count for specific market."""
        analyzer.add_trades(create_trade_sequence("MARKET1", count=5, side="yes"))
        analyzer.add_trades(create_trade_sequence("MARKET2", count=3, side="no"))

        assert analyzer.get_trade_count("MARKET1") == 5
        assert analyzer.get_trade_count("MARKET2") == 3
        assert analyzer.get_trade_count("MARKET3") == 0

    def test_clear_history(self, analyzer):
        """Clear trade history."""
        analyzer.add_trades(create_trade_sequence("MARKET1", count=5, side="yes"))
        analyzer.add_trades(create_trade_sequence("MARKET2", count=3, side="no"))

        # Clear specific market
        analyzer.clear_history("MARKET1")
        assert analyzer.get_trade_count("MARKET1") == 0
        assert analyzer.get_trade_count("MARKET2") == 3

        # Clear all
        analyzer.clear_history()
        assert analyzer.get_trade_count("MARKET2") == 0


# ============================================================================
# Test Formatting Functions
# ============================================================================

class TestFormatting:
    """Test pretty-printing functions."""

    def test_format_flow_metrics(self, analyzer):
        """Format flow metrics as string."""
        trades = create_trade_sequence("TEST", count=5, side="yes", start_price=48, price_increment=1)
        analyzer.add_trades(trades)
        metrics = analyzer.analyze_flow("TEST")

        output = format_flow_metrics(metrics)

        assert "TEST" in output
        assert "Run Detection" in output
        assert "Toxicity" in output

    def test_format_adjustment(self, analyzer):
        """Format quote adjustment as string."""
        trades = create_trade_sequence("TEST", count=6, side="yes")
        analyzer.add_trades(trades)
        adj = analyzer.recommend_adjustment("TEST")

        output = format_adjustment(adj)

        assert "Quote Adjustment" in output
        assert adj.action.upper() in output


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """End-to-end integration tests."""

    def test_full_workflow(self, analyzer):
        """Full workflow: trades -> metrics -> adjustment."""
        # Simulate toxic flow: 7 consecutive buys with price rising
        trades = create_trade_sequence(
            "MARKET",
            count=7,
            side="yes",
            start_price=45,
            price_increment=1
        )

        # Add trades
        analyzer.add_trades(trades)

        # Analyze flow
        metrics = analyzer.analyze_flow("MARKET")
        assert metrics is not None
        assert metrics.run_length == 7
        assert metrics.price_change == 6
        assert metrics.is_toxic

        # Get recommendation
        adj = analyzer.recommend_adjustment("MARKET")
        assert adj.action in ["widen", "pull"]
        # If widening, spread should be wider; if pulling, it's 0
        if adj.action == "widen":
            assert adj.spread_multiplier > 1.0

    def test_evolving_flow(self, analyzer):
        """Flow analysis updates as new trades arrive."""
        # Start with normal flow
        analyzer.add_trades([
            create_trade("TEST", side="yes", timestamp=datetime.now() - timedelta(seconds=3)),
            create_trade("TEST", side="no", timestamp=datetime.now() - timedelta(seconds=2)),
        ])

        adj1 = analyzer.recommend_adjustment("TEST")
        assert adj1.action == "normal"

        # Add toxic trades
        toxic_trades = create_trade_sequence("TEST", count=6, side="yes")
        analyzer.add_trades(toxic_trades)

        adj2 = analyzer.recommend_adjustment("TEST")
        assert adj2.action != "normal"
        assert adj2.toxicity_score > adj1.toxicity_score
