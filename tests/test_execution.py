"""
Tests for execution engine.
"""

import pytest
from unittest.mock import Mock

from src.execution import (
    MarketConfig,
    ExecutionConfig,
    ExecutionEngine,
    OrderState,
    create_config
)
from src.quotes import Position


@pytest.fixture
def mock_client():
    """Create a mock Kalshi client."""
    client = Mock()
    client.get_positions = Mock(return_value=[])
    client.get_orderbook = Mock(return_value={
        'yes': [[48, 100]],
        'no': [[52, 100]]
    })
    client.place_order = Mock(return_value={'order_id': 'test_123'})
    client.cancel_order = Mock(return_value=True)
    return client


@pytest.fixture
def simple_config():
    """Create a simple execution config."""
    return ExecutionConfig(
        quote_interval=0.1,
        position_sync_interval=1.0,
        dry_run=True,
        markets={
            'TEST': MarketConfig(
                ticker='TEST',
                enabled=True,
                gamma=0.1,
                sigma=2.0,
                k=1.5,
                base_size=10,
                max_position=100
            )
        }
    )


@pytest.fixture
def engine(mock_client, simple_config):
    """Create execution engine with mocks."""
    return ExecutionEngine(mock_client, simple_config)


class TestMarketConfig:
    """Test MarketConfig."""

    def test_default_values(self):
        """Test default market config values."""
        config = MarketConfig(ticker="TEST")
        assert config.ticker == "TEST"
        assert config.enabled is True
        assert config.gamma == 0.1
        assert config.sigma == 2.0
        assert config.k == 1.5
        assert config.base_size == 10
        assert config.max_position == 100

    def test_custom_values(self):
        """Test custom market config values."""
        config = MarketConfig(
            ticker="CUSTOM",
            gamma=0.2,
            sigma=3.0,
            k=2.0,
            base_size=20,
            max_position=200
        )
        assert config.gamma == 0.2
        assert config.sigma == 3.0
        assert config.k == 2.0


class TestExecutionConfig:
    """Test ExecutionConfig."""

    def test_default_values(self):
        """Test default execution config values."""
        config = ExecutionConfig()
        assert config.quote_interval == 1.0
        assert config.position_sync_interval == 5.0
        assert config.total_max_position == 500
        assert config.dry_run is True

    def test_with_markets(self):
        """Test config with markets."""
        markets = {
            'A': MarketConfig(ticker='A'),
            'B': MarketConfig(ticker='B')
        }
        config = ExecutionConfig(markets=markets)
        assert len(config.markets) == 2


class TestOrderState:
    """Test OrderState."""

    def test_initial_state(self):
        """Test initial order state."""
        state = OrderState(ticker="TEST")
        assert state.ticker == "TEST"
        assert state.yes_order_id is None
        assert state.no_order_id is None
        assert state.last_quote is None


class TestExecutionEngine:
    """Test ExecutionEngine."""

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine.running is False
        assert engine.config.dry_run is True
        assert len(engine.orders) == 0

    def test_tick_fetches_orderbook(self, engine, mock_client):
        """Test that tick fetches orderbook."""
        engine._tick()
        mock_client.get_orderbook.assert_called()

    def test_dry_run_no_orders(self, engine, mock_client):
        """Test dry run doesn't place real orders."""
        engine._tick()
        # In dry run, place_order should not be called
        mock_client.place_order.assert_not_called()

    def test_position_sync(self, engine, mock_client):
        """Test position syncing."""
        mock_client.get_positions.return_value = [
            {'ticker': 'TEST', 'position': 50}
        ]
        engine._sync_positions()

        pos = engine.positions.get_position('TEST')
        assert pos.quantity == 50

    def test_position_limit_check(self, engine):
        """Test position limit enforcement."""
        engine.positions.update_position('A', delta=300)
        engine.positions.update_position('B', delta=300)
        # Total = 600, limit = 500
        assert engine.positions.get_total_exposure() > engine.config.total_max_position


class TestCreateConfig:
    """Test create_config helper."""

    def test_create_with_defaults(self):
        """Test creating config with defaults."""
        config = create_config(['TICKER1', 'TICKER2'])
        assert len(config.markets) == 2
        assert 'TICKER1' in config.markets
        assert 'TICKER2' in config.markets
        assert config.dry_run is True

    def test_create_with_custom_params(self):
        """Test creating config with custom params."""
        config = create_config(
            ['TEST'],
            dry_run=False,
            gamma=0.2,
            sigma=3.0,
            base_size=20
        )
        assert config.dry_run is False
        assert config.markets['TEST'].gamma == 0.2
        assert config.markets['TEST'].sigma == 3.0
        assert config.markets['TEST'].base_size == 20
