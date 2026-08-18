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
import re
import sys
from typing import TYPE_CHECKING

import aiohttp

from .provider import YAHOO_MARKET_TICKERS, DataProvider

if TYPE_CHECKING:
    from .builder import QuoteBuilder
    from .cache import CacheManager
    from .config import ConfigManager
    from .events import EventBus
    from .tiingo_usage import TiingoUsageTracker

_DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class YahooProvider(DataProvider):
    def __init__(
        self,
        config: "ConfigManager",
        event_bus: "EventBus",
        usage_tracker: "TiingoUsageTracker",
        cache: "CacheManager",
        builder: "QuoteBuilder",
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.usage_tracker = usage_tracker
        self.cache = cache
        self.builder = builder

        self._market_cache = None
        self._quotes_cache = {}
        self._history_cache = {}

        self.session: aiohttp.ClientSession | None = None
        self._user_agent = _DEFAULT_USER_AGENT
        self.crumb = None
        self.initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(
                    unsafe=True
                ),  # unsafe=True needed for IP addresses if any, fine for Yahoo
                headers={"User-Agent": self._user_agent},
                max_line_size=32768,
                max_field_size=32768,
            )

    async def fetch_market(self) -> dict[str, any]:
        if not self.builder.is_market_open() and self._market_cache:
            return self._market_cache

        symbols = list(YAHOO_MARKET_TICKERS.values())
        names = list(YAHOO_MARKET_TICKERS.keys())

        try:
            raw_quotes = await self._fetch_raw_quotes(symbols)
            quotes_map = {
                r.get("symbol", "").upper(): r for r in raw_quotes if r.get("symbol")
            }
            indices = []

            for sym, name in zip(symbols, names, strict=True):
                try:
                    q = quotes_map.get(sym.upper(), {})
                    price = q.get("regularMarketPrice", 0)
                    prev_close = q.get("regularMarketPreviousClose", 0)
                    change_pct = q.get("regularMarketChangePercent")
                    if change_pct is None:
                        change_pct = (
                            ((price - prev_close) / prev_close * 100)
                            if prev_close and prev_close != 0
                            else 0.0
                        )
                    indices.append(
                        self.builder.build_market_index(name, price, change_pct)
                    )
                except Exception:
                    indices.append({"name": name, "value": None, "change": 0.0})

            result = {"indices": indices, "is_open": self.builder.is_market_open()}
            self._market_cache = result
            return result

        except Exception as e:
            print(f"[stiq] Market fetch error (custom): {e}", file=sys.stderr)
            if self._market_cache:
                return self._market_cache
            return {"indices": [], "is_open": False}

    def _chunk_symbols(
        self, symbols: list[str], chunk_size: int = 500
    ) -> list[list[str]]:
        return [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]

    async def _fetch_raw_quotes(self, symbols: list[str]) -> list[dict[str, any]]:
        if not await self._initialize() or not symbols:
            return []

        all_results = []
        for chunk in self._chunk_symbols(symbols):
            url = f"https://query1.finance.yahoo.com/v7/finance/quote?crumb={self.crumb}&symbols={','.join(chunk)}"
            try:
                data = await self._query_api(url)
                all_results.extend(data.get("quoteResponse", {}).get("result", []))
            except Exception as e:
                print(
                    f"[stiq-custom] Error fetching raw quote data for chunk: {e}",
                    file=sys.stderr,
                )

        return all_results

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        if not self.builder.is_market_open():
            results = {}
            all_cached = True
            for sym in symbols:
                sym_upper = sym.upper()
                if sym_upper in self._quotes_cache:
                    results[sym_upper] = self._quotes_cache[sym_upper]
                else:
                    all_cached = False
                    break
            if all_cached:
                return results

        raw_quotes = await self._fetch_raw_quotes(symbols)
        quotes_map = {
            r.get("symbol", "").upper(): r for r in raw_quotes if r.get("symbol")
        }
        results = {}

        for sym in symbols:
            sym_upper = sym.upper()
            try:
                r = quotes_map.get(sym_upper, {})
                row = self.builder.build_realtime_quote(
                    sym=sym_upper,
                    price=r.get("regularMarketPrice", 0),
                    prev_close=r.get("regularMarketPreviousClose", 0),
                    open=r.get("regularMarketOpen", 0),
                    high=r.get("regularMarketDayHigh", 0),
                    low=r.get("regularMarketDayLow", 0),
                    volume=r.get("regularMarketVolume", 0),
                    change_pct=r.get("regularMarketChangePercent"),
                )
                results[sym_upper] = row
                self._quotes_cache[sym_upper] = row

            except Exception as e:
                print(
                    f"[stiq] Quote error for {sym_upper} (custom): {e}", file=sys.stderr
                )
                if not self.builder.is_market_open():
                    row = self.builder.build_realtime_quote(sym_upper)
                    self._quotes_cache[sym_upper] = row
                    results[sym_upper] = row
                elif sym_upper in self._quotes_cache:
                    results[sym_upper] = self._quotes_cache[sym_upper]

        return results

    async def fetch_history(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        if not self.builder.is_market_open():
            results = {}
            all_cached = True
            for sym in symbols:
                sym_upper = sym.upper()
                if sym_upper in self._history_cache:
                    results[sym_upper] = self._history_cache[sym_upper]
                else:
                    all_cached = False
                    break
            if all_cached:
                return results

        from datetime import date

        today_str = date.today().isoformat()
        results = {}
        symbols_to_fetch = []

        # 1. Check cache first
        for sym in symbols:
            sym_upper = sym.upper()
            cached = self.cache.get_history(sym_upper)

            # Cache hit: it has today's date AND Yahoo metrics (we check 'currency' which Yahoo always sets)
            if (
                cached is not None
                and cached.get("last_updated") == today_str
                and cached.get("currency") is not None
            ):
                row = self.builder.build_history_quote(
                    sym=sym_upper,
                    low_52w=cached.get("low_52w"),
                    high_52w=cached.get("high_52w"),
                    avg_volume=cached.get("avg_volume"),
                    pe_ratio=cached.get("pe_ratio"),
                    dividend_rate=cached.get("dividend_rate"),
                    dividend_yield=cached.get("dividend_yield"),
                    market_cap=cached.get("market_cap"),
                    currency=cached.get("currency", "USD"),
                    history=cached.get("history", []),
                )
                results[sym_upper] = row
                self._history_cache[sym_upper] = row
            else:
                symbols_to_fetch.append(sym)

        if not symbols_to_fetch:
            return results

        # 2. Fetch for missing symbols
        raw_quotes = await self._fetch_raw_quotes(symbols_to_fetch)
        quotes_map = {
            r.get("symbol", "").upper(): r for r in raw_quotes if r.get("symbol")
        }

        for sym in symbols_to_fetch:
            sym_upper = sym.upper()
            try:
                r = quotes_map.get(sym_upper, {})

                cached = self.cache.get_history(sym_upper)
                if cached is not None and cached.get("last_updated") == today_str:
                    history_arr = cached.get("history", [])
                else:
                    history_arr = await self._fetch_history_chart(sym_upper)

                cache_update = {
                    "history": history_arr,
                    "last_updated": today_str,
                    "raw_prices": [],
                    "low_52w": r.get("fiftyTwoWeekLow"),
                    "high_52w": r.get("fiftyTwoWeekHigh"),
                    "avg_volume": r.get("averageDailyVolume10Day"),
                    "pe_ratio": r.get("trailingPE"),
                    "dividend_rate": r.get("trailingAnnualDividendRate"),
                    "dividend_yield": r.get("trailingAnnualDividendYield"),
                    "market_cap": r.get("marketCap"),
                    "currency": r.get("currency", "USD"),
                }
                self.cache.set_history(sym_upper, cache_update)

                row = self.builder.build_history_quote(
                    sym=sym_upper,
                    low_52w=r.get("fiftyTwoWeekLow"),
                    high_52w=r.get("fiftyTwoWeekHigh"),
                    avg_volume=r.get("averageDailyVolume10Day"),
                    pe_ratio=r.get("trailingPE"),
                    dividend_rate=r.get("trailingAnnualDividendRate"),
                    dividend_yield=r.get("trailingAnnualDividendYield"),
                    market_cap=r.get("marketCap"),
                    currency=r.get("currency", "USD"),
                    history=history_arr,
                )
                results[sym_upper] = row
                self._history_cache[sym_upper] = row

            except Exception as e:
                print(
                    f"[stiq] History error for {sym_upper} (custom): {e}",
                    file=sys.stderr,
                )

                # 3. Fallback to stale cache if API failed
                cached = self.cache.get_history(sym_upper)
                if cached is not None:
                    row = self.builder.build_history_quote(
                        sym=sym_upper,
                        low_52w=cached.get("low_52w"),
                        high_52w=cached.get("high_52w"),
                        avg_volume=cached.get("avg_volume"),
                        pe_ratio=cached.get("pe_ratio"),
                        dividend_rate=cached.get("dividend_rate"),
                        dividend_yield=cached.get("dividend_yield"),
                        market_cap=cached.get("market_cap"),
                        currency=cached.get("currency", "USD"),
                        history=cached.get("history", []),
                    )
                    results[sym_upper] = row
                    self._history_cache[sym_upper] = row
                elif not self.builder.is_market_open():
                    row = self.builder.build_history_quote(sym_upper)
                    self._history_cache[sym_upper] = row
                    results[sym_upper] = row
                elif sym_upper in self._history_cache:
                    results[sym_upper] = self._history_cache[sym_upper]

        return results

    def _get_headers(
        self, content_type: str = "application/json", include_origin: bool = True
    ) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Content-Type": content_type,
            "Host": "query1.finance.yahoo.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "TE": "trailers",
        }
        if include_origin:
            headers["Origin"] = "https://finance.yahoo.com"
            headers["Referer"] = "https://finance.yahoo.com"
        return headers

    async def _query_api(
        self, url: str, content_type: str = "application/json", is_text: bool = False
    ) -> any:
        await self._ensure_session()
        headers = self._get_headers(content_type=content_type)
        if url.startswith("https://query1.finance.yahoo.com/v1/test/getcrumb"):
            headers["Origin"] = "https://finance.yahoo.com"
            headers["Referer"] = "https://finance.yahoo.com"

        async with self.session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            if is_text:
                return await resp.text()
            return await resp.json()

    async def _fetchCookies(self) -> bool | None:
        await self._ensure_session()
        url = "https://finance.yahoo.com/"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                await resp.text()
                current_url = str(resp.url)
        except Exception as e:
            print(f"[stiq-custom] Error fetching initial cookies: {e}", file=sys.stderr)
            return False

        a1 = self._get_a1_cookie()
        if not a1:
            # EU Consent Flow
            try:
                session_id_match = re.search(
                    r"sessionId=(?:([A-Za-z0-9_-]*))", current_url
                )
                csrf_token_match = re.search(r"gcrumb=(?:([A-Za-z0-9_]*))", current_url)

                if session_id_match and csrf_token_match:
                    session_id = session_id_match.group(1)
                    csrf_token = csrf_token_match.group(1)

                    form_data = {
                        "csrfToken": csrf_token,
                        "sessionId": session_id,
                        "namespace": "yahoo",
                        "agree": "agree",
                    }

                    consent_url = f"https://consent.yahoo.com/v2/collectConsent?sessionId={session_id}"
                    consent_headers = {
                        "Origin": "https://consent.yahoo.com",
                        "Referer": current_url,
                    }
                    async with self.session.post(
                        consent_url, data=form_data, headers=consent_headers
                    ) as resp2:
                        await resp2.text()

                    a1 = self._get_a1_cookie()
            except Exception as e:
                print(f"[stiq-custom] Error in EU consent flow: {e}", file=sys.stderr)
                return False

        print(
            f"[stiq-custom] Cookies acquired: {[c.key for c in self.session.cookie_jar]}",
            file=sys.stderr,
        )
        return None

    async def _fetchCrumb(self) -> bool:
        try:
            self.crumb = await self._query_api(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                content_type="text/plain",
                is_text=True,
            )
            self.initialized = True
            return True
        except Exception as e:
            print(f"[stiq-custom] Error fetching crumb: {e}", file=sys.stderr)
            return False

    def _get_a1_cookie(self) -> str | None:
        if self.session and self.session.cookie_jar:
            for cookie in self.session.cookie_jar:
                if cookie.key == "A1":
                    return f"{cookie.key}={cookie.value}"
        return None

    async def _initialize(self) -> bool:
        if self.initialized:
            return True

        async with self._init_lock:
            if self.initialized:
                return True
            await self._fetchCookies()
            return await self._fetchCrumb()

    async def _fetch_history_chart(self, symbol: str) -> list[float]:
        if not await self._initialize():
            return []

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo&crumb={self.crumb}"
        try:
            data = await self._query_api(url)
            result = data.get("chart", {}).get("result", [])
            if result:
                indicators = result[0].get("indicators", {}).get("quote", [])
                if indicators and "close" in indicators[0]:
                    closes = indicators[0]["close"]
                    return [round(float(c), 2) for c in closes if c is not None]
        except Exception as e:
            print(
                f"[stiq-custom] Error fetching history for {symbol}: {e}",
                file=sys.stderr,
            )
        return []
