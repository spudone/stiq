import asyncio
import json
import os
import shutil
import subprocess
import sys
import webbrowser
import uvicorn
from contextlib import asynccontextmanager
from fastapi import Body, FastAPI, HTTPException, Request, Query, Response
from typing import List
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from stiq.schemas import (
    WatchlistConfig,
    TiingoUsage,
    WatchlistAddRequest,
    WatchlistRemoveRequest,
    WatchlistIntervalRequest,
    UnifiedQuote,
)
from .config import init_config, get_config
from .events import init_event_bus, get_event_bus
from .tiingo_usage import init_usage_tracker, get_usage_tracker
from stiq.provider import get_provider, DataProvider
from stiq.config import ConfigManager
from stiq.events import EventBus
from stiq.tiingo_usage import TiingoUsageTracker
from stiq.builder import builder
from datetime import datetime


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


# --- Lifecycle Management ---

# Global components
config_manager: ConfigManager | None = None
event_bus: EventBus | None = None
usage_tracker: TiingoUsageTracker | None = None
provider: DataProvider | None = None


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


async def background_poller():
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

    global config_manager, event_bus, usage_tracker, provider
    init_config()
    init_event_bus()
    init_usage_tracker()

    config_manager = get_config()
    event_bus = get_event_bus()
    usage_tracker = get_usage_tracker()
    provider = get_provider()

    # Startup — launch the Chrome app window before starting background tasks
    url = f"http://127.0.0.1:{app.state.port}/index.html"
    launch_app_window(url)
    print(f"[stiq] Starting application on {url}")

    poller_task = asyncio.create_task(background_poller())
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
async def get_watchlist():
    return config_manager.get_config()


@app.get("/api/tiingo_usage", response_model=TiingoUsage)
async def get_tiingo_usage():
    return usage_tracker.get_usage_dict()


@app.get("/api/market")
async def get_market():
    return await provider.fetch_market()


@app.get("/api/quotes", response_model=List[UnifiedQuote])
async def get_quotes(symbols: str = Query(..., min_length=1)):
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
async def get_history(symbols: str):
    """Fetch history for symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    history_data = await provider.fetch_history(symbol_list)
    return history_data


@app.post("/api/watchlist/add")
async def add_to_watchlist(
    request: Request,
    payload: WatchlistAddRequest | None = Body(default=None),
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
    if not config_manager.add_symbol(symbol):
        raise HTTPException(
            status_code=400, detail="Symbol already in watchlist or invalid"
        )
    return {"success": True, "symbol": symbol}


@app.post("/api/watchlist/remove")
async def remove_from_watchlist(
    request: Request,
    payload: WatchlistRemoveRequest | None = Body(default=None),
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
        if config_manager.remove_symbol(s):
            removed.append(s)
        else:
            not_found.append(s)

    if not removed and not_found:
        raise HTTPException(status_code=400, detail="Symbols not in watchlist")
    return {"success": True, "removed": removed, "not_found": not_found}


@app.post("/api/watchlist/interval")
async def update_interval(
    request: Request,
    payload: WatchlistIntervalRequest | None = Body(default=None),
    seconds: str | None = None,
):
    # Accept seconds from JSON body, query param, or form field
    if seconds is None and payload is None:
        form = await request.form()
        seconds = form.get("seconds")
    seconds_val = int(seconds) if seconds else payload.seconds if payload else 300
    config_manager.set_interval(seconds_val)
    return {"success": True, "interval": seconds_val}


async def delayed_exit(delay_secs: float):
    await asyncio.sleep(delay_secs)
    os._exit(0)


@app.post("/api/shutdown")
async def shutdown():
    print("[stiq] Shutting down...")
    usage_tracker.save()
    asyncio.create_task(delayed_exit(0.5))
    return {"success": True}


@app.get("/api/stream")
async def stream_events():
    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        event_bus.subscribe(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"comment": "ping"}
        except asyncio.CancelledError:
            event_bus.unsubscribe(queue)
            raise

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
