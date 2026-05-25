"""
TiingoWebSocketProvider — DataProvider backed by Tiingo IEX + Forex websocket feeds.

Maintains persistent websocket connections in background asyncio tasks running
directly on the application's main event loop, caches the latest tick data in-memory,
and serves it asynchronously via fetch_market() / fetch_quotes().
No REST API calls are made; all data comes from the websocket streams.
"""

import asyncio
import json
import os
import sys
import urllib.request
from datetime import date
from typing import Any

import websockets

from .provider import DataProvider, YAHOO_MARKET_TICKERS
from .builder import builder



# ── Tiingo WebSocket Endpoints ──────────────────────────────────────
_IEX_WS_URL = "wss://api.tiingo.com/iex"
_FX_WS_URL = "wss://api.tiingo.com/fx"

# ── IEX data array field positions (thresholdLevel 5) ───────────────
# data[0] = updateType ("Q" quote / "T" trade)
# data[1] = ticker
# data[2] = timestamp
# data[3] = tngoLast
# data[4] = prevClose
# data[5] = open
# data[6] = high
# data[7] = low
# data[8] = volume
_IEX_TICKER    = 1
_IEX_TNGOLAST  = 3
_IEX_PREVCLOSE = 4
_IEX_OPEN      = 5
_IEX_HIGH      = 6
_IEX_LOW       = 7
_IEX_VOLUME    = 8

# ── FX data array field positions (thresholdLevel 5, type "Q") ──────
# data[0] = updateType ("Q")
# data[1] = ticker
# data[2] = timestamp
# data[3] = bidSize
# data[4] = bidPrice
# data[5] = midPrice
# data[6] = askSize
# data[7] = askPrice
_FX_TICKER   = 1
_FX_BIDPRICE = 4
_FX_MIDPRICE = 5
_FX_ASKPRICE = 7


