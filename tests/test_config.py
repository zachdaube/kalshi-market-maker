"""
Tests for configuration loading and validation.
"""

import pytest
import os
import tempfile
from pathlib import Path

from src.config_loader import (
    ConfigLoader,
    ConfigValidationError,
    load_config
)
from src.execution import ExecutionConfig, MarketConfig


@pytest.fixture
def valid_config_dict():
    """Valid configuration dictionary."""
    return {
        'environment': 'test',
        'execution': {
            'quote_interval': 1.0,
            'position_sync_interval': 5.0,
            'total_max_position': 500,
            'dry_run': True
        },
        'markets': [
            {
                'ticker': 'TEST1',
                'enabled': True,
                'gamma': 0.1,
                'sigma': 2.0,
                'k': 1.5,
                'base_size': 10,
                'max_position': 100
            }
        ],
        'api': {
            'key_id': 'test-key',
            'private_key_file': 'kalshidemo.txt',
            'host': 'https://demo-api.kalshi.co/trade-api/v2'
        }
    }


class TestConfigValidation:
    """Test configuration validation."""

    def test_valid_config(self, valid_config_dict):
        """Test that valid config passes validation."""
        loader = ConfigLoader()
        loader._validate_config(valid_config_dict)

    def test_missing_required_key(self, valid_config_dict):
        """Test that missing required key raises error."""
        del valid_config_dict['execution']
        loader = ConfigLoader()
        with pytest.raises(ConfigValidationError):
            loader._validate_config(valid_config_dict)

    def test_missing_markets(self, valid_config_dict):
        """Test that empty markets raises error."""
        valid_config_dict['markets'] = []
        loader = ConfigLoader()
        with pytest.raises(ConfigValidationError):
            loader._validate_config(valid_config_dict)

    def test_market_missing_ticker(self, valid_config_dict):
        """Test that market without ticker raises error."""
        valid_config_dict['markets'] = [{'enabled': True}]
        loader = ConfigLoader()
        with pytest.raises(ConfigValidationError):
            loader._validate_config(valid_config_dict)


class TestEnvVarExpansion:
    """Test environment variable expansion."""

    def test_expand_env_var(self):
        """Test environment variable expansion."""
        os.environ['TEST_VAR'] = 'test_value'
        loader = ConfigLoader()
        result = loader._expand_env_vars({'key': '${TEST_VAR}'})
        assert result['key'] == 'test_value'
        del os.environ['TEST_VAR']

    def test_missing_env_var_raises(self):
        """Test that missing env var raises error."""
        loader = ConfigLoader()
        with pytest.raises(ConfigValidationError):
            loader._expand_env_vars({'key': '${NONEXISTENT_VAR}'})

    def test_expand_nested(self):
        """Test nested env var expansion."""
        os.environ['TEST_VAR'] = 'value'
        loader = ConfigLoader()
        result = loader._expand_env_vars({
            'level1': {
                'level2': '${TEST_VAR}'
            }
        })
        assert result['level1']['level2'] == 'value'
        del os.environ['TEST_VAR']


class TestConfigConversion:
    """Test conversion to ExecutionConfig."""

    def test_to_execution_config(self, valid_config_dict):
        """Test converting dict to ExecutionConfig."""
        loader = ConfigLoader()
        config = loader.to_execution_config(valid_config_dict)

        assert isinstance(config, ExecutionConfig)
        assert config.quote_interval == 1.0
        assert config.dry_run is True
        assert 'TEST1' in config.markets

    def test_market_conversion(self, valid_config_dict):
        """Test market config conversion."""
        loader = ConfigLoader()
        config = loader.to_execution_config(valid_config_dict)

        market = config.markets['TEST1']
        assert market.ticker == 'TEST1'
        assert market.gamma == 0.1
        assert market.sigma == 2.0
        assert market.k == 1.5
        assert market.base_size == 10

    def test_default_values(self, valid_config_dict):
        """Test that missing values get defaults."""
        # Remove optional AS params
        valid_config_dict['markets'][0] = {'ticker': 'TEST2'}
        loader = ConfigLoader()
        config = loader.to_execution_config(valid_config_dict)

        market = config.markets['TEST2']
        assert market.gamma == 0.1  # default
        assert market.sigma == 2.0  # default
        assert market.k == 1.5      # default
