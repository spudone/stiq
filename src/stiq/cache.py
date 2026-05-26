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


class CacheManager:
    def __init__(self) -> None:
        self.dir: str = os.path.expanduser("~/.stiq")
        self.file: str = os.path.join(self.dir, "cache.json")
        # Structure: {"provider_name": {"SYMBOL": { ...dict_data... }}}
        self.data: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as f:
                    content = json.load(f)
                    if not content:
                        return
                        
                    # Detect old structure which was flat {"AAPL": {"date": ..., "history": [...]}}
                    first_val = list(content.values())[0]
                    if isinstance(first_val, dict) and "history" in first_val and "date" in first_val:
                        # Migrate old cache to "yahoo" namespace
                        self.data = {"yahoo": content}
                    else:
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

    def get_history(self, provider: str, sym: str) -> dict | None:
        provider_cache = self.data.get(provider, {})
        return provider_cache.get(sym.upper())

    def set_history(self, provider: str, sym: str, data: dict) -> None:
        if provider not in self.data:
            self.data[provider] = {}
        self.data[provider][sym.upper()] = data
        self.save()


# Shared global cache instance
cache = CacheManager()
