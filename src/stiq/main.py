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
import mimetypes
import os
import shutil
import subprocess
import sys
import webbrowser
import urllib.parse
from datetime import datetime
from stiq.provider import get_provider
from stiq.config import config
from stiq.events import event_bus

provider = get_provider()


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_content_type(file_path):
    """Guess the MIME type of a file path."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


async def send_response(writer, status_code, content_type, body_bytes):
    """Send an HTTP response with CORS headers."""
    status_msg = "OK" if status_code == 200 else ("Created" if status_code == 201 else "Error")
    headers = [
        f"HTTP/1.1 {status_code} {status_msg}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body_bytes)}",
        "Access-Control-Allow-Origin: *",
        "Connection: close",
        "\r\n"
    ]
    try:
        writer.write(("\r\n".join(headers)).encode("utf-8") + body_bytes)
        await writer.drain()
    except Exception:
        pass


async def send_json(writer, data):
    """Send a JSON payload."""
    body = json.dumps(data).encode("utf-8")
    await send_response(writer, 200, "application/json", body)


async def send_error(writer, status_code, message):
    """Send a plain text HTTP error response."""
    body = f"Error {status_code}: {message}".encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} {message}",
        "Content-Type: text/plain",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "\r\n"
    ]
    try:
        writer.write(("\r\n".join(headers)).encode("utf-8") + body)
        await writer.drain()
    except Exception:
        pass


async def delayed_exit(delay):
    """Wait and then shut down the application process."""
    await asyncio.sleep(delay)
    os._exit(0)


async def handle_get(path, qs, writer):
    """Handle GET requests for static assets and API routes."""
    if path == "/api/stream":
        headers = [
            "HTTP/1.1 200 OK",
            "Content-Type: text/event-stream",
            "Cache-Control: no-cache",
            "Connection: keep-alive",
            "Access-Control-Allow-Origin: *",
            "\r\n"
        ]
        try:
            writer.write(("\r\n".join(headers)).encode("utf-8"))
            await writer.drain()
        except Exception:
            return
            
        queue = asyncio.Queue()
        event_bus.subscribe(queue)
        try:
            while True:
                message = await queue.get()
                data_str = json.dumps(message)
                writer.write(f"data: {data_str}\n\n".encode("utf-8"))
                await writer.drain()
        except Exception:
            pass
        finally:
            event_bus.unsubscribe(queue)
            
    elif path == "/api/market":
        data = await provider.fetch_market()
        await send_json(writer, data)
    elif path == "/api/quotes":
        symbols = qs.get("symbols", [""])[0]
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        
        realtime_data = await provider.fetch_quotes(symbol_list)
        history_data = await provider.fetch_history(symbol_list)
        
        data = []
        for sym in symbol_list:
            sym_upper = sym.upper()
            rt = realtime_data.get(sym_upper, {})
            hi = history_data.get(sym_upper, {})
            
            merged = {**hi, **rt}
            if not merged.get("quote"):
                merged["quote"] = sym_upper
            data.append(merged)
            
        await send_json(writer, data)
    elif path == "/api/history":
        symbols = qs.get("symbols", [""])[0]
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        data = await provider.fetch_history(symbol_list)
        await send_json(writer, data)
    elif path == "/api/watchlist":
        await send_json(
            writer,
            {
                "symbols": config.watchlist, 
                "poll_interval_secs": config.poll_interval_secs,
                "provider": config.quotes_provider,
                "market_provider": config.market_provider
            }
        )
    elif path == "/api/shutdown":
        await send_response(writer, 200, "text/plain", b"Shutting down")
        print("\n[stiq] Browser window closed. Shutting down…")
        asyncio.create_task(delayed_exit(0.5))
    else:
        # Serve static files from web/
        if path == "/" or path == "/index.html":
            file_path = resource_path("web/index.html")
        else:
            # Prevent directory traversal
            clean_path = path.lstrip("/")
            file_path = resource_path(os.path.join("web", clean_path))

        # Check path existence
        if not os.path.exists(file_path) or os.path.isdir(file_path):
            await send_error(writer, 404, "Not Found")
            return

        content_type = get_content_type(file_path)
        try:
            with open(file_path, "rb") as f:
                body = f.read()
            await send_response(writer, 200, content_type, body)
        except Exception:
            await send_error(writer, 500, "Internal Server Error")


async def handle_post(path, qs, writer):
    """Handle POST requests for mutating configuration or shutdown."""
    if path == "/api/watchlist/add":
        symbol = qs.get("symbol", [""])[0].strip()
        if symbol:
            config.add(symbol)
            await send_json(writer, {"success": True})
        else:
            await send_error(writer, 400, "Missing symbol parameter")
    elif path == "/api/watchlist/remove":
        symbol = qs.get("symbol", [""])[0].strip()
        if symbol:
            config.remove(symbol)
            await send_json(writer, {"success": True})
        else:
            await send_error(writer, 400, "Missing symbol parameter")
    elif path == "/api/watchlist/interval":
        seconds_str = qs.get("seconds", [""])[0].strip()
        if seconds_str:
            try:
                config.set_interval(int(seconds_str))
                await send_json(writer, {"success": True})
            except ValueError:
                await send_error(writer, 400, "Invalid seconds value")
        else:
            await send_error(writer, 400, "Missing seconds parameter")
    elif path == "/api/shutdown":
        await send_response(writer, 200, "text/plain", b"Shutting down")
        print("\n[stiq] Browser window closed. Shutting down…")
        asyncio.create_task(delayed_exit(0.5))
    else:
        await send_error(writer, 404, "Not Found")


async def handle_client(reader, writer):
    """Asynchronous HTTP request router."""
    try:
        request_line_bytes = await reader.readline()
        if not request_line_bytes:
            return
        request_line = request_line_bytes.decode("utf-8").strip()
        parts = request_line.split()
        if len(parts) < 3:
            return
        method, full_path, _ = parts

        # Read and ignore HTTP request headers
        while True:
            line_bytes = await reader.readline()
            line = line_bytes.decode("utf-8").strip()
            if not line:
                break

        parsed = urllib.parse.urlparse(full_path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if method == "GET":
            await handle_get(path, qs, writer)
        elif method == "POST":
            await handle_post(path, qs, writer)
        else:
            await send_error(writer, 405, "Method Not Allowed")
    except Exception as e:
        print(f"[stiq] Error handling request: {e}", file=sys.stderr)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def launch_app_window(url):
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
            # Run detached and silence Chrome's internal stdout/stderr errors
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


# ── Application Entry ───────────────────────────────────────────


async def background_poller():
    """Periodically fetches market, history, and polling quotes, pushing them to EventBus."""
    last_history_fetch = None
    while True:
        try:
            if config.watchlist:
                today_str = datetime.now().strftime("%Y-%m-%d")
                if last_history_fetch != today_str and builder.is_market_open():
                    hist = await provider.fetch_history(config.watchlist)
                    event_bus.publish("history", hist)
                    last_history_fetch = today_str

                if builder.is_market_open():
                    mkt = await provider.fetch_market()
                    event_bus.publish("market", mkt)

                    if config.quotes_provider != "tiingo":
                        quotes = await provider.fetch_quotes(config.watchlist)
                        q_list = []
                        for sym in config.watchlist:
                            q = quotes.get(sym.upper())
                            if q:
                                q["quote"] = sym.upper()
                                q_list.append(q)
                        if q_list:
                            event_bus.publish("quotes", q_list)
        except Exception as e:
            print(f"[stiq] Poller error: {e}", file=sys.stderr)
        
        sleep_secs = 300 if config.quotes_provider == "tiingo" else config.poll_interval_secs
        await asyncio.sleep(sleep_secs)


async def main_async():
    port = 8123
    server = await asyncio.start_server(handle_client, "127.0.0.1", port)
    url = f"http://127.0.0.1:{port}/index.html"

    print(f"[stiq] Starting application on {url}")

    # Start background poller
    asyncio.create_task(background_poller())

    # Launch Chrome app window or fallback
    launch_app_window(url)

    async with server:
        await server.serve_forever()


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[stiq] Shutting down…")


if __name__ == "__main__":
    main()
