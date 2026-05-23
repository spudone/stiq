from .provider import DataProvider, YAHOO_MARKET_TICKERS
from .cache import cache
from .builder import builder
import sys
import yfinance as yf

class YFinanceProvider(DataProvider):
    def __init__(self) -> None:
        self._market_cache = None
        self._quotes_cache = {}

    def _normalize_raw_quote(self, ticker: any) -> dict[str, any]:
        info = ticker.fast_info
        t_info = {}
        try:
            t_info = ticker.info
        except Exception:
            pass

        return builder.make_normalized_quote(
            price=info.get("lastPrice", 0),
            prev_close=info.get("previousClose", 0),
            open=info.get("open", 0),
            high=info.get("dayHigh", 0),
            low=info.get("dayLow", 0),
            volume=info.get("lastVolume", 0),
            low_52w=info.get("fiftyTwoWeekLow") or t_info.get("fiftyTwoWeekLow"),
            high_52w=info.get("fiftyTwoWeekHigh") or t_info.get("fiftyTwoWeekHigh"),
            avg_volume=info.get("averageVolume10Day")
            or t_info.get("averageDailyVolume10Day"),
            pe_ratio=t_info.get("trailingPE"),
            dividend_rate=t_info.get("dividendRate")
            or t_info.get("trailingAnnualDividendRate"),
            dividend_yield=t_info.get("dividendYield")
            or t_info.get("trailingAnnualDividendYield"),
            market_cap=info.get("marketCap") or t_info.get("marketCap"),
            currency=info.get("currency") or t_info.get("currency", "USD"),
            history=[],
        )

    def fetch_market(self) -> dict[str, any]:
        symbols = list(YAHOO_MARKET_TICKERS.values())
        names = list(YAHOO_MARKET_TICKERS.keys())

        try:
            tickers = yf.Tickers(" ".join(symbols))
            indices = []

            for sym, name in zip(symbols, names):
                try:
                    t = tickers.tickers[sym]
                    normalized = self._normalize_raw_quote(t)
                    indices.append(builder.build_market_index(name, normalized))
                except Exception:
                    indices.append({"name": name, "value": None, "change": 0.0})

            result = {"indices": indices, "is_open": builder.is_market_open()}
            self._market_cache = result
            return result

        except Exception as e:
            print(f"[stiq] Market fetch error (yfinance): {e}", file=sys.stderr)
            if self._market_cache:
                return self._market_cache
            return {"indices": [], "is_open": False}

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, any]]:
        if not symbols:
            return []

        results = []
        try:
            tickers = yf.Tickers(" ".join(symbols))

            for sym in symbols:
                sym_upper = sym.upper()
                try:
                    t = tickers.tickers[sym]
                    normalized = self._normalize_raw_quote(t)

                    cached = cache.get_history(sym_upper)
                    if cached is not None:
                        normalized["history"] = cached
                    else:
                        hist = t.history(period="1mo")
                        h = []
                        if (
                            hist is not None
                            and not hist.empty
                            and "Close" in hist.columns
                        ):
                            h = [round(float(c), 2) for c in hist["Close"].tolist()]
                        cache.set_history(sym_upper, h)
                        normalized["history"] = h

                    row = builder.build_quote_row(sym_upper, normalized)
                    results.append(row)
                    self._quotes_cache[sym_upper] = row

                except Exception as e:
                    print(
                        f"[stiq] Quote error for {sym_upper} (yfinance): {e}",
                        file=sys.stderr,
                    )
                    if sym_upper in self._quotes_cache:
                        results.append(self._quotes_cache[sym_upper])

        except Exception as e:
            print(f"[stiq] Quotes fetch error (yfinance): {e}", file=sys.stderr)
            for sym in symbols:
                sym_upper = sym.upper()
                if sym_upper in self._quotes_cache:
                    results.append(self._quotes_cache[sym_upper])

        return results
