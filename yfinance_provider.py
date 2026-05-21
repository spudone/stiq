import sys
import yfinance as yf

# ── Cache ────────────────────────────────────────────────────────
_market_cache = None
_quotes_cache = {}

from provider_utils import MARKET_TICKERS, build_quote_row, build_market_index, is_market_open, get_cached_history, set_cached_history

def fetch_market():
    global _market_cache
    symbols = list(MARKET_TICKERS.values())
    names = list(MARKET_TICKERS.keys())

    try:
        tickers = yf.Tickers(" ".join(symbols))
        quotes = _map_quotes(tickers, symbols)
        indices = []

        for sym, name in zip(symbols, names):
            try:
                indices.append(build_market_index(name, quotes.get(sym, {})))
            except Exception:
                indices.append({"name": name, "value": "—", "change": "0.00"})

        result = {"indices": indices, "is_open": is_market_open()}
        _market_cache = result
        return result

    except Exception as e:
        print(f"[stiq] Market fetch error (yfinance): {e}", file=sys.stderr)
        if _market_cache:
            return _market_cache
        return {"indices": [], "is_open": False}

def fetch_quotes(symbols):
    global _quotes_cache
    if not symbols:
        return []

    results = []
    try:
        tickers = yf.Tickers(" ".join(symbols))
        quotes = _map_quotes(tickers, symbols, include_history=True)
        
        for sym in symbols:
            try:
                row = build_quote_row(sym, quotes.get(sym, {}))
                results.append(row)
                _quotes_cache[sym] = row

            except Exception as e:
                print(f"[stiq] Quote error for {sym} (yfinance): {e}", file=sys.stderr)
                if sym in _quotes_cache:
                    results.append(_quotes_cache[sym])

    except Exception as e:
        print(f"[stiq] Quotes fetch error (yfinance): {e}", file=sys.stderr)
        for sym in symbols:
            if sym in _quotes_cache:
                results.append(_quotes_cache[sym])

    return results

def _map_quotes(tickers, symbols, include_history=False):
    mapped = {}
    for sym in symbols:
        try:
            t = tickers.tickers[sym]
            info = t.fast_info
            
            price = info.get("lastPrice", 0)
            prev = info.get("previousClose", 0)

            t_info = {}
            try:
                t_info = t.info
            except Exception:
                pass

            mapped[sym] = {
                "regularMarketPrice": price,
                "regularMarketPreviousClose": prev,
                "regularMarketOpen": info.get("open", 0),
                "regularMarketDayHigh": info.get("dayHigh", 0),
                "regularMarketDayLow": info.get("dayLow", 0),
                "regularMarketVolume": info.get("lastVolume", 0),
                "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow") or t_info.get("fiftyTwoWeekLow"),
                "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh") or t_info.get("fiftyTwoWeekHigh"),
                "averageDailyVolume10Day": info.get("averageVolume10Day") or t_info.get("averageDailyVolume10Day"),
                "trailingPE": t_info.get("trailingPE"),
                "trailingAnnualDividendRate": t_info.get("dividendRate") or t_info.get("trailingAnnualDividendRate"),
                "trailingAnnualDividendYield": t_info.get("dividendYield") or t_info.get("trailingAnnualDividendYield"),
                "marketCap": info.get("marketCap") or t_info.get("marketCap"),
                "currency": info.get("currency") or t_info.get("currency", "USD"),
            }

            if include_history:
                cached = get_cached_history(sym)
                if cached is not None:
                    mapped[sym]["history"] = cached
                else:
                    hist = t.history(period="1mo")
                    h = []
                    if hist is not None and not hist.empty and "Close" in hist.columns:
                        h = [round(float(c), 2) for c in hist["Close"].tolist()]
                    set_cached_history(sym, h)
                    mapped[sym]["history"] = h

        except Exception:
            mapped[sym] = {}
    return mapped