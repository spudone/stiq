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

import os
import json


# Unified schema shared by all providers
UNIFIED_HISTORY_FIELDS = {
    "history": [],  # Array of closing prices (all providers)
    "last_updated": "",  # ISO date string (ALL PROVIDERS NOW WRITE THIS!)
    # Yahoo-specific fields
    "low_52w": None,
    "high_52w": None,
    "avg_volume": None,
    "market_cap": None,
    # Tiingo-specific fields
    "raw_prices": [],  # Detailed daily OHLCV data (Tiingo only)
    # Other metrics
    "pe_ratio": None,
    "dividend_rate": None,
    "dividend_yield": None,
    "currency": "USD",
}


class CacheManager:
    def __init__(self) -> None:
        self.dir: str = os.path.expanduser("~/.stiq")
        self.file: str = os.path.join(self.dir, "cache.json")
        # Structure: {"SYMBOL": { ...unified_data... }}
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as f:
                    content = json.load(f)
                    if not content:
                        return

                    # Already flat {SYMBOL: {...}} – just ensure defaults are present
                    self.data = content
            except Exception:
                pass

    def save(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.file, "w") as f:
                json.dump(self.data, f)
        except Exception:
            pass

    def get_history(self, sym: str) -> dict | None:
        """Return the unified history data for a symbol (no provider argument)."""
        return self.data.get(sym.upper())

    def set_history(self, sym: str, data: dict) -> None:
        """Store history data with smart merge – prefer non-empty values."""
        existing = self.data.get(sym.upper(), {})

        merged = {**existing}
        for key, value in data.items():
            if isinstance(value, list):
                # Empty lists don't overwrite; Tiingo's raw_prices survives Yahoo writes
                merged[key] = value if value else existing.get(key, [])
            elif value is not None:
                merged[key] = value

        self.data[sym.upper()] = merged
        self.save()


# Shared global cache instance
cache = CacheManager()
