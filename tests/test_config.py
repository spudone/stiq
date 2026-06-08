import pytest
import os
import json
from unittest.mock import patch

from stiq.config import ConfigManager


@pytest.fixture
def temp_config_dir(tmp_path):
    # Mock expanduser to return our temp_path for testing
    with patch("os.path.expanduser", return_value=str(tmp_path)):
        yield tmp_path


def test_config_initialization_and_defaults(temp_config_dir):
    config = ConfigManager()

    # Check default values
    assert config.watchlist == []
    assert config.poll_interval_secs == 300
    assert config.market_provider == "yahoo"
    assert config.quotes_provider == "yahoo"
    assert config.history_provider == "yahoo"
    assert config.use_rate_limit is True

    # File should be created on initialization if missing
    assert os.path.exists(config.file)


def test_config_load_existing(temp_config_dir):
    # Pre-populate a config file
    data = {
        "watchlist": ["AAPL", "msft"],
        "poll_interval_secs": 120,
        "market_provider": "yfinance",
        "quotes_provider": "tiingo",
        "history_provider": "yfinance",
        "use_rate_limit": False,
    }
    config_file = os.path.join(temp_config_dir, "config.json")
    with open(config_file, "w") as f:
        json.dump(data, f)

    config = ConfigManager()

    assert config.watchlist == ["AAPL", "MSFT"]  # should upper case
    assert config.poll_interval_secs == 120
    assert config.market_provider == "yfinance"
    assert config.quotes_provider == "tiingo"
    assert config.history_provider == "yfinance"
    assert config.use_rate_limit is False


def test_add_symbol(temp_config_dir):
    config = ConfigManager()

    assert config.add_symbol("aapl") is True
    assert config.watchlist == ["AAPL"]

    # Adding duplicate should return False and not add
    assert config.add_symbol("AAPL") is False
    assert config.add_symbol("aapl") is False
    assert config.watchlist == ["AAPL"]

    # Verify save was called
    with open(config.file, "r") as f:
        data = json.load(f)
        assert data["watchlist"] == ["AAPL"]


def test_remove_symbol(temp_config_dir):
    config = ConfigManager()
    config.add_symbol("AAPL")
    config.add_symbol("MSFT")

    assert config.remove_symbol("msft") is True
    assert config.watchlist == ["AAPL"]

    # Removing non-existent should return False
    assert config.remove_symbol("TSLA") is False
    assert config.watchlist == ["AAPL"]


def test_set_interval(temp_config_dir):
    config = ConfigManager()

    config.set_interval(600)
    assert config.poll_interval_secs == 600

    # Should enforce minimum 60
    config.set_interval(30)
    assert config.poll_interval_secs == 60

    config.set_interval(0)
    assert config.poll_interval_secs == 60
