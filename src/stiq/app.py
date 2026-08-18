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
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from stiq.builder import QuoteBuilder
from stiq.cache import CacheManager
from stiq.config import ConfigManager
from stiq.events import EventBus
from stiq.provider import DataProvider, create_provider
from stiq.schemas import (
    TiingoUsage,
    UnifiedQuote,
    WatchlistAddRequest,
    WatchlistConfig,
    WatchlistIntervalRequest,
    WatchlistRemoveRequest,
)
from stiq.tiingo_usage import TiingoUsageTracker


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


# --- Dependencies ---


def get_config_dep(request: Request) -> ConfigManager:
    return request.app.state.config


def get_provider_dep(request: Request) -> DataProvider:
    return request.app.state.provider


def get_event_bus_dep(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_usage_tracker_dep(request: Request) -> TiingoUsageTracker:
    return request.app.state.usage_tracker


# --- Lifecycle Management ---


def launch_app_window(url: str) -> None:
    """Try to launch an app-like window using Chrome/Edge, fallback to default browser."""
    executables = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
        "microsoft-edge",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]

    app_cmd = None
    for exe in executables:
        if shutil.which(exe) or os.path.exists(exe):
            app_cmd = shutil.which(exe) or exe
            break

    if app_cmd:
        try:
            print(f"[stiq] Launching app window using {app_cmd}…")
            subprocess.Popen(
                [app_cmd, f"--app={url}", "--window-size=1280,720"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception as e:
            print(f"[stiq] Failed to launch app window: {e}")

    print("[stiq] Chrome/Edge not found, falling back to default browser…")
    webbrowser.open(url)


async def background_poller(
    config_manager: ConfigManager,
    provider: DataProvider,
    event_bus: EventBus,
    builder: QuoteBuilder,
):
    """Periodically fetches market, history, and polling quotes, pushing them to EventBus."""
    last_history_fetch = None
    while True:
        try:
            if config_manager.watchlist:
                today_str = datetime.now().strftime("%Y-%m-%d")
                if last_history_fetch != today_str and builder.is_market_open():
                    hist = await provider.fetch_history(config_manager.watchlist)
                    event_bus.publish("history", hist)
                    last_history_fetch = today_str

                if builder.is_market_open():
                    mkt = await provider.fetch_market()
                    event_bus.publish("market", mkt)

                    if config_manager.quotes_provider != "tiingo":
                        quotes = await provider.fetch_quotes(config_manager.watchlist)
                        q_list = []
                        for sym in config_manager.watchlist:
                            q = quotes.get(sym.upper())
                            if q:
                                q["quote"] = sym.upper()
                                q_list.append(q)
                        if q_list:
                            event_bus.publish("quotes", q_list)
        except Exception as e:
            print(f"[stiq] Poller error: {e}", file=sys.stderr)

        sleep_secs = (
            300
            if config_manager.quotes_provider == "tiingo"
            else config_manager.poll_interval_secs
        )
        await asyncio.sleep(sleep_secs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Filter out favicon.ico requests from uvicorn logs
    import logging

    class EndpointFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "GET /favicon.ico" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

    config_manager = ConfigManager()
    event_bus = EventBus()
    usage_tracker = TiingoUsageTracker(event_bus)
    cache_manager = CacheManager()
    builder = QuoteBuilder()
    provider = create_provider(
        config_manager, event_bus, usage_tracker, cache_manager, builder
    )

    app.state.config = config_manager
    app.state.event_bus = event_bus
    app.state.usage_tracker = usage_tracker
    app.state.cache = cache_manager
    app.state.builder = builder
    app.state.provider = provider
    app.state.shutdown_timer = None

    # Startup — launch the Chrome app window after a brief delay
    # so Uvicorn can finish the lifespan and start accepting requests
    url = f"http://127.0.0.1:{app.state.port}/index.html"
    print(f"[stiq] Starting application on {url}")

    async def wait_and_launch():  # Poll the server until it responds, meaning Uvicorn is fully up

        # Poll the server until it responds, meaning Uvicorn is fully up
        for _ in range(50):
            try:
                # Send a quick request to see if the server responds
                await asyncio.to_thread(urllib.request.urlopen, url, timeout=0.5)
                break
            except urllib.error.HTTPError:
                # Server is up and responded with an HTTP status code (e.g., 404, 500)
                break
            except Exception:
                # Server is not up yet, wait 0.1s and try again
                await asyncio.sleep(0.1)

        launch_app_window(url)

    asyncio.create_task(wait_and_launch())

    poller_task = asyncio.create_task(
        background_poller(config_manager, provider, event_bus, builder)
    )
    usage_task = asyncio.create_task(usage_tracker.periodic_save(60))

    yield

    # Shutdown
    usage_tracker.save()
    poller_task.cancel()
    usage_task.cancel()
    try:
        await poller_task
        await usage_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Stiq API", lifespan=lifespan)
app.state.port = 8123

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{app.state.port}",
        f"http://localhost:{app.state.port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # Log the error in a real application
    print(f"Unhandled exception: {exc}", file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )


# --- API Endpoints ---


@app.get("/api/watchlist", response_model=WatchlistConfig)
async def get_watchlist(
    config: Annotated[ConfigManager, Depends(get_config_dep)],
):
    return config.get_config()


@app.get("/api/tiingo_usage", response_model=TiingoUsage)
async def get_tiingo_usage(
    usage_tracker: Annotated[TiingoUsageTracker, Depends(get_usage_tracker_dep)],
):
    return usage_tracker.get_usage_dict()


@app.get("/api/market")
async def get_market(
    provider: Annotated[DataProvider, Depends(get_provider_dep)],
):
    return await provider.fetch_market()


@app.get("/api/quotes", response_model=list[UnifiedQuote])
async def get_quotes(
    symbols: Annotated[str, Query(min_length=1)],
    provider: Annotated[DataProvider, Depends(get_provider_dep)],
):
    """Fetch quotes for symbols, merging realtime data with historical data."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    realtime_data = await provider.fetch_quotes(symbol_list)
    history_data = await provider.fetch_history(symbol_list)

    data = []
    for sym in symbol_list:
        rt = realtime_data.get(sym, {})
        hi = history_data.get(sym, {})
        merged = {**hi, **rt}
        if not merged.get("quote"):
            merged["quote"] = sym
        data.append(merged)

    return data


@app.get("/api/history")
async def get_history(
    symbols: str,
    provider: Annotated[DataProvider, Depends(get_provider_dep)],
):
    """Fetch history for symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    history_data = await provider.fetch_history(symbol_list)
    return history_data


@app.post("/api/watchlist/add")
async def add_to_watchlist(
    request: Request,
    config: Annotated[ConfigManager, Depends(get_config_dep)],
    payload: Annotated[WatchlistAddRequest | None, Body()] = None,
    symbol: str | None = None,
):
    # Accept symbol from JSON body, query param, or form field
    if symbol is None and payload is None:
        # Parse form data (e.g. from URL-encoded POST)
        form = await request.form()
        symbol = form.get("symbol")
    symbol = (symbol or (payload.symbol if payload else "")).strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    if not config.add_symbol(symbol):
        raise HTTPException(
            status_code=400, detail="Symbol already in watchlist or invalid"
        )
    return {"success": True, "symbol": symbol}


@app.post("/api/watchlist/remove")
async def remove_from_watchlist(
    request: Request,
    config: Annotated[ConfigManager, Depends(get_config_dep)],
    payload: Annotated[WatchlistRemoveRequest | None, Body()] = None,
    symbol: str | None = None,
):
    if symbol is None and payload is None:
        form = await request.form()
        symbol = form.get("symbol")
    symbol_str = (symbol or (payload.symbol if payload else "")).strip().upper()
    if not symbol_str:
        raise HTTPException(status_code=400, detail="Symbol is required")

    removed = []
    not_found = []
    for s in symbol_str.split(","):
        s = s.strip()
        if not s:
            continue
        if config.remove_symbol(s):
            removed.append(s)
        else:
            not_found.append(s)

    if not removed and not_found:
        raise HTTPException(status_code=400, detail="Symbols not in watchlist")
    return {"success": True, "removed": removed, "not_found": not_found}


@app.post("/api/watchlist/interval")
async def update_interval(
    request: Request,
    config: Annotated[ConfigManager, Depends(get_config_dep)],
    payload: Annotated[WatchlistIntervalRequest | None, Body()] = None,
    seconds: str | None = None,
):
    # Accept seconds from JSON body, query param, or form field
    if seconds is None and payload is None:
        form = await request.form()
        seconds = form.get("seconds")
    seconds_val = int(seconds) if seconds else payload.seconds if payload else 300
    config.set_interval(seconds_val)
    return {"success": True, "interval": seconds_val}


async def delayed_exit(
    delay_secs: float, usage_tracker: TiingoUsageTracker | None = None
):
    await asyncio.sleep(delay_secs)
    if usage_tracker:
        try:
            usage_tracker.save()
        except Exception as e:
            print(f"[stiq] Error saving usage tracker: {e}", file=sys.stderr)
    os._exit(0)


@app.get("/api/stream")
async def stream_events(
    request: Request,
    event_bus: Annotated[EventBus, Depends(get_event_bus_dep)],
):
    # Cancel any pending shutdown timer — a client just connected
    timer = getattr(request.app.state, "shutdown_timer", None)
    if timer and not timer.done():
        print("[stiq] Client reconnected, cancelling pending shutdown.")
        timer.cancel()
        request.app.state.shutdown_timer = None

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        event_bus.subscribe(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"data": json.dumps(event)}
                except TimeoutError:
                    yield {"comment": "ping"}
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(queue)
            if len(event_bus.subscribers) == 0:
                print("[stiq] Last SSE client disconnected. Shutting down in 3s...")
                usage_tracker = getattr(request.app.state, "usage_tracker", None)
                request.app.state.shutdown_timer = asyncio.create_task(
                    delayed_exit(3.0, usage_tracker)
                )

    return EventSourceResponse(event_generator())


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


# --- Static Files ---


def _find_web_dir() -> str:
    """Locate the web/ directory for serving static files.

    In development web/ lives at the project root (sibling of src/).
    In a PyInstaller bundle, web/ is copied into the bundle root,
    which is sys._MEIPASS.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller: web/ is at the bundle root
        candidate = os.path.join(sys._MEIPASS, "web")
        if os.path.isdir(candidate):
            return candidate
    # Development: check relative to module first, then fallback to cwd
    candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web")),
        os.path.abspath(os.path.join(os.getcwd(), "web")),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    # Fallback: look for web/ in the bundle root
    return resource_path("web")


_static_dir = _find_web_dir()
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")

# --- Main Entrypoint for running with uvicorn ---


def run_app():
    # Find the absolute path to the web directory
    # Since we'll be running this from the project root, "web" should be fine.
    uvicorn.run(app, host="127.0.0.1", port=8123)


if __name__ == "__main__":
    run_app()
