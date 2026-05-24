import asyncio
import gzip
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

from .provider import DataProvider, YAHOO_MARKET_TICKERS
from .cache import cache
from .builder import builder

_DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class YahooProvider(DataProvider):
    def __init__(self) -> None:
        self._market_cache = None
        self._quotes_cache = {}
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self._user_agent = _DEFAULT_USER_AGENT
        self.opener.addheaders = [("User-Agent", self._user_agent)]
        self.crumb = None
        self.initialized = False

    async def fetch_market(self) -> dict[str, any]:
        return await asyncio.to_thread(self._fetch_market_sync)

    def _fetch_market_sync(self) -> dict[str, any]:
        if not builder.is_market_open() and self._market_cache:
            return self._market_cache

        symbols = list(YAHOO_MARKET_TICKERS.values())
        names = list(YAHOO_MARKET_TICKERS.keys())

        try:
            quotes = self._fetch_raw_quotes(symbols)
            indices = []

            for sym, name in zip(symbols, names):
                try:
                    indices.append(
                        builder.build_market_index(name, quotes.get(sym.upper(), {}))
                    )
                except Exception:
                    indices.append({"name": name, "value": None, "change": 0.0})

            result = {"indices": indices, "is_open": builder.is_market_open()}
            self._market_cache = result
            return result

        except Exception as e:
            print(f"[stiq] Market fetch error (custom): {e}", file=sys.stderr)
            if self._market_cache:
                return self._market_cache
            return {"indices": [], "is_open": False}

    def _normalize_raw_quote(self, raw_quote: dict[str, any]) -> dict[str, any]:
        return builder.make_normalized_quote(
            price=raw_quote.get("regularMarketPrice", 0),
            prev_close=raw_quote.get("regularMarketPreviousClose", 0),
            open=raw_quote.get("regularMarketOpen", 0),
            high=raw_quote.get("regularMarketDayHigh", 0),
            low=raw_quote.get("regularMarketDayLow", 0),
            volume=raw_quote.get("regularMarketVolume", 0),
            low_52w=raw_quote.get("fiftyTwoWeekLow"),
            high_52w=raw_quote.get("fiftyTwoWeekHigh"),
            avg_volume=raw_quote.get("averageDailyVolume10Day"),
            pe_ratio=raw_quote.get("trailingPE"),
            dividend_rate=raw_quote.get("trailingAnnualDividendRate"),
            dividend_yield=raw_quote.get("trailingAnnualDividendYield"),
            market_cap=raw_quote.get("marketCap"),
            currency=raw_quote.get("currency", "USD"),
            history=raw_quote.get("history", []),
            change_pct=raw_quote.get("regularMarketChangePercent"),
        )

    def _fetch_raw_quotes(
        self, symbols: list[str], include_history: bool = False
    ) -> dict[str, dict[str, any]]:
        if not self._initialize() or not symbols:
            return {}

        url = f"https://query1.finance.yahoo.com/v7/finance/quote?crumb={self.crumb}&symbols={','.join(symbols)}"
        try:
            data = self._query_api(url)
            results = data.get("quoteResponse", {}).get("result", [])
            quotes = {}
            for r in results:
                sym_upper = r.get("symbol", "").upper()
                if not sym_upper:
                    continue
                normalized = self._normalize_raw_quote(r)
                if include_history:
                    cached = cache.get_history(sym_upper)
                    if cached is not None:
                        normalized["history"] = cached
                    else:
                        h = self._fetch_history(sym_upper)
                        cache.set_history(sym_upper, h)
                        normalized["history"] = h
                quotes[sym_upper] = normalized
            return quotes
        except Exception as e:
            print(f"[stiq-custom] Error fetching raw quote data: {e}", file=sys.stderr)
            return {}

    async def fetch_quotes(
        self, symbols: list[str], include_history: bool = True
    ) -> list[dict[str, any]]:
        return await asyncio.to_thread(self._fetch_quotes_sync, symbols, include_history)

    def _fetch_quotes_sync(
        self, symbols: list[str], include_history: bool = True
    ) -> list[dict[str, any]]:
        if not symbols:
            return []

        if not builder.is_market_open():
            results = []
            all_cached = True
            for sym in symbols:
                sym_upper = sym.upper()
                if sym_upper in self._quotes_cache:
                    results.append(self._quotes_cache[sym_upper])
                else:
                    all_cached = False
                    break
            if all_cached:
                return results

        quotes = self._fetch_raw_quotes(symbols, include_history=include_history)
        results = []
        for sym in symbols:
            sym_upper = sym.upper()
            try:
                row = builder.build_quote_row(sym_upper, quotes.get(sym_upper, {}))
                results.append(row)
                self._quotes_cache[sym_upper] = row

            except Exception as e:
                print(
                    f"[stiq] Quote error for {sym_upper} (custom): {e}", file=sys.stderr
                )
                if not builder.is_market_open():
                    row = builder.build_quote_row(sym_upper, {})
                    self._quotes_cache[sym_upper] = row
                    results.append(row)
                elif sym_upper in self._quotes_cache:
                    results.append(self._quotes_cache[sym_upper])

        return results

    def _read_response(self, resp: any) -> str:
        data = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
                data = f.read()
        return data.decode("utf-8")

    def _get_headers(
        self, content_type: str = "application/json", include_origin: bool = True
    ) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
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

    def _query_api(
        self, url: str, content_type: str = "application/json"
    ) -> dict[str, any]:
        req = urllib.request.Request(
            url, headers=self._get_headers(content_type=content_type)
        )
        resp = self.opener.open(req)
        return json.loads(self._read_response(resp))

    def _fetchCookies(self) -> bool | None:
        req = urllib.request.Request(
            "https://finance.yahoo.com/",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        try:
            resp = self.opener.open(req)
            html = self._read_response(resp)
        except Exception as e:
            print(f"[stiq-custom] Error fetching initial cookies: {e}", file=sys.stderr)
            return False

        a1 = self._get_a1_cookie()
        if not a1:
            # EU Consent Flow
            url = resp.url
            try:
                session_id_match = re.search(r"sessionId=(?:([A-Za-z0-9_-]*))", url)
                csrf_token_match = re.search(r"gcrumb=(?:([A-Za-z0-9_]*))", url)

                if session_id_match and csrf_token_match:
                    session_id = session_id_match.group(1)
                    csrf_token = csrf_token_match.group(1)

                    form_data = urllib.parse.urlencode(
                        {
                            "csrfToken": csrf_token,
                            "sessionId": session_id,
                            "namespace": "yahoo",
                            "agree": "agree",
                        }
                    ).encode()

                    req2 = urllib.request.Request(
                        f"https://consent.yahoo.com/v2/collectConsent?sessionId={session_id}",
                        data=form_data,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Origin": "https://consent.yahoo.com",
                            "Referer": url,
                        },
                    )
                    self.opener.open(req2)
                    a1 = self._get_a1_cookie()
            except Exception as e:
                print(f"[stiq-custom] Error in EU consent flow: {e}", file=sys.stderr)
                return False

        if not a1:
            pass

        print(
            f"[stiq-custom] Cookies acquired: {[c.name for c in self.cookie_jar]}",
            file=sys.stderr,
        )
        return None

    def _fetchCrumb(self) -> bool:
        try:
            req_crumb = urllib.request.Request(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                headers=self._get_headers(
                    content_type="text/plain", include_origin=False
                ),
            )
            resp = self.opener.open(req_crumb)
            self.crumb = self._read_response(resp)
            self.initialized = True
            return True
        except Exception as e:
            print(f"[stiq-custom] Error fetching crumb: {e}", file=sys.stderr)
            return False

    def _get_a1_cookie(self) -> str | None:
        for c in self.cookie_jar:
            if c.name == "A1":
                return f"{c.name}={c.value}"
        return None

    def _initialize(self) -> bool:
        if self.initialized:
            return True

        self._fetchCookies()
        return self._fetchCrumb()

    def _fetch_history(self, symbol: str) -> list[float]:
        if not self._initialize():
            return []

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo&crumb={self.crumb}"
        try:
            data = self._query_api(url)
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
