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

# IEX data array field positions (thresholdLevel 5)
_IEX_TICKER    = 1
_IEX_TNGOLAST  = 3
_IEX_PREVCLOSE = 4
_IEX_OPEN      = 5
_IEX_HIGH      = 6
_IEX_LOW       = 7
_IEX_VOLUME    = 8

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
            "Authorization": f"Token {self.api_key}"
        }

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        url = urllib.parse.urljoin(self.base_url, endpoint)
        if params is None:
            params = {}
        
        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

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
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
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
                    print(f"[tiingo-ws] IEX closed: {close_code} {close_reason}", file=sys.stderr)
                self._iex_ws = None
                self._iex_sub_id = None

            print(f"[tiingo-ws] IEX reconnecting in {backoff:.0f}s…", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _send_subscribe(self, tickers: list[str]) -> None:
        if not self._iex_ws:
            return
        msg = {
            "eventName": "subscribe",
            "authorization": self.api_key,
            "eventData": {
                "tickers": sorted(tickers),
            },
        }
        await self._iex_ws.send(json.dumps(msg))

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
                print(f"[tiingo-ws] IEX added tickers: {sorted(new_tickers)}", file=sys.stderr)

            if removed_tickers:
                msg = {
                    "eventName": "unsubscribe",
                    "authorization": self.api_key,
                    "eventData": {
                        "tickers": sorted(removed_tickers),
                    },
                }
                await ws.send(json.dumps(msg))
                print(f"[tiingo-ws] IEX removed tickers: {sorted(removed_tickers)}", file=sys.stderr)

            self._current_iex_tickers = desired
        except Exception as e:
            print(f"[tiingo-ws] IEX subscription update error: {e}", file=sys.stderr)

    def _on_iex_message(self, raw_msg: str | bytes) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("messageType")

        if msg_type == "I":
            data = msg.get("data", {})
            if isinstance(data, dict):
                self._iex_sub_id = data.get("subscriptionId")
                if self._current_iex_tickers:
                    asyncio.create_task(self._send_subscribe(list(self._current_iex_tickers)))
            return

        if msg_type == "H":
            return

        if msg_type == "A":
            data = msg.get("data", [])
            if not isinstance(data, list) or len(data) < 5:
                return

            ticker = str(data[_IEX_TICKER]).upper()
            price = _safe_float(data[_IEX_TNGOLAST])
            prev_close = _safe_float(data[_IEX_PREVCLOSE]) if len(data) > _IEX_PREVCLOSE else 0.0
            open_price = _safe_float(data[_IEX_OPEN]) if len(data) > _IEX_OPEN else 0.0
            high = _safe_float(data[_IEX_HIGH]) if len(data) > _IEX_HIGH else 0.0
            low = _safe_float(data[_IEX_LOW]) if len(data) > _IEX_LOW else 0.0
            volume = _safe_float(data[_IEX_VOLUME]) if len(data) > _IEX_VOLUME else 0.0

            if price <= 0:
                return

            parsed = {
                "ticker": ticker,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "high": high,
                "low": low,
                "volume": volume
            }

            if self.on_quote:
                self.on_quote(parsed)

    # ────────────────────────────────────────────────────────────────
    # Historical / Fundamentals Management
    # ────────────────────────────────────────────────────────────────

    def get_cached_history(self, ticker: str) -> dict[str, Any] | None:
        """Returns synchronously the cached history data, bypassing API entirely."""
        return cache.get_history("tiingo", ticker.upper())

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
                return cache.get_history("tiingo", ticker) or {}

            today_str = date.today().isoformat()
            fund = cache.get_history("tiingo", ticker) or {}
            if fund.get("last_updated") == today_str:
                return fund

            from .config import config
            use_rate_limit = config.use_rate_limit

            if use_rate_limit:
                await self._request_lock.acquire()
                lock_acquired = True
                
                # Double check
                fund = cache.get_history("tiingo", ticker) or {}
                if fund.get("last_updated") == today_str:
                    return fund
                    
                now = time.time()
                time_since_last = now - self._last_request_time
                delay = float(os.environ.get("TIINGO_RATE_LIMIT_DELAY", "2.0"))
                if time_since_last < delay:
                    await asyncio.sleep(delay - time_since_last)
                    
                self._last_request_time = time.time()

            try:
                one_year_ago_dt = datetime.now() - timedelta(days=365)
                one_year_ago = one_year_ago_dt.strftime("%Y-%m-%d")
                
                existing_prices = fund.get("raw_prices", [])
                startDate = None
                if history_data.get("raw_prices") and history_data.get("last_updated"):
                    try:
                        last_dt = datetime.strptime(history_data["last_updated"], "%Y-%m-%d").date()
                        start_dt = last_dt + timedelta(days=1)
                        if start_dt <= datetime.now().date():
                            startDate = start_dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass

                if not startDate:
                    startDate = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

                data = await self.get_ticker_price(ticker, startDate=startDate)
                
                if data:
                    existing_prices = history_data.get("raw_prices", [])
                    
                    new_dates = {item["date"].split("T")[0] for item in data}
                    merged = [p for p in existing_prices if p["date"].split("T")[0] not in new_dates]
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
                        high_52w = max((item.get("high", 0) for item in data_prices), default=None)
                        low_52w = min((item.get("low", float("inf")) for item in data_prices), default=None)
                        
                        div_rate = sum(item.get("divCash", 0) for item in data_prices)
                        
                        vol_days = data_prices[-10:] if len(data_prices) >= 10 else data_prices
                        avg_vol = sum(item.get("volume", 0) for item in vol_days) / len(vol_days) if vol_days else None
                        
                        history_days = data_prices[-30:] if len(data_prices) >= 30 else data_prices
                        history = [item.get("close", 0) for item in history_days]
                        
                        if high_52w: history_data["high_52w"] = high_52w
                        if low_52w: history_data["low_52w"] = low_52w
                        if div_rate > 0: history_data["dividend_rate"] = div_rate
                        if avg_vol: history_data["avg_volume"] = avg_vol
                        history_data["history"] = history
                        
                        latest_close = data_prices[-1].get("close")
                        if latest_close and div_rate > 0:
                            history_data["dividend_yield"] = div_rate / latest_close
                        else:
                            history_data["dividend_yield"] = None
            except Exception as e:
                print(f"[tiingo-ws] Error fetching historical prices for {ticker}: {e}", file=sys.stderr)

            history_data["last_updated"] = today_str
            cache.set_history("tiingo", ticker, history_data)
            
            return history_data
        finally:
            if lock_acquired:
                self._request_lock.release()
