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

import asyncio
import json
import os
from datetime import datetime

import pytz

from .events import EventBus

_USAGE_DIR = os.path.expanduser("~/.stiq")
_USAGE_FILE = os.path.join(_USAGE_DIR, "usage.json")


class TiingoUsageTracker:
    def __init__(self, event_bus: EventBus):
        self.tz = pytz.timezone("US/Eastern")
        self.lock = asyncio.Lock()
        self.event_bus = event_bus
        self._load()

    def _load(self):
        data = {}
        if os.path.exists(_USAGE_FILE):
            try:
                with open(_USAGE_FILE) as f:
                    data = json.load(f)
            except Exception:
                pass

        self.hourly_requests = data.get("hourly_requests", 0)
        self.daily_requests = data.get("daily_requests", 0)
        self.monthly_bandwidth_bytes = data.get("monthly_bandwidth_bytes", 0)

        # Timestamps of last known resets
        now = datetime.now(self.tz)
        self.last_reset_hour = data.get("last_reset_hour", now.strftime("%Y-%m-%d %H"))
        self.last_reset_day = data.get("last_reset_day", now.strftime("%Y-%m-%d"))
        self.last_reset_month = data.get("last_reset_month", now.strftime("%Y-%m"))

        # Check if we need to reset immediately
        self._check_resets()

    def _check_resets(self) -> bool:
        """
        Check if any time boundaries have been crossed and reset counters if so.
        Returns True if a reset occurred.
        """
        now = datetime.now(self.tz)
        current_hour = now.strftime("%Y-%m-%d %H")
        current_day = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%Y-%m")

        changed = False

        if current_hour != self.last_reset_hour:
            self.hourly_requests = 0
            self.last_reset_hour = current_hour
            changed = True

        if current_day != self.last_reset_day:
            self.daily_requests = 0
            self.last_reset_day = current_day
            changed = True

        if current_month != self.last_reset_month:
            self.monthly_bandwidth_bytes = 0
            self.last_reset_month = current_month
            changed = True

        return changed

    async def track_request(self, req_bytes: int, resp_bytes: int):
        async with self.lock:
            self._check_resets()
            self.hourly_requests += 1
            self.daily_requests += 1
            self.monthly_bandwidth_bytes += req_bytes + resp_bytes
            self._save_to_disk()

    async def track_ws_bytes(self, size_bytes: int):
        async with self.lock:
            self._check_resets()
            self.monthly_bandwidth_bytes += size_bytes

    def get_usage_dict(self) -> dict:
        self._check_resets()
        mb = self.monthly_bandwidth_bytes / (1024 * 1024)
        return {
            "hourly_requests": self.hourly_requests,
            "daily_requests": self.daily_requests,
            "monthly_bandwidth_mb": mb,
        }

    def _save_to_disk(self):
        """Write current usage state to ~/.stiq/usage.json."""
        data = {
            "hourly_requests": self.hourly_requests,
            "daily_requests": self.daily_requests,
            "monthly_bandwidth_bytes": self.monthly_bandwidth_bytes,
            "last_reset_hour": self.last_reset_hour,
            "last_reset_day": self.last_reset_day,
            "last_reset_month": self.last_reset_month,
        }
        try:
            os.makedirs(_USAGE_DIR, exist_ok=True)
            with open(_USAGE_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def save(self):
        """Public save method for shutdown hooks."""
        self._check_resets()
        self._save_to_disk()

    async def periodic_save(self, interval: int = 60):
        """Periodically persist bandwidth data and publish usage via SSE."""
        while True:
            await asyncio.sleep(interval)
            async with self.lock:
                self._save_to_disk()
            self.event_bus.publish("tiingo_usage", self.get_usage_dict())
