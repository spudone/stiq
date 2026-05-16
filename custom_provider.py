import sys
import json
import re
import urllib.request
import urllib.parse
import gzip
import io
from http.cookiejar import CookieJar
from datetime import datetime
import pytz

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

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class YahooProvider:
    def __init__(self):
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.opener.addheaders = [('User-Agent', _USER_AGENT)]
        self.crumb = None
        self.initialized = False

    def _read_response(self, resp):
        data = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
                data = f.read()
        return data.decode('utf-8')

    def get_a1_cookie(self):
        for c in self.cookie_jar:
            if c.name == 'A1':
                return f"{c.name}={c.value}"
        return None

    def initialize(self):
        if self.initialized:
            return True

        # 1. Fetch Cookies
        req = urllib.request.Request("https://finance.yahoo.com/", headers={
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Upgrade-Insecure-Requests': '1'
        })
        try:
            resp = self.opener.open(req)
            html = self._read_response(resp)
        except Exception as e:
            print(f"[stiq-custom] Error fetching initial cookies: {e}", file=sys.stderr)
            return False

        a1 = self.get_a1_cookie()
        if not a1:
            # EU Consent Flow
            url = resp.url
            try:
                session_id_match = re.search(r'sessionId=(?:([A-Za-z0-9_-]*))', url)
                csrf_token_match = re.search(r'gcrumb=(?:([A-Za-z0-9_]*))', url)
                
                if session_id_match and csrf_token_match:
                    session_id = session_id_match.group(1)
                    csrf_token = csrf_token_match.group(1)
                    
                    form_data = urllib.parse.urlencode({
                        'csrfToken': csrf_token,
                        'sessionId': session_id,
                        'namespace': 'yahoo',
                        'agree': 'agree'
                    }).encode()
                    
                    req2 = urllib.request.Request(f"https://consent.yahoo.com/v2/collectConsent?sessionId={session_id}", data=form_data, headers={
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Origin': 'https://consent.yahoo.com',
                        'Referer': url
                    })
                    self.opener.open(req2)
                    a1 = self.get_a1_cookie()
            except Exception as e:
                print(f"[stiq-custom] Error in EU consent flow: {e}", file=sys.stderr)
                return False

        if not a1:
            # Sometimes Yahoo gives other cookies but works without A1. We'll proceed with whatever cookies we have.
            pass

        print(f"[stiq-custom] Cookies acquired: {[c.name for c in self.cookie_jar]}", file=sys.stderr)

        # 2. Fetch Crumb
        req_crumb = urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb", headers={
            'Accept': '*/*',
            'Accept-Encoding': 'gzip',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Content-Type': 'text/plain',
            'Host': 'query1.finance.yahoo.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'TE': 'trailers',
        })
        try:
            resp = self.opener.open(req_crumb)
            self.crumb = self._read_response(resp)
            self.initialized = True
            return True
        except Exception as e:
            print(f"[stiq-custom] Error fetching crumb: {e}", file=sys.stderr)
            return False

    def get_quotes(self, symbols):
        if not self.initialize() or not symbols:
            return {}
        
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?crumb={self.crumb}&symbols={','.join(symbols)}"
        
        req = urllib.request.Request(url, headers={
            'Accept': '*/*',
            'Accept-Encoding': 'gzip',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Host': 'query1.finance.yahoo.com',
            'Origin': 'https://finance.yahoo.com',
            'Referer': 'https://finance.yahoo.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'TE': 'trailers',
        })
        try:
            resp = self.opener.open(req)
            data = json.loads(self._read_response(resp))
            results = data.get('quoteResponse', {}).get('result', [])
            return {r['symbol']: r for r in results}
        except Exception as e:
            print(f"[stiq-custom] Error fetching quote data: {e}", file=sys.stderr)
            return {}

    def get_history(self, symbol):
        if not self.initialize():
            return []
        
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo&crumb={self.crumb}"
        req = urllib.request.Request(url, headers={
            'Accept': '*/*',
            'Accept-Encoding': 'gzip',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Host': 'query1.finance.yahoo.com',
            'Origin': 'https://finance.yahoo.com',
            'Referer': 'https://finance.yahoo.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'TE': 'trailers',
        })
        try:
            resp = self.opener.open(req)
            data = json.loads(self._read_response(resp))
            result = data.get('chart', {}).get('result', [])
            if result:
                indicators = result[0].get('indicators', {}).get('quote', [])
                if indicators and 'close' in indicators[0]:
                    closes = indicators[0]['close']
                    return [round(float(c), 2) for c in closes if c is not None]
        except Exception as e:
            print(f"[stiq-custom] Error fetching history for {symbol}: {e}", file=sys.stderr)
        return []

_provider = YahooProvider()

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
        quotes = _provider.get_quotes(symbols)

        for sym, name in zip(symbols, names):
            try:
                info = quotes.get(sym, {})
                price = info.get("regularMarketPrice", 0)
                prev = info.get("regularMarketPreviousClose", 0)

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

        et = pytz.timezone("US/Eastern")
        now_et = datetime.now(et)
        hour = now_et.hour
        weekday = now_et.weekday()
        is_open = (weekday < 5) and (9 <= hour < 16)

        result = {"indices": indices, "is_open": is_open}
        _market_cache = result
        return result

    except Exception as e:
        print(f"[stiq] Market fetch error (custom): {e}", file=sys.stderr)
        if _market_cache:
            return _market_cache
        return {"indices": [], "is_open": False}


def fetch_quotes(symbols):
    global _quotes_cache
    if not symbols:
        return []

    results = []
    try:
        quotes = _provider.get_quotes(symbols)

        for sym in symbols:
            try:
                info = quotes.get(sym, {})
                
                price = info.get("regularMarketPrice", 0)
                prev = info.get("regularMarketPreviousClose", 0)
                change = price - prev if prev else 0
                change_pct = info.get("regularMarketChangePercent", 0)

                day_open = info.get("regularMarketOpen", 0)
                day_high = info.get("regularMarketDayHigh", 0)
                day_low = info.get("regularMarketDayLow", 0)
                volume = info.get("regularMarketVolume", 0)

                history = _provider.get_history(sym)

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
                print(f"[stiq] Quote error for {sym} (custom): {e}", file=sys.stderr)
                if sym in _quotes_cache:
                    results.append(_quotes_cache[sym])

    except Exception as e:
        print(f"[stiq] Quotes fetch error (custom): {e}", file=sys.stderr)
        for sym in symbols:
            if sym in _quotes_cache:
                results.append(_quotes_cache[sym])

    return results
