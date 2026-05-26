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
from .provider import DataProvider, YAHOO_MARKET_TICKERS
from .cache import cache
from .builder import builder
import sys
import yfinance as yf

class YFinanceProvider(DataProvider):
    def __init__(self) -> None:
        self._market_cache = None
        self._quotes_cache = {}
        self._history_cache = {}

    async def fetch_market(self) -> dict[str, any]:
        if not builder.is_market_open() and self._market_cache:
            return self._market_cache

        return await asyncio.to_thread(self._fetch_market_sync)

    def _fetch_market_sync(self) -> dict[str, any]:
        symbols = list(YAHOO_MARKET_TICKERS.values())
        names = list(YAHOO_MARKET_TICKERS.keys())

        try:
            tickers = yf.Tickers(" ".join(symbols))
            indices = []

            for sym, name in zip(symbols, names):
                try:
                    t = tickers.tickers[sym]
                    info = t.fast_info
                    price = info.get("lastPrice", 0)
                    prev_close = info.get("previousClose", 0)
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close and prev_close != 0 else 0.0
                    indices.append(builder.build_market_index(name, price, change_pct))
                except Exception:
                    indices.append({"name": name, "value": None, "change": 0.0})

            result = {"indices": indices, "is_open": builder.is_market_open()}
            self._market_cache = result
            return result

        except Exception as e:
            print(f"[stiq] Market fetch error (yfinance): {e}", file=sys.stderr)
            if self._market_cache:
                return self._market_cache
            return {"indices": [], "is_open": False}

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        if not builder.is_market_open():
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

        return await asyncio.to_thread(self._fetch_quotes_sync, symbols)

    def _fetch_quotes_sync(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        results = {}
        try:
            tickers = yf.Tickers(" ".join(symbols))

            for sym in symbols:
                sym_upper = sym.upper()
                try:
                    t = tickers.tickers[sym]
                    info = t.fast_info

                    row = builder.build_realtime_quote(
                        sym=sym_upper,
                        price=info.get("lastPrice", 0),
                        prev_close=info.get("previousClose", 0),
                        open=info.get("open", 0),
                        high=info.get("dayHigh", 0),
                        low=info.get("dayLow", 0),
                        volume=info.get("lastVolume", 0),
                    )
                    results[sym_upper] = row
                    self._quotes_cache[sym_upper] = row

                except Exception as e:
                    print(
                        f"[stiq] Quote error for {sym_upper} (yfinance): {e}",
                        file=sys.stderr,
                    )
                    if not builder.is_market_open():
                        row = builder.build_realtime_quote(sym_upper)
                        self._quotes_cache[sym_upper] = row
                        results[sym_upper] = row
                    elif sym_upper in self._quotes_cache:
                        results[sym_upper] = self._quotes_cache[sym_upper]

        except Exception as e:
            print(f"[stiq] Quotes fetch error (yfinance): {e}", file=sys.stderr)
            for sym in symbols:
                sym_upper = sym.upper()
                if not builder.is_market_open():
                    row = builder.build_realtime_quote(sym_upper)
                    self._quotes_cache[sym_upper] = row
                    results[sym_upper] = row
                elif sym_upper in self._quotes_cache:
                    results[sym_upper] = self._quotes_cache[sym_upper]

        return results

    async def fetch_history(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        if not symbols:
            return {}

        if not builder.is_market_open():
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

        return await asyncio.to_thread(self._fetch_history_sync, symbols)

    def _fetch_history_sync(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        results = {}
        try:
            tickers = yf.Tickers(" ".join(symbols))

            for sym in symbols:
                sym_upper = sym.upper()
                try:
                    t = tickers.tickers[sym]
                    info = t.fast_info
                    t_info = {}
                    try:
                        t_info = t.info
                    except Exception:
                        pass
                        
                    cached = cache.get_history(sym_upper)
                    if cached is not None:
                        h = cached
                    else:
                        hist = t.history(period="1mo")
                        h = []
                        if (
                            hist is not None
                            and not hist.empty
                            and "Close" in hist.columns
                        ):
                            h = [round(float(c), 2) for c in hist["Close"].tolist()]
                        cache.set_history(sym_upper, h)

                    row = builder.build_history_quote(
                        sym=sym_upper,
                        low_52w=info.get("fiftyTwoWeekLow") or t_info.get("fiftyTwoWeekLow"),
                        high_52w=info.get("fiftyTwoWeekHigh") or t_info.get("fiftyTwoWeekHigh"),
                        avg_volume=info.get("averageVolume10Day") or t_info.get("averageDailyVolume10Day"),
                        pe_ratio=t_info.get("trailingPE"),
                        dividend_rate=t_info.get("dividendRate") or t_info.get("trailingAnnualDividendRate"),
                        dividend_yield=t_info.get("dividendYield") or t_info.get("trailingAnnualDividendYield"),
                        market_cap=info.get("marketCap") or t_info.get("marketCap"),
                        currency=info.get("currency") or t_info.get("currency", "USD"),
                        history=h,
                    )
                    results[sym_upper] = row
                    self._history_cache[sym_upper] = row

                except Exception as e:
                    print(
                        f"[stiq] History error for {sym_upper} (yfinance): {e}",
                        file=sys.stderr,
                    )
                    if not builder.is_market_open():
                        row = builder.build_history_quote(sym_upper)
                        self._history_cache[sym_upper] = row
                        results[sym_upper] = row
                    elif sym_upper in self._history_cache:
                        results[sym_upper] = self._history_cache[sym_upper]

        except Exception as e:
            print(f"[stiq] History fetch error (yfinance): {e}", file=sys.stderr)
            for sym in symbols:
                sym_upper = sym.upper()
                if not builder.is_market_open():
                    row = builder.build_history_quote(sym_upper)
                    self._history_cache[sym_upper] = row
                    results[sym_upper] = row
                elif sym_upper in self._history_cache:
                    results[sym_upper] = self._history_cache[sym_upper]

        return results
