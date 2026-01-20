"""
Configuration Loading for Avellaneda-Stoikov Market Maker

Loads YAML config with environment variable expansion.
"""

import os
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

from src.execution import ExecutionConfig, MarketConfig


class ConfigValidationError(Exception):
    """Raised when configuration is invalid."""
    pass


class ConfigLoader:
    """Load and validate configuration from YAML files."""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)

    def load(self, environment: str = "demo") -> Dict[str, Any]:
        """Load configuration for specified environment."""
        config_file = self.config_dir / f"{environment}.yaml"

        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        config = self._expand_env_vars(config)
        self._validate_config(config)
        return config

    def _expand_env_vars(self, config: Any) -> Any:
        """Expand ${VAR_NAME} environment variables."""
        if isinstance(config, dict):
            return {k: self._expand_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._expand_env_vars(item) for item in config]
        elif isinstance(config, str):
            if config.startswith("${") and config.endswith("}"):
                var_name = config[2:-1]
                value = os.getenv(var_name)
                if value is None:
                    raise ConfigValidationError(f"Environment variable not set: {var_name}")
                return value
            return config
        return config

    def _validate_config(self, config: Dict[str, Any]):
        """Validate configuration structure."""
        required = ['execution', 'markets', 'api']
        for key in required:
            if key not in config:
                raise ConfigValidationError(f"Missing required key: {key}")

        # Validate markets
        if not isinstance(config['markets'], list) or len(config['markets']) == 0:
            raise ConfigValidationError("At least one market must be configured")

        for market in config['markets']:
            if 'ticker' not in market:
                raise ConfigValidationError("Market missing ticker")

        # Validate API
        api = config['api']
        for field in ['key_id', 'private_key_file', 'host']:
            if field not in api:
                raise ConfigValidationError(f"Missing API field: {field}")

    def to_execution_config(self, config: Dict[str, Any]) -> ExecutionConfig:
        """Convert config dict to ExecutionConfig."""
        exec_config = config['execution']
        markets = {}

        for market in config['markets']:
            ticker = market['ticker']
            markets[ticker] = MarketConfig(
                ticker=ticker,
                enabled=market.get('enabled', True),
                gamma=market.get('gamma', 0.1),
                sigma=market.get('sigma', 2.0),
                k=market.get('k', 1.5),
                base_size=market.get('base_size', 10),
                max_position=market.get('max_position', 100),
                max_loss_cents=market.get('max_loss_cents', 500.0)
            )

        return ExecutionConfig(
            quote_interval=exec_config.get('quote_interval', 1.0),
            position_sync_interval=exec_config.get('position_sync_interval', 5.0),
            total_max_position=exec_config.get('total_max_position', 500),
            cancel_threshold=exec_config.get('cancel_threshold', 1),
            markets=markets,
            dry_run=exec_config.get('dry_run', True)
        )


def load_config(environment: str = "demo") -> ExecutionConfig:
    """Convenience function to load config."""
    loader = ConfigLoader()
    config_dict = loader.load(environment)
    return loader.to_execution_config(config_dict)
