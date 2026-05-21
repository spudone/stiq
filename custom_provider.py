import sys
import json
import urllib.request
import urllib.parse
import gzip
import io
from http.cookiejar import CookieJar

from provider_utils import MARKET_TICKERS, build_quote_row, build_market_index, is_market_open, get_cached_history, set_cached_history

# ── Cache ────────────────────────────────────────────────────────
_market_cache = None
_quotes_cache = {}

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

    def _get_headers(self, content_type='application/json', include_origin=True):
        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Content-Type': content_type,
            'Host': 'query1.finance.yahoo.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'TE': 'trailers',
        }
        if include_origin:
            headers['Origin'] = 'https://finance.yahoo.com'
            headers['Referer'] = 'https://finance.yahoo.com'
        return headers

    def _query_api(self, url, content_type='application/json'):
        req = urllib.request.Request(url, headers=self._get_headers(content_type=content_type))
        resp = self.opener.open(req)
        return json.loads(self._read_response(resp))

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
        try:
            req_crumb = urllib.request.Request(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                headers=self._get_headers(content_type='text/plain', include_origin=False)
            )
            resp = self.opener.open(req_crumb)
            self.crumb = self._read_response(resp)
            self.initialized = True
            return True
        except Exception as e:
            print(f"[stiq-custom] Error fetching crumb: {e}", file=sys.stderr)
            return False

    def get_quotes(self, symbols, include_history=False):
        if not self.initialize() or not symbols:
            return {}
        
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?crumb={self.crumb}&symbols={','.join(symbols)}"
        try:
            data = self._query_api(url)
            results = data.get('quoteResponse', {}).get('result', [])
            quotes = {r['symbol']: r for r in results}
            if include_history:
                for sym in quotes:
                    cached = get_cached_history(sym)
                    if cached is not None:
                        quotes[sym]['history'] = cached
                    else:
                        h = self.get_history(sym)
                        set_cached_history(sym, h)
                        quotes[sym]['history'] = h
            return quotes
        except Exception as e:
            print(f"[stiq-custom] Error fetching quote data: {e}", file=sys.stderr)
            return {}

    def get_history(self, symbol):
        if not self.initialize():
            return []
        
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo&crumb={self.crumb}"
        try:
            data = self._query_api(url)
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

# Formatting functions imported from provider_utils

def fetch_market():
    global _market_cache
    symbols = list(MARKET_TICKERS.values())
    names = list(MARKET_TICKERS.keys())

    try:
        quotes = _provider.get_quotes(symbols)
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
        quotes = _provider.get_quotes(symbols, include_history=True)

        for sym in symbols:
            try:
                row = build_quote_row(sym, quotes.get(sym, {}))
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
