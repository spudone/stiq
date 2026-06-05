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

import aiohttp
import asyncio
import json
import os
import sys
import urllib.parse
import websockets
from datetime import datetime, timedelta, date
from typing import Any, Callable

from .cache import cache
from .tiingo_usage import tiingo_usage_tracker

# IEX data array field positions (thresholdLevel 5)
_IEX_TICKER = 1
_IEX_TNGOLAST = 3
_IEX_PREVCLOSE = 4
_IEX_OPEN = 5
_IEX_HIGH = 6
_IEX_LOW = 7
_IEX_VOLUME = 8


def _safe_float(val, default=0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class AsyncTiingoClient:
    """
    An asynchronous subset of tiingo-python using aiohttp and websockets.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.api_key = self.config.get("api_key", "")
        self.base_url = "https://api.tiingo.com"
        self.on_quote = self.config.get("on_quote")

        self._iex_ws = None
        self._iex_sub_id = None
        self._current_iex_tickers: set[str] = set()

        self._request_lock = asyncio.Lock()
        self._last_request_time = 0.0

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Token {self.api_key}",
        }

    async def _request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> Any:
        url = urllib.parse.urljoin(self.base_url, endpoint)
        if params is None:
            params = {}

        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                # Track request usage
                req_bytes = len(url) + sum(len(k) + len(v) for k, v in response.request_info.headers.items())
                body_bytes = await response.read()
                await tiingo_usage_tracker.track_request(req_bytes, len(body_bytes))
                return json.loads(body_bytes)

    async def get_iex_quotes(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Fetch latest IEX quotes for a list of tickers via REST."""
        if not tickers:
            return []
        params = {"tickers": ",".join(tickers)}
        return await self._request("/iex/", params=params)

    async def get_ticker_price(
        self, ticker: str, startDate: str | None = None, endDate: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch daily historical prices for a ticker."""
        params = {}
        if startDate:
            params["startDate"] = startDate
        if endDate:
            params["endDate"] = endDate

        endpoint = f"/tiingo/daily/{ticker}/prices"
        return await self._request(endpoint, params=params)

    # ────────────────────────────────────────────────────────────────
    # IEX WebSocket Management
    # ────────────────────────────────────────────────────────────────

    async def connect_iex(self) -> None:
        """Connect to IEX websocket with auto-reconnect and exponential backoff."""
        backoff = 1.0
        while True:
            try:
                url = f"wss://api.tiingo.com/iex?token={self.api_key}"
                print("[tiingo-ws] IEX connecting…", file=sys.stderr)
                async with websockets.connect(
                    url, ping_interval=30, ping_timeout=10
                ) as ws:
                    self._iex_ws = ws
                    print("[tiingo-ws] IEX connected", file=sys.stderr)
                    # Resubscribe to existing tickers on reconnect
                    if self._current_iex_tickers:
                        await self._send_subscribe(list(self._current_iex_tickers))
                    async for message in ws:
                        self._on_iex_message(message)
            except Exception as e:
                print(f"[tiingo-ws] IEX connection error: {e}", file=sys.stderr)
            finally:
                if self._iex_ws:
                    close_code = getattr(self._iex_ws, "close_code", None)
                    close_reason = getattr(self._iex_ws, "close_reason", None)
                    print(
                        f"[tiingo-ws] IEX closed: {close_code} {close_reason}",
                        file=sys.stderr,
                    )
                self._iex_ws = None
                self._iex_sub_id = None

            print(f"[tiingo-ws] IEX reconnecting in {backoff:.0f}s…", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _send_subscribe(self, tickers: list[str]) -> None:
        if not self._iex_ws:
            return
        from .config import config

        msg = {
            "eventName": "subscribe",
            "authorization": self.api_key,
            "eventData": {
                "thresholdLevel": config.tiingo_threshold_level,
                "tickers": sorted(tickers),
            },
        }
        msg_str = json.dumps(msg)
        await self._iex_ws.send(msg_str)
        await tiingo_usage_tracker.track_ws_bytes(len(msg_str.encode("utf-8")))

    async def subscribe_iex(self, tickers: list[str]) -> None:
        """Dynamically update IEX subscriptions."""
        desired = set(t.upper() for t in tickers)
        if desired == self._current_iex_tickers:
            return

        ws = self._iex_ws
        if ws is None or not self._iex_sub_id:
            # Not fully connected yet. Update desired state and it will subscribe when ready.
            self._current_iex_tickers = desired
            return

        new_tickers = desired - self._current_iex_tickers
        removed_tickers = self._current_iex_tickers - desired

        try:
            if new_tickers:
                await self._send_subscribe(list(new_tickers))
                print(
                    f"[tiingo-ws] IEX added tickers: {sorted(new_tickers)}",
                    file=sys.stderr,
                )

            if removed_tickers:
                msg = {
                    "eventName": "unsubscribe",
                    "authorization": self.api_key,
                    "eventData": {
                        "tickers": sorted(removed_tickers),
                    },
                }
                msg_str = json.dumps(msg)
                await ws.send(msg_str)
                await tiingo_usage_tracker.track_ws_bytes(len(msg_str.encode("utf-8")))
                print(
                    f"[tiingo-ws] IEX removed tickers: {sorted(removed_tickers)}",
                    file=sys.stderr,
                )

            self._current_iex_tickers = desired
        except Exception as e:
            print(f"[tiingo-ws] IEX subscription update error: {e}", file=sys.stderr)

    def _on_iex_message(self, raw_msg: str | bytes) -> None:
        try:
            # We track ws bandwidth inside an async task since the track_ws_bytes method is async
            if isinstance(raw_msg, bytes):
                msg_len = len(raw_msg)
            else:
                msg_len = len(raw_msg.encode("utf-8"))
            asyncio.create_task(tiingo_usage_tracker.track_ws_bytes(msg_len))

            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("messageType")

        if msg_type == "I":
            data = msg.get("data", {})
            if isinstance(data, dict):
                self._iex_sub_id = data.get("subscriptionId")
                if self._current_iex_tickers:
                    asyncio.create_task(
                        self._send_subscribe(list(self._current_iex_tickers))
                    )
            return

        if msg_type == "H":
            return

        if msg_type == "A":
            data = msg.get("data", [])
            if not isinstance(data, list) or len(data) < 3:
                return

            if len(data) == 3:
                # Reference price (thresholdLevel 6)
                ticker = str(data[1]).upper()
                price = _safe_float(data[2])
                prev_close = 0.0
                open_price = 0.0
                high = 0.0
                low = 0.0
                volume = 0.0
            else:
                # Top-of-Book / Last Trade (thresholdLevel 0 or 5)
                # Index 0: Message Type ("T", "Q", "B")
                update_type = str(data[0]) if len(data) > 0 else ""
                if update_type in ("T", "B") and len(data) > 9:
                    ticker = str(data[3]).upper()
                    price = _safe_float(data[9])
                    prev_close = 0.0
                    open_price = 0.0
                    high = 0.0
                    low = 0.0
                    volume = _safe_float(data[10]) if len(data) > 10 else 0.0
                else:
                    return

            if price <= 0:
                return

            parsed = {
                "ticker": ticker,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "high": high,
                "low": low,
                "volume": volume,
            }

            if self.on_quote:
                self.on_quote(parsed)

    # ────────────────────────────────────────────────────────────────
    # History Management
    # ────────────────────────────────────────────────────────────────

    def get_cached_history(self, ticker: str) -> dict[str, Any] | None:
        """Returns synchronously the cached history data, bypassing API entirely."""
        return cache.get_history(ticker.upper())

    async def get_history(self, ticker: str) -> dict[str, Any]:
        """
        Get cached history or fetch rate-limited updates.
        Returns the fundamental data dictionary.
        """
        import time

        lock_acquired = False
        ticker = ticker.upper()

        try:
            if not self.api_key:
                return cache.get_history(ticker) or {}

            today_str = date.today().isoformat()
            history_data = cache.get_history(ticker) or {}
            if history_data.get("last_updated") == today_str:
                return history_data

            from .config import config

            use_rate_limit = config.use_rate_limit

            if use_rate_limit:
                await self._request_lock.acquire()
                lock_acquired = True

                # Double check
                history_data = cache.get_history(ticker) or {}
                if history_data.get("last_updated") == today_str:
                    return history_data

                now = time.time()
                time_since_last = now - self._last_request_time
                delay = float(os.environ.get("TIINGO_RATE_LIMIT_DELAY", "2.0"))
                if time_since_last < delay:
                    await asyncio.sleep(delay - time_since_last)

                self._last_request_time = time.time()

            try:
                one_year_ago_dt = datetime.now() - timedelta(days=365)
                one_year_ago = one_year_ago_dt.strftime("%Y-%m-%d")

                existing_prices = history_data.get("raw_prices", [])
                startDate = None
                if history_data.get("last_updated"):
                    try:
                        last_dt = datetime.strptime(
                            history_data["last_updated"], "%Y-%m-%d"
                        ).date()
                        start_dt = last_dt + timedelta(days=1)
                        if start_dt <= datetime.now().date():
                            startDate = start_dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass

                if not startDate:
                    startDate = (datetime.now() - timedelta(days=365)).strftime(
                        "%Y-%m-%d"
                    )

                data = await self.get_ticker_price(ticker, startDate=startDate)

                if data:
                    existing_prices = history_data.get("raw_prices", [])

                    new_dates = {item["date"].split("T")[0] for item in data}
                    merged = [
                        p
                        for p in existing_prices
                        if p["date"].split("T")[0] not in new_dates
                    ]
                    merged.extend(data)

                    merged.sort(key=lambda x: x["date"])

                    cutoff = (datetime.now() - timedelta(days=365)).date()
                    filtered = []
                    for p in merged:
                        p_date_str = p["date"].split("T")[0]
                        p_date = datetime.strptime(p_date_str, "%Y-%m-%d").date()
                        if p_date >= cutoff:
                            filtered.append(p)

                    history_data["raw_prices"] = filtered

                    data_prices = filtered
                    if data_prices:
                        is_full_history = False
                        if len(data_prices) > 0:
                            first_date_str = data_prices[0]["date"].split("T")[0]
                            first_date = datetime.strptime(first_date_str, "%Y-%m-%d").date()
                            if first_date <= (datetime.now().date() - timedelta(days=360)):
                                is_full_history = True

                        has_cached_metrics = "high_52w" in history_data and "low_52w" in history_data

                        if is_full_history or not has_cached_metrics:
                            high_52w = max(
                                (item.get("high", 0) for item in data_prices), default=None
                            )
                            low_52w = min(
                                (item.get("low", float("inf")) for item in data_prices),
                                default=None,
                            )
                            if low_52w == float("inf"): low_52w = None

                            div_rate = sum(item.get("divCash", 0) for item in data_prices)

                            vol_days = (
                                data_prices[-10:] if len(data_prices) >= 10 else data_prices
                            )
                            avg_vol = (
                                sum(item.get("volume", 0) for item in vol_days)
                                / len(vol_days)
                                if vol_days
                                else None
                            )

                            history_days = (
                                data_prices[-30:] if len(data_prices) >= 30 else data_prices
                            )
                            history = [item.get("close", 0) for item in history_days]
                        else:
                            new_high = max((item.get("high", 0) for item in data), default=0)
                            cached_high = history_data.get("high_52w") or 0
                            high_52w = max(cached_high, new_high) if cached_high else new_high

                            new_low = min((item.get("low", float("inf")) for item in data), default=float("inf"))
                            cached_low = history_data.get("low_52w")
                            if cached_low is None:
                                cached_low = float("inf")
                            low_52w = min(cached_low, new_low)
                            if low_52w == float("inf"): low_52w = None

                            cached_div = history_data.get("dividend_rate") or 0
                            new_divs = sum(item.get("divCash", 0) for item in data)
                            div_rate = cached_div + new_divs

                            N = len(data)
                            cached_vol = history_data.get("avg_volume") or 0
                            if N >= 10:
                                vol_days = data[-10:]
                                avg_vol = sum(item.get("volume", 0) for item in vol_days) / 10.0
                            elif N > 0 and cached_vol:
                                avg_vol = ((10 - N) * cached_vol + sum(item.get("volume", 0) for item in data)) / 10.0
                            else:
                                avg_vol = cached_vol

                            cached_history = history_data.get("history") or []
                            new_closes = [item.get("close", 0) for item in data]
                            history = (cached_history + new_closes)[-30:]

                        if high_52w:
                            history_data["high_52w"] = high_52w
                        if low_52w:
                            history_data["low_52w"] = low_52w
                        if div_rate > 0:
                            history_data["dividend_rate"] = div_rate
                        if avg_vol:
                            history_data["avg_volume"] = avg_vol
                        history_data["history"] = history

                        latest_close = data_prices[-1].get("close")
                        if latest_close and div_rate > 0:
                            history_data["dividend_yield"] = div_rate / latest_close
                        else:
                            history_data["dividend_yield"] = None

                        # These can't be derived from prices alone; store as None so
                        # Yahoo/yfinance can later fill them in via smart merge.
                        if "market_cap" not in history_data:
                            history_data.setdefault("market_cap", None)
                        if "pe_ratio" not in history_data:
                            history_data.setdefault("pe_ratio", None)
            except Exception as e:
                print(
                    f"[tiingo-ws] Error fetching historical prices for {ticker}: {e}",
                    file=sys.stderr,
                )
                return history_data

            history_data["last_updated"] = today_str
            cache.set_history(ticker, history_data)

            return history_data
        finally:
            if lock_acquired:
                self._request_lock.release()
