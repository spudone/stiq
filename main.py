"""
Stiq — High-density browser-based stock ticker.
Lightweight HTTP server with system browser, modular data providers.
"""

import sys
import os
import json
import importlib
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ── Data Provider ────────────────────────────────────────────────

if os.environ.get("USE_YFINANCE") == "1":
    provider = importlib.import_module("yfinance_provider")
else:
    try:
        provider = importlib.import_module("custom_provider")
    except ModuleNotFoundError:
        provider = importlib.import_module("yfinance_provider")


# ── API Request Handler ─────────────────────────────────────────

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class StiqHandler(SimpleHTTPRequestHandler):
    """Serves static files from web/ and handles API routes."""

    def __init__(self, *args, **kwargs):
        web_dir = resource_path("web")
        super().__init__(*args, directory=web_dir, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/market":
            self._json_response(provider.fetch_market())
        elif parsed.path == "/api/quotes":
            qs = parse_qs(parsed.query)
            symbols = qs.get("symbols", [""])[0]
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
            self._json_response(provider.fetch_quotes(symbol_list))
        elif parsed.path == "/api/shutdown":
            self.send_response(200)
            self.end_headers()
            print("\n[stiq] Browser window closed. Shutting down…")
            threading.Thread(target=lambda: os._exit(0)).start()
        else:
            # Serve static files from web/
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/shutdown":
            self.send_response(200)
            self.end_headers()
            print("\n[stiq] Browser window closed. Shutting down…")
            threading.Thread(target=lambda: os._exit(0)).start()

    def _json_response(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Silence per-request logging
        pass

import subprocess
import shutil

def launch_app_window(url):
    """Try to launch an app-like window using Chrome/Edge, fallback to default browser."""
    executables = [
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge", "microsoft-edge",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
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
                stderr=subprocess.DEVNULL
            )
            return
        except Exception as e:
            print(f"[stiq] Failed to launch app window: {e}")
            
    print("[stiq] Chrome/Edge not found, falling back to default browser…")
    webbrowser.open(url)

# ── Application Entry ───────────────────────────────────────────

def main():
    port = 8123
    server = HTTPServer(("127.0.0.1", port), StiqHandler)
    url = f"http://127.0.0.1:{port}/index.html"

    print(f"[stiq] Starting application on {url}")

    # Run the server in a background thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Launch Chrome app window or fallback
    launch_app_window(url)

    # Keep running until interrupted
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\n[stiq] Shutting down…")
        server.shutdown()

if __name__ == "__main__":
    main()