def _safe_float(val, default=0.0) -> float:
    """Coerce a value to float, returning default if None or invalid."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class TiingoWebSocketProvider(DataProvider):
    """DataProvider implementation using Tiingo IEX + FX websocket feeds."""

    def __init__(self) -> None:
        self._api_key: str = os.environ.get("TIINGO_API_KEY", "")
        if not self._api_key:
            print("[tiingo-ws] WARNING: TIINGO_API_KEY not set", file=sys.stderr)

        try:
            self._threshold = int(os.environ.get("TIINGO_THRESHOLD", "5"))
        except ValueError:
            self._threshold = 5

        # ── Caches ──────────────────────────────────────────────────
        self._iex_cache: dict[str, dict[str, Any]] = {}
        
        self._quotes_cache: dict[str, dict] = {}
        self._fundamentals_cache: dict[str, dict[str, Any]] = {}
        self._fundamentals_requested: set[str] = set()
        self._load_fund_cache()

        # ── Subscription tracking ──────────────────────────────────
        self._iex_sub_id: str | None = None
        self._current_iex_tickers: set[str] = set()

        # ── WebSocket references ───────────────────────────────────
        self._iex_ws: Any = None

        # ── Lazy initialization flag ───────────────────────────────
        self._started = False
        self._last_request_time = 0.0

    def _load_fund_cache(self) -> None:
        cache_file = os.path.expanduser("~/.stiq/tiingo_fund_cache.json")
        try:
            if os.path.exists(cache_file):
                with open(cache_file, "r") as f:
                    data = json.load(f)
                self._fundamentals_cache = data.get("symbols", {})
        except Exception as e:
            print(f"[tiingo-ws] Error loading fundamentals cache: {e}", file=sys.stderr)

    def _save_fund_cache(self) -> None:
        cache_file = os.path.expanduser("~/.stiq/tiingo_fund_cache.json")
        try:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump({"symbols": self._fundamentals_cache}, f)
        except Exception as e:
            print(f"[tiingo-ws] Error saving fundamentals cache: {e}", file=sys.stderr)

    async def _ensure_started(self) -> None:
        """Starts connection tasks on the active asyncio loop when first accessed."""
        if not self._started:
            self._started = True
            self._request_lock = asyncio.Lock()
            if self._api_key:
                await self._seed_initial_data()
                loop = asyncio.get_running_loop()
                loop.create_task(self._iex_connect_loop())

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
            loop = asyncio.get_running_loop()
            
            # Seed IEX
            iex_desired = self._get_iex_tickers()
            missing_iex = [t for t in iex_desired if t.upper() not in self._iex_cache]
            if missing_iex:
                iex_tickers = ",".join(missing_iex)
                url_iex = f"https://api.tiingo.com/iex/?tickers={iex_tickers}&token={self._api_key}"
                req_iex = urllib.request.Request(url_iex, headers={"Content-Type": "application/json"})
                resp_iex = await loop.run_in_executor(None, urllib.request.urlopen, req_iex)
                data_iex = json.loads(resp_iex.read().decode("utf-8"))
                for r in data_iex:
                    ticker = r.get("ticker", "").upper()
                    price = _safe_float(r.get("tngoLast"))
                    prev_close = _safe_float(r.get("prevClose"))
                    open_price = _safe_float(r.get("open"))
                    high = _safe_float(r.get("high"))
                    low = _safe_float(r.get("low"))
                    volume = _safe_float(r.get("volume"))
                    
                    normalized = builder.make_normalized_quote(
                        price=price,
                        prev_close=prev_close,
                        open=open_price,
                        high=high,
                        low=low,
                        volume=volume,
                        currency="USD",
                        history=[],
                    )
                    if ticker not in self._iex_cache:
                        self._iex_cache[ticker] = normalized
            try:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump({
                        "iex": self._iex_cache
                    }, f, indent=4)
            except Exception as e:
                print(f"[tiingo-ws] Error saving cache: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[tiingo-ws] Error seeding initial data: {e}", file=sys.stderr)

    # ────────────────────────────────────────────────────────────────
    # IEX WebSocket
    # ────────────────────────────────────────────────────────────────

    def _get_iex_tickers(self) -> list[str]:
        """Collect all equity tickers we need from the IEX feed."""
        tickers: set[str] = set()
        # Watchlist symbols (imported lazily to avoid circular deps)
        try:
            from .config import config
            for sym in config.watchlist:
                tickers.add(sym.upper())
        except Exception:
            pass
        return sorted(tickers)

    async def _iex_connect_loop(self) -> None:
        """Connect to IEX websocket with auto-reconnect and exponential backoff."""
        backoff = 1.0
        while True:
            try:
                url = f"{_IEX_WS_URL}?token={self._api_key}"
                print("[tiingo-ws] IEX connecting…", file=sys.stderr)
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    self._iex_ws = ws
                    backoff = 1.0
                    await self._on_iex_open(ws)
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

            # Reconnect with backoff
            print(f"[tiingo-ws] IEX reconnecting in {backoff:.0f}s…", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _on_iex_open(self, ws) -> None:
        print("[tiingo-ws] IEX connected", file=sys.stderr)
        tickers = self._get_iex_tickers()
        self._current_iex_tickers = set(t.upper() for t in tickers)
        
        subscribe_msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {
                "thresholdLevel": self._threshold,
                "tickers": tickers,
            },
        }
        await ws.send(json.dumps(subscribe_msg))
        print(f"[tiingo-ws] IEX subscribed to {len(tickers)} tickers", file=sys.stderr)

    def _on_iex_message(self, raw_msg: str | bytes) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("messageType")

        # Capture subscription ID from initial "I" info message
        if msg_type == "I":
            data = msg.get("data", {})
            if isinstance(data, dict):
                self._iex_sub_id = data.get("subscriptionId")
            return

        # Ignore heartbeats
        if msg_type == "H":
            return

        # Process data updates ("A" = new data)
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

            normalized = builder.make_normalized_quote(
                price=price,
                prev_close=prev_close,
                open=open_price,
                high=high,
                low=low,
                volume=volume,
                currency="USD",
                history=[],
            )

            self._iex_cache[ticker] = normalized

    # ────────────────────────────────────────────────────────────────
        return sorted(tickers)

    async def _fx_connect_loop(self) -> None:
        """Connect to FX websocket with auto-reconnect and exponential backoff."""
        backoff = 1.0
        while True:
            try:
                url = f"{_FX_WS_URL}?token={self._api_key}"
                print("[tiingo-ws] FX connecting…", file=sys.stderr)
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    self._fx_ws = ws
                    backoff = 1.0
                    await self._on_fx_open(ws)
                    async for message in ws:
                        self._on_fx_message(message)
            except Exception as e:
                print(f"[tiingo-ws] FX connection error: {e}", file=sys.stderr)
            finally:
                if self._fx_ws:
                    close_code = getattr(self._fx_ws, "close_code", None)
                    close_reason = getattr(self._fx_ws, "close_reason", None)
                    print(f"[tiingo-ws] FX closed: {close_code} {close_reason}", file=sys.stderr)
                self._fx_ws = None
                self._fx_sub_id = None

            # Reconnect with backoff
            print(f"[tiingo-ws] FX reconnecting in {backoff:.0f}s…", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _on_fx_open(self, ws) -> None:
        print("[tiingo-ws] FX connected", file=sys.stderr)
        tickers = self._get_fx_tickers()
        self._current_fx_tickers = set(t.lower() for t in tickers)
        subscribe_msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {
                "thresholdLevel": self._threshold,
                "tickers": tickers,
            },
        }
        await ws.send(json.dumps(subscribe_msg))
        print(f"[tiingo-ws] FX subscribed to {tickers}", file=sys.stderr)

    def _on_fx_message(self, raw_msg: str | bytes) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("messageType")

        # Capture subscription ID
        if msg_type == "I":
            data = msg.get("data", {})
            if isinstance(data, dict):
                self._fx_sub_id = data.get("subscriptionId")
            return

        if msg_type == "H":
            return

        if msg_type == "A":
            data = msg.get("data", [])
            if not isinstance(data, list) or len(data) < 6:
                return

            ticker = str(data[_FX_TICKER]).lower()
            mid_price = _safe_float(data[_FX_MIDPRICE])
            bid_price = _safe_float(data[_FX_BIDPRICE])
            ask_price = _safe_float(data[_FX_ASKPRICE])

            # Use midPrice as primary, fall back to bid
            price = mid_price if mid_price > 0 else bid_price
            if price <= 0:
                return

            # Synthetic prevClose: use the first price seen each calendar day
            today = date.today()
            if ticker not in self._fx_day or self._fx_day[ticker] != today:
                # First tick of a new day — if we had a previous price, use it
                if ticker in self._fx_cache:
                    old_price = self._fx_cache[ticker].get("price", price)
                    self._fx_prev_close[ticker] = old_price
                else:
                    # Very first tick ever — use current price (0% change)
                    self._fx_prev_close[ticker] = price
                self._fx_day[ticker] = today

            prev_close = self._fx_prev_close.get(ticker, price)

            self._fx_cache[ticker] = {
                "price": price,
                "midPrice": mid_price,
                "bidPrice": bid_price,
                "askPrice": ask_price,
                "prevClose": prev_close,
            }

    # ────────────────────────────────────────────────────────────────
    # Dynamic subscription updates
    # ────────────────────────────────────────────────────────────────

    async def _update_iex_subscriptions(self) -> None:
        """Check if the watchlist has changed and update IEX subscriptions directly."""
        desired = set(t.upper() for t in self._get_iex_tickers())
        if desired == self._current_iex_tickers:
            return

        ws = self._iex_ws
        if ws is None or not self._iex_sub_id:
            return

        new_tickers = desired - self._current_iex_tickers
        removed_tickers = self._current_iex_tickers - desired

        try:
            if new_tickers:
                msg = {
                    "eventName": "subscribe",
                    "authorization": self._api_key,
                    "eventData": {
                        "thresholdLevel": self._threshold,
                        "tickers": sorted(new_tickers),
                    },
                }
                await ws.send(json.dumps(msg))
                print(f"[tiingo-ws] IEX added tickers: {sorted(new_tickers)}", file=sys.stderr)

            if removed_tickers:
                msg = {
                    "eventName": "unsubscribe",
                    "authorization": self._api_key,
                    "eventData": {
                        "tickers": sorted(removed_tickers),
                    },
                }
                await ws.send(json.dumps(msg))
                print(f"[tiingo-ws] IEX removed tickers: {sorted(removed_tickers)}", file=sys.stderr)

            self._current_iex_tickers = desired
        except Exception as e:
            print(f"[tiingo-ws] IEX subscription update error: {e}", file=sys.stderr)

    # ────────────────────────────────────────────────────────────────
    # DataProvider interface
    # ────────────────────────────────────────────────────────────────

    async def fetch_market(self) -> dict[str, any]:
        # No-op since Tiingo doesn't stream indices natively and ETF proxy conversions are disabled
        return {"indices": [], "is_open": builder.is_market_open()}

    async def _fetch_fundamentals(self, ticker: str) -> None:
        lock_acquired = False
        try:
            if not self._api_key:
                return
                
            fund = self._fundamentals_cache.get(ticker, {})
            today_str = date.today().isoformat()
            
            if fund.get("last_updated") == today_str:
                return

            import time
            use_rate_limit = os.environ.get("USE_RATE_LIMIT", "1").lower() not in ("0", "false")

            if use_rate_limit:
                if self._request_lock.locked():
                    return
                    
                await self._request_lock.acquire()
                lock_acquired = True
                now = time.time()
                time_since_last = now - self._last_request_time
                if time_since_last < 90.0:
                    return
                    
                self._last_request_time = time.time()
                
            loop = asyncio.get_running_loop()
            
            # 1. Historical prices for 52w high/low, div, avg_vol, history
            try:
                from datetime import datetime, timedelta
                one_year_ago_dt = datetime.now() - timedelta(days=365)
                one_year_ago = one_year_ago_dt.strftime("%Y-%m-%d")
                
                existing_prices = fund.get("raw_prices", [])
                existing_prices = [p for p in existing_prices if p.get("date", "")[:10] >= one_year_ago]
                
                if existing_prices:
                    last_date_str = existing_prices[-1].get("date", "")[:10]
                    last_date_dt = datetime.strptime(last_date_str, "%Y-%m-%d")
                    start_date_dt = last_date_dt + timedelta(days=1)
                    start_date = start_date_dt.strftime("%Y-%m-%d")
                    
                    if start_date <= today_str:
                        url_prices = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_date}&token={self._api_key}"
                        req = urllib.request.Request(url_prices, headers={"Content-Type": "application/json"})
                        resp = await loop.run_in_executor(None, urllib.request.urlopen, req)
                        new_prices = json.loads(resp.read().decode("utf-8"))
                        data_prices = existing_prices + new_prices
                    else:
                        data_prices = existing_prices
                else:
                    url_prices = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={one_year_ago}&token={self._api_key}"
                    req = urllib.request.Request(url_prices, headers={"Content-Type": "application/json"})
                    resp = await loop.run_in_executor(None, urllib.request.urlopen, req)
                    data_prices = json.loads(resp.read().decode("utf-8"))
                
                fund["raw_prices"] = data_prices
                
                if data_prices:
                    high_52w = max((p.get("high", 0) for p in data_prices if p.get("high")), default=None)
                    low_52w = min((p.get("low", float('inf')) for p in data_prices if p.get("low")), default=None)
                    if low_52w == float('inf'): low_52w = None
                    
                    div_rate = sum(p.get("divCash", 0) for p in data_prices)
                    
                    recent_10 = data_prices[-10:]
                    avg_vol = sum(p.get("volume", 0) for p in recent_10) / len(recent_10) if recent_10 else None
                    
                    recent_30 = data_prices[-30:]
                    history = [p.get("close", 0) for p in recent_30]
                    
                    if high_52w: fund["high_52w"] = high_52w
                    if low_52w: fund["low_52w"] = low_52w
                    if div_rate > 0: fund["dividend_rate"] = div_rate
                    if avg_vol: fund["avg_volume"] = avg_vol
                    fund["history"] = history
                    
                    latest_close = data_prices[-1].get("close", 0)
                    if latest_close > 0 and div_rate > 0:
                        fund["dividend_yield"] = div_rate / latest_close
            except Exception as e:
                print(f"[tiingo-ws] Error fetching historical prices for {ticker}: {e}", file=sys.stderr)

            # 2. Daily fundamentals for PE / Market Cap
            try:
                url_fund = f"https://api.tiingo.com/tiingo/fundamentals/{ticker}/daily?token={self._api_key}"
                req = urllib.request.Request(url_fund, headers={"Content-Type": "application/json"})
                resp = await loop.run_in_executor(None, urllib.request.urlopen, req)
                data_fund = json.loads(resp.read().decode("utf-8"))
                if data_fund:
                    latest_fund = data_fund[-1]
                    if latest_fund.get("marketCap"):
                        fund["market_cap"] = latest_fund.get("marketCap")
                    if latest_fund.get("peRatio"):
                        fund["pe_ratio"] = latest_fund.get("peRatio")
            except urllib.error.HTTPError:
                pass # 404 expected for ETFs and unsupported tickers
            except Exception as e:
                print(f"[tiingo-ws] Error fetching fundamentals for {ticker}: {e}", file=sys.stderr)
                
            fund["last_updated"] = today_str
            self._fundamentals_cache[ticker] = fund

            # Update caches immediately so the next request (even if market closed) gets the new data
            if ticker in self._iex_cache:
                quote = self._iex_cache[ticker]
                quote["low_52w"] = fund.get("low_52w") if "low_52w" in fund else quote.get("low_52w")
                quote["high_52w"] = fund.get("high_52w") if "high_52w" in fund else quote.get("high_52w")
                quote["avg_volume"] = fund.get("avg_volume") if "avg_volume" in fund else quote.get("avg_volume")
                quote["pe_ratio"] = fund.get("pe_ratio") if "pe_ratio" in fund else quote.get("pe_ratio")
                quote["dividend_rate"] = fund.get("dividend_rate") if "dividend_rate" in fund else quote.get("dividend_rate")
                quote["dividend_yield"] = fund.get("dividend_yield") if "dividend_yield" in fund else quote.get("dividend_yield")
                quote["market_cap"] = fund.get("market_cap") if "market_cap" in fund else quote.get("market_cap")
                quote["history"] = fund.get("history") if "history" in fund else quote.get("history", [])
                self._quotes_cache[ticker] = builder.build_quote_row(ticker, quote)
                
            self._save_fund_cache()
        finally:
            if lock_acquired:
                self._request_lock.release()
            if ticker in self._fundamentals_requested:
                self._fundamentals_requested.remove(ticker)

    async def fetch_quotes(self, symbols: list[str]) -> list[dict[str, any]]:
        if not symbols:
            return []

        await self._ensure_started()

        # Update subscriptions if watchlist changed
        await self._update_iex_subscriptions()

        results = []
        for sym in symbols:
            sym_upper = sym.upper()
            
            fund = self._fundamentals_cache.get(sym_upper, {})
            today_str = date.today().isoformat()
            
            # Only request if it's expired
            if fund.get("last_updated") != today_str and sym_upper not in self._fundamentals_requested:
                self._fundamentals_requested.add(sym_upper)
                asyncio.create_task(self._fetch_fundamentals(sym_upper))
                
            try:
                quote = self._iex_cache.get(sym_upper)

                if quote:
                    # Overlay fundamentals on the IEX quote
                    fund = self._fundamentals_cache.get(sym_upper, {})
                    quote["low_52w"] = fund.get("low_52w") if "low_52w" in fund else quote.get("low_52w")
                    quote["high_52w"] = fund.get("high_52w") if "high_52w" in fund else quote.get("high_52w")
                    quote["avg_volume"] = fund.get("avg_volume") if "avg_volume" in fund else quote.get("avg_volume")
                    quote["pe_ratio"] = fund.get("pe_ratio") if "pe_ratio" in fund else quote.get("pe_ratio")
                    quote["dividend_rate"] = fund.get("dividend_rate") if "dividend_rate" in fund else quote.get("dividend_rate")
                    quote["dividend_yield"] = fund.get("dividend_yield") if "dividend_yield" in fund else quote.get("dividend_yield")
                    quote["market_cap"] = fund.get("market_cap") if "market_cap" in fund else quote.get("market_cap")
                    quote["history"] = fund.get("history") if "history" in fund else quote.get("history", [])

                    row = builder.build_quote_row(sym_upper, quote)
                    results.append(row)
                    self._quotes_cache[sym_upper] = row
                else:
                    # Fall back to previously cached result
                    if sym_upper in self._quotes_cache:
                        results.append(self._quotes_cache[sym_upper])
            except Exception:
                if sym_upper in self._quotes_cache:
                    results.append(self._quotes_cache[sym_upper])

        return results
