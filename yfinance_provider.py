import sys
import yfinance as yf

# ── Cache ────────────────────────────────────────────────────────
_market_cache = None
_quotes_cache = {}

MARKET_TICKERS = {
    "Dow":      "^DJI",
    "Nasdaq":   "^IXIC",
    "S&P 500":  "^GSPC",
    "Russell":  "^RUT",
    "10Y Yield": "^TNX",
    "Oil":      "CL=F",
    "Gold":     "GC=F",
    "EUR/USD":  "EURUSD=X",
    "BTC":      "BTC-USD",
    "VIX":      "^VIX",
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

def fetch_market():
    global _market_cache
    symbols = list(MARKET_TICKERS.values())
    names = list(MARKET_TICKERS.keys())
    indices = []

    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym, name in zip(symbols, names):
            try:
                info = tickers.tickers[sym].fast_info
                price = info.get("lastPrice", 0)
                prev = info.get("previousClose", 0)

                if prev and prev != 0:
                    change_pct = ((price - prev) / prev) * 100
                else:
                    change_pct = 0.0

                indices.append({
                    "name": name,
                    "value": _fmt_number(price),
                    "change": f"{change_pct:+.2f}",
                })
            except Exception:
                indices.append({
                    "name": name,
                    "value": "—",
                    "change": "0.00",
                })

        from datetime import datetime
        import pytz

        et = pytz.timezone("US/Eastern")
        now_et = datetime.now(et)
        hour = now_et.hour
        weekday = now_et.weekday()
        is_open = (weekday < 5) and (9 <= hour < 16)

        result = {"indices": indices, "is_open": is_open}
        _market_cache = result
        return result

    except Exception as e:
        print(f"[stiq] Market fetch error (yfinance): {e}", file=sys.stderr)
        if _market_cache:
            return _market_cache
        return {"indices": [], "is_open": False}


def fetch_quotes(quotes):
    global _quotes_cache
    if not quotes:
        return []

    results = []
    try:
        tickers = yf.Tickers(" ".join(quotes))
        for sym in quotes:
            try:
                t = tickers.tickers[sym]
                info = t.fast_info

                price = info.get("lastPrice", 0)
                prev = info.get("previousClose", 0)
                change = price - prev if prev else 0
                change_pct = ((change / prev) * 100) if prev and prev != 0 else 0

                day_open = info.get("open", 0)
                day_high = info.get("dayHigh", 0)
                day_low = info.get("dayLow", 0)
                volume = info.get("lastVolume", 0)

                hist = t.history(period="1mo")
                history = []
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    history = [round(float(c), 2) for c in hist["Close"].tolist()]

                row = {
                    "quote": sym.upper(),
                    "last": _fmt_price(price),
                    "change": f"{change:+.2f}",
                    "changePct": f"{change_pct:+.2f}",
                    "open": _fmt_price(day_open),
                    "high": _fmt_price(day_high),
                    "low": _fmt_price(day_low),
                    "volume": _fmt_volume(volume),
                    "history": history,
                }
                results.append(row)
                _quotes_cache[sym] = row

            except Exception as e:
                print(f"[stiq] Quote error for {sym} (yfinance): {e}", file=sys.stderr)
                if sym in _quotes_cache:
                    results.append(_quotes_cache[sym])

    except Exception as e:
        print(f"[stiq] Quotes fetch error (yfinance): {e}", file=sys.stderr)
        for sym in quotes:
            if sym in _quotes_cache:
                results.append(_quotes_cache[sym])

    return results
