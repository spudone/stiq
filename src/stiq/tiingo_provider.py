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
from datetime import date
from typing import Any

import websockets

from .provider import DataProvider, YAHOO_MARKET_TICKERS
from .builder import builder
from .yahoo_provider import YahooProvider


# ── Tiingo WebSocket Endpoints ──────────────────────────────────────
_IEX_WS_URL = "wss://api.tiingo.com/iex"
_FX_WS_URL = "wss://api.tiingo.com/fx"

# ── Market index mapping: Yahoo tickers → Tiingo-streamable proxies ─
# Tiingo IEX streams US-listed equities/ETFs.  For indices we use ETF
# proxies; for currencies we use the forex websocket feed.
_MARKET_PROXY_MAP: dict[str, dict] = {
    "^DJI":   {"proxy": "DIA",    "feed": "iex",  "label": "Dow"},
    "^GSPC":  {"proxy": "SPY",    "feed": "iex",  "label": "S&P 500"},
    "^IXIC":  {"proxy": "QQQ",    "feed": "iex",  "label": "NASDAQ"},
    "^N225":  {"proxy": "EWJ",    "feed": "iex",  "label": "Tokyo"},
    "^HSI":   {"proxy": "EWH",    "feed": "iex",  "label": "HK"},
    "^FTSE":  {"proxy": "EWU",    "feed": "iex",  "label": "London"},
    "^GDAXI": {"proxy": "EWG",    "feed": "iex",  "label": "Frankfurt"},
    "^TNX":   {"proxy": "TLT",    "feed": "iex",  "label": "10-Year Yield"},
    "EUR=X":  {"proxy": "eurusd", "feed": "fx",   "label": "Euro"},
    "JPY=X":  {"proxy": "usdjpy", "feed": "fx",   "label": "Yen"},
    "CL=F":   {"proxy": "USO",    "feed": "iex",  "label": "Oil"},
    "GC=F":   {"proxy": "GLD",    "feed": "iex",  "label": "Gold"},
}

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

        self._yahoo = YahooProvider()

        # ── Caches ──────────────────────────────────────────────────
        self._iex_cache: dict[str, dict] = {}  # ticker → normalized quote dict
        self._fx_cache: dict[str, dict] = {}   # ticker → {midPrice, bidPrice, askPrice, prevClose}

        # Track the current day for synthetic forex prevClose
        self._fx_prev_close: dict[str, float] = {}  # ticker → first midPrice of the day
        self._fx_day: dict[str, date] = {}           # ticker → date of prevClose

        # ── Result caches for closed-market optimization ────────────
        self._market_cache: dict | None = None
        self._quotes_cache: dict[str, dict] = {}

        # ── Subscription tracking ──────────────────────────────────
        self._iex_sub_id: str | None = None
        self._fx_sub_id: str | None = None
        self._current_iex_tickers: set[str] = set()
        self._current_fx_tickers: set[str] = set()

        # ── WebSocket references ───────────────────────────────────
        self._iex_ws: Any = None
        self._fx_ws: Any = None

        # ── Lazy initialization flag ───────────────────────────────
        self._started = False

    async def _ensure_started(self) -> None:
        """Starts connection tasks on the active asyncio loop when first accessed."""
        if not self._started:
            self._started = True
            if self._api_key:
                loop = asyncio.get_running_loop()
                loop.create_task(self._iex_connect_loop())
                loop.create_task(self._fx_connect_loop())

    # ────────────────────────────────────────────────────────────────
    # IEX WebSocket
    # ────────────────────────────────────────────────────────────────

    def _get_iex_tickers(self) -> list[str]:
        """Collect all equity tickers we need from the IEX feed."""
        tickers: set[str] = set()
        # Market index proxies
        for info in _MARKET_PROXY_MAP.values():
            if info["feed"] == "iex":
                tickers.add(info["proxy"].upper())
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
        
        threshold = os.environ.get("TIINGO_THRESHOLD", "5")
        try:
            threshold_val = int(threshold)
        except ValueError:
            threshold_val = 5

        subscribe_msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {
                "tickers": tickers,
                "thresholdLevel": threshold_val,
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
    # Forex WebSocket
    # ────────────────────────────────────────────────────────────────

    def _get_fx_tickers(self) -> list[str]:
        """Collect all forex tickers we need."""
        tickers: set[str] = set()
        for info in _MARKET_PROXY_MAP.values():
            if info["feed"] == "fx":
                tickers.add(info["proxy"].lower())
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
        await self._ensure_started()

        # Return cached result when market is closed
        if not builder.is_market_open() and self._market_cache:
            return self._market_cache

        result = await asyncio.to_thread(self._yahoo._fetch_market_sync)
        self._market_cache = result
        return result

    async def fetch_quotes(self, symbols: list[str]) -> list[dict[str, any]]:
        if not symbols:
            return []

        await self._ensure_started()

        # Update subscriptions if watchlist changed
        await self._update_iex_subscriptions()

        # Return cache when market is closed
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

        # Fetch fundamentals from Yahoo in a background thread
        yahoo_quotes = {}
        try:
            yahoo_quotes = await asyncio.to_thread(
                self._yahoo._fetch_raw_quotes, symbols, True
            )
        except Exception as e:
            print(f"[tiingo-ws] Error fetching fundamentals from Yahoo: {e}", file=sys.stderr)

        results = []
        for sym in symbols:
            sym_upper = sym.upper()
            try:
                quote = self._iex_cache.get(sym_upper)
                y_quote = yahoo_quotes.get(sym_upper)

                if not quote and y_quote:
                    # Fallback to Yahoo quote if no WebSocket tick has arrived yet
                    quote = y_quote
                elif quote and y_quote:
                    # Overlay fundamentals on the IEX quote
                    quote["low_52w"] = y_quote.get("low_52w")
                    quote["high_52w"] = y_quote.get("high_52w")
                    quote["avg_volume"] = y_quote.get("avg_volume")
                    quote["pe_ratio"] = y_quote.get("pe_ratio")
                    quote["dividend_rate"] = y_quote.get("dividend_rate")
                    quote["dividend_yield"] = y_quote.get("dividend_yield")
                    quote["market_cap"] = y_quote.get("market_cap")

                if quote:
                    quote["history"] = y_quote.get("history", []) if y_quote else []
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
