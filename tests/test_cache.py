"""
Stiq - Stock Ticker
Copyright (C) 2026 spudone

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import json
import os
from unittest.mock import patch

import pytest

from stiq.cache import CacheManager


@pytest.fixture
def temp_cache_dir(tmp_path):
    with patch("os.path.expanduser", return_value=str(tmp_path)):
        yield tmp_path


def test_cache_initialization_and_empty(temp_cache_dir):
    cache = CacheManager()
    assert cache.data == {}
    assert cache.get_history("AAPL") is None


def test_cache_load_existing(temp_cache_dir):
    data = {"AAPL": {"history": [100.0, 101.0], "pe_ratio": 25.0}}
    cache_file = os.path.join(temp_cache_dir, "cache.json")
    with open(cache_file, "w") as f:
        json.dump(data, f)

    cache = CacheManager()
    assert cache.get_history("AAPL") == {"history": [100.0, 101.0], "pe_ratio": 25.0}


def test_set_history_merging(temp_cache_dir):
    cache = CacheManager()

    # Initial set
    initial_data = {
        "history": [100.0, 101.0],
        "pe_ratio": 25.0,
        "raw_prices": [{"close": 100.0}, {"close": 101.0}],
    }
    cache.set_history("AAPL", initial_data)

    assert cache.get_history("AAPL") == initial_data

    # Overwrite with partial data (e.g. Yahoo overwrite which doesn't have raw_prices)
    new_data = {
        "history": [102.0, 103.0],
        "pe_ratio": 26.0,
        "raw_prices": [],  # Should not overwrite existing non-empty lists
    }
    cache.set_history("AAPL", new_data)

    merged = cache.get_history("AAPL")
    assert merged["history"] == [102.0, 103.0]  # History overwritten
    assert merged["pe_ratio"] == 26.0
    assert merged["raw_prices"] == [
        {"close": 100.0},
        {"close": 101.0},
    ]  # Kept original list

    # Null values shouldn't overwrite existing
    null_data = {"pe_ratio": None}
    cache.set_history("AAPL", null_data)
    assert cache.get_history("AAPL")["pe_ratio"] == 26.0

    # Saving is verified since it happens implicitly
    with open(cache.file) as f:
        saved_data = json.load(f)
        assert saved_data["AAPL"]["pe_ratio"] == 26.0
