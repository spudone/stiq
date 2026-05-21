# provider_utils.py
# Shared formatting and configuration utilities for Stiq data providers.

import os
import json
from datetime import date

CACHE_DIR = os.path.expanduser("~/.stiq")
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")

# ── History Cache (once per symbol per day) ──────────────────────
_history_cache = {}   # {symbol: (date_str, [floats])}

def _load_cache():
    global _history_cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                for sym, entry in data.items():
                    if isinstance(entry, dict) and "date" in entry and "history" in entry:
                        _history_cache[sym] = (entry["date"], entry["history"])
        except Exception:
            pass

def _save_cache():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        data = {}
        for sym, (d_str, history) in _history_cache.items():
            data[sym] = {"date": d_str, "history": history}
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# Initialize cache on module import
_load_cache()

def get_cached_history(sym):
    """Returns cached history list if it was fetched today, else None."""
    entry = _history_cache.get(sym)
    today_str = date.today().isoformat()
    if entry and entry[0] == today_str:
        return entry[1]
    return None

def set_cached_history(sym, history):
    """Stores history for a symbol, tagged with today's date, and saves to disk."""
    today_str = date.today().isoformat()
    _history_cache[sym] = (today_str, history)
    _save_cache()

MARKET_TICKERS = {
    # Row 1
    "Dow":           "^DJI",
    "S&P 500":       "^GSPC",
    "NASDAQ":        "^IXIC",
    # Row 2
    "Tokyo":         "^N225",
    "HK":            "^HSI",
    "London":        "^FTSE",
    "Frankfurt":     "^GDAXI",
    # Row 3
    "10-Year Yield": "^TNX",
    "Euro":          "EUR=X",
    "Yen":           "JPY=X",
    "Oil":           "CL=F",
    "Gold":          "GC=F",
}


def _fmt_price(val):
    try:
        return f"{float(val):,.2f}"
    except (TypeError, ValueError):
        return "—"

def _fmt_number(val):
    try:
        val = float(val)
        if abs(val) >= 1000:
            return f"{val:,.2f}"
        elif abs(val) >= 1:
            return f"{val:.2f}"
        else:
            return f"{val:.4f}"
    except (TypeError, ValueError):
        return "—"

def _fmt_volume(val):
    try:
        val = float(val)
        if val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.1f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.1f}K"
        else:
            return str(int(val))
    except (TypeError, ValueError):
        return "—"

def _fmt_large_val(val):
    try:
        v = float(val)
        unit = ""
        if v >= 1.0e12:
            v /= 1.0e12
            unit = "T"
        elif v >= 1.0e9:
            v /= 1.0e9
            unit = "B"
        elif v >= 1.0e6:
            v /= 1.0e6
            unit = "M"
        elif v >= 1.0e5:
            v /= 1.0e3
            unit = "K"
        else:
            unit = ""
        return f"{v:.3f}{unit}"
    except (TypeError, ValueError):
        return "—"

def build_market_index(name, quote):
    """Builds a single market index entry from raw Yahoo API data."""
    price = quote.get("regularMarketPrice", 0)
    prev = quote.get("regularMarketPreviousClose", 0)

    change_pct = quote.get("regularMarketChangePercent")
    if change_pct is None:
        if prev and prev != 0:
            change_pct = ((price - prev) / prev) * 100
        else:
            change_pct = 0.0

    return {
        "name": name,
        "value": _fmt_number(price),
        "change": f"{change_pct:+.2f}",
    }

def build_quote_row(sym, quote):
    """
    Builds a unified UI quote row dictionary from raw Yahoo API data.
    Both providers map their data to this schema before calling this function.
    History is expected as a 'history' key in the quote dict.
    """
    price = quote.get("regularMarketPrice", 0)
    prev = quote.get("regularMarketPreviousClose", 0)
    change = price - prev if prev else 0
    
    change_pct = quote.get("regularMarketChangePercent")
    if change_pct is None:
        change_pct = ((change / prev) * 100) if prev and prev != 0 else 0

    day_open = quote.get("regularMarketOpen", 0)
    day_high = quote.get("regularMarketDayHigh", 0)
    day_low = quote.get("regularMarketDayLow", 0)
    volume = quote.get("regularMarketVolume", 0)

    yield_val = quote.get("trailingAnnualDividendYield")

    return {
        "quote": sym.upper(),
        "last": _fmt_price(price),
        "change": f"{change:+.2f}",
        "changePct": f"{change_pct:+.2f}",
        "open": _fmt_price(day_open),
        "high": _fmt_price(day_high),
        "low": _fmt_price(day_low),
        "volume": _fmt_volume(volume),
        "low52": _fmt_price(quote.get("fiftyTwoWeekLow")),
        "high52": _fmt_price(quote.get("fiftyTwoWeekHigh")),
        "avgVolume": _fmt_volume(quote.get("averageDailyVolume10Day")),
        "peRatio": _fmt_number(quote.get("trailingPE")),
        "dividend": _fmt_price(quote.get("trailingAnnualDividendRate")),
        "yield": f"{float(yield_val) * 100:.2f}" if yield_val is not None else "—",
        "marketCap": _fmt_large_val(quote.get("marketCap")),
        "currency": quote.get("currency", "USD"),
        "history": quote.get("history", []),
    }

def is_market_open():
    """Returns True if US markets are currently open."""
    from datetime import datetime
    import pytz
    et = pytz.timezone("US/Eastern")
    now_et = datetime.now(et)
    return (now_et.weekday() < 5) and (9 <= now_et.hour < 16)
