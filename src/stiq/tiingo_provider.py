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
import sys
from typing import Any

from .provider import DataProvider
from .builder import builder
from .async_tiingo import AsyncTiingoClient


class TiingoWebSocketProvider(DataProvider):
    """DataProvider implementation using Tiingo IEX + FX API."""

    def __init__(self) -> None:
        self._api_key: str = os.environ.get("TIINGO_API_KEY", "")
        if not self._api_key:
            print("[tiingo-ws] WARNING: TIINGO_API_KEY not set", file=sys.stderr)

        self.client = AsyncTiingoClient(
            config={"api_key": self._api_key, "on_quote": self._handle_tiingo_quote}
        )

        self._iex_cache: dict[str, dict[str, Any]] = {}
        self._quotes_cache: dict[str, dict] = {}
        self._history_cache: dict[str, dict] = {}
        self._history_requested: set[str] = set()

        self._started = False

    def _handle_tiingo_quote(self, quote_data: dict[str, Any]) -> None:
        """Callback from AsyncTiingoClient when a valid realtime quote arrives."""
        ticker = quote_data["ticker"]
        normalized = builder.build_realtime_quote(
            sym=ticker,
            price=quote_data["price"],
            prev_close=quote_data["prev_close"],
            open=quote_data["open"],
            high=quote_data["high"],
            low=quote_data["low"],
            volume=quote_data["volume"],
        )
        self._iex_cache[ticker] = normalized
        self._quotes_cache[ticker] = normalized

        from .events import event_bus

        publish_data = dict(normalized)
        publish_data["quote"] = ticker
        event_bus.publish("quote", publish_data)

    async def _ensure_started(self) -> None:
        """Starts connection tasks on the active asyncio loop when first accessed."""
        if not self._started:
            self._started = True
            if self._api_key:
                await self._seed_initial_data()
                loop = asyncio.get_running_loop()
                loop.create_task(self.client.connect_iex())

    def _get_iex_tickers(self) -> list[str]:
        """Collect all equity tickers we need from the IEX feed."""
        tickers: set[str] = set()
        try:
            from .config import config

            for sym in config.watchlist:
                tickers.add(sym.upper())
        except Exception:
            pass
        return sorted(tickers)

    async def _seed_initial_data(self) -> None:
        """Seed initial values using the REST API for closed market or immediate display."""
        cache_file = os.path.expanduser("~/.stiq/tiingo_cache.json")

        if builder.is_market_open():
            if os.path.exists(cache_file):
                try:
                    os.remove(cache_file)
                except Exception:
                    pass
            return

        try:
            if os.path.exists(cache_file):
                with open(cache_file, "r") as f:
                    data = json.load(f)
                    self._iex_cache = data.get("iex", {})
                return
        except Exception as e:
            print(f"[tiingo-ws] Error loading cache: {e}", file=sys.stderr)

        try:
            iex_tickers = self._get_iex_tickers()
            if iex_tickers:
                data_iex = await self.client.get_iex_quotes(iex_tickers)
                for r in data_iex:
                    ticker = r.get("ticker", "").upper()
                    price = float(r.get("tngoLast") or 0.0)
                    prev_close = float(r.get("prevClose") or 0.0)
                    open_price = float(r.get("open") or 0.0)
                    high = float(r.get("high") or 0.0)
                    low = float(r.get("low") or 0.0)
                    volume = float(r.get("volume") or 0.0)

                    normalized = builder.build_realtime_quote(
                        sym=ticker,
                        price=price,
                        prev_close=prev_close,
                        open=open_price,
                        high=high,
                        low=low,
                        volume=volume,
                    )
                    if ticker not in self._iex_cache:
                        self._iex_cache[ticker] = normalized

            try:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump({"iex": self._iex_cache}, f, indent=4)
            except Exception as e:
                print(f"[tiingo-ws] Error saving cache: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[tiingo-ws] Error seeding initial data: {e}", file=sys.stderr)

    async def fetch_market(self) -> dict[str, any]:
        # No-op since Tiingo doesn't supply indices
        return {"indices": [], "is_open": builder.is_market_open()}

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        await self._ensure_started()

        # Determine the full desired list (watchlist + adhoc symbols)
        desired_set = set(t.upper() for t in self._get_iex_tickers() + symbols)
        await self.client.subscribe_iex(list(desired_set))

        # Gracefully handle missing cache (e.g., weekends, holidays, newly added symbols)
        missing = [
            s.upper()
            for s in symbols
            if s.upper() not in self._quotes_cache and s.upper() not in self._iex_cache
        ]
        if missing:
            try:
                data_iex = await self.client.get_iex_quotes(missing)
                for r in data_iex:
                    ticker = r.get("ticker", "").upper()
                    normalized = builder.build_realtime_quote(
                        sym=ticker,
                        price=float(r.get("tngoLast") or 0.0),
                        prev_close=float(r.get("prevClose") or 0.0),
                        open=float(r.get("open") or 0.0),
                        high=float(r.get("high") or 0.0),
                        low=float(r.get("low") or 0.0),
                        volume=float(r.get("volume") or 0.0),
                    )
                    self._iex_cache[ticker] = normalized
            except Exception as e:
                import sys

                print(
                    f"[tiingo-ws] Error fetching missing quotes via REST: {e}",
                    file=sys.stderr,
                )

        results = {}
        for sym in symbols:
            sym_upper = sym.upper()
            if sym_upper in self._quotes_cache:
                results[sym_upper] = self._quotes_cache[sym_upper]
            elif sym_upper in self._iex_cache:
                results[sym_upper] = self._iex_cache[sym_upper]
            else:
                row = builder.build_realtime_quote(sym_upper)
                self._quotes_cache[sym_upper] = row
                results[sym_upper] = row

        return results

    async def _update_history_cache(self, ticker: str) -> None:
        """Background task to fetch history and update the history cache."""
        try:
            history_data = await self.client.get_history(ticker)

            if history_data:
                quote = builder.build_history_quote(
                    sym=ticker,
                    low_52w=history_data.get("low_52w"),
                    high_52w=history_data.get("high_52w"),
                    avg_volume=history_data.get("avg_volume"),
                    pe_ratio=history_data.get("pe_ratio"),
                    dividend_rate=history_data.get("dividend_rate"),
                    dividend_yield=history_data.get("dividend_yield"),
                    market_cap=history_data.get("market_cap"),
                    currency="USD",
                    history=history_data.get("history", []),
                )
                self._history_cache[ticker] = quote
        finally:
            if ticker in self._history_requested:
                self._history_requested.remove(ticker)

    async def fetch_history(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        await self._ensure_started()

        results = {}
        from datetime import date

        today_str = date.today().isoformat()

        for sym in symbols:
            sym_upper = sym.upper()

            history_data = self.client.get_cached_history(sym_upper) or {}

            if (
                history_data.get("last_updated") != today_str
                and sym_upper not in self._history_requested
            ):
                self._history_requested.add(sym_upper)
                asyncio.create_task(self._update_history_cache(sym_upper))

            if sym_upper in self._history_cache:
                results[sym_upper] = self._history_cache[sym_upper]
            else:
                hist_row = builder.build_history_quote(
                    sym=sym_upper,
                    low_52w=history_data.get("low_52w"),
                    high_52w=history_data.get("high_52w"),
                    avg_volume=history_data.get("avg_volume"),
                    pe_ratio=history_data.get("pe_ratio"),
                    dividend_rate=history_data.get("dividend_rate"),
                    dividend_yield=history_data.get("dividend_yield"),
                    market_cap=history_data.get("market_cap"),
                    currency="USD",
                    history=history_data.get("history", []),
                )
                self._history_cache[sym_upper] = hist_row
                results[sym_upper] = hist_row

        return results
