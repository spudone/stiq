import pytz
from datetime import datetime


class QuoteBuilder:
    def is_market_open(self) -> bool:
        et = pytz.timezone("US/Eastern")
        now_et = datetime.now(et)
        return (now_et.weekday() < 5) and (9 <= now_et.hour < 16)

    def make_normalized_quote(
        self,
        price: float = 0.0,
        prev_close: float = 0.0,
        open: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        volume: float = 0.0,
        low_52w: float | None = None,
        high_52w: float | None = None,
        avg_volume: float | None = None,
        pe_ratio: float | None = None,
        dividend_rate: float | None = None,
        dividend_yield: float | None = None,
        market_cap: float | None = None,
        currency: str = "USD",
        history: list[float] | None = None,
        change_pct: float | None = None,
    ) -> dict[str, any]:
        return {
            "price": price,
            "prev_close": prev_close,
            "open": open,
            "high": high,
            "low": low,
            "volume": volume,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "avg_volume": avg_volume,
            "pe_ratio": pe_ratio,
            "dividend_rate": dividend_rate,
            "dividend_yield": dividend_yield,
            "market_cap": market_cap,
            "currency": currency,
            "history": history or [],
            "change_pct": change_pct,
        }

    def build_market_index(self, name: str, quote: dict[str, any]) -> dict[str, any]:
        price = quote.get("price", 0)
        prev = quote.get("prev_close", 0)
        change_pct = quote.get("change_pct")
        if change_pct is None:
            change_pct = ((price - prev) / prev * 100) if prev and prev != 0 else 0.0
        return {
            "name": name,
            "value": price,
            "change": change_pct,
        }

    def build_quote_row(self, sym: str, quote: dict[str, any]) -> dict[str, any]:
        price = quote.get("price", 0)
        prev = quote.get("prev_close", 0)
        change = price - prev if prev else 0
        change_pct = quote.get("change_pct")
        if change_pct is None:
            change_pct = ((change / prev) * 100) if prev and prev != 0 else 0

        return {
            "quote": sym.upper(),
            "last": price,
            "change": change,
            "changePct": change_pct,
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "volume": quote.get("volume"),
            "low52": quote.get("low_52w"),
            "high52": quote.get("high_52w"),
            "avgVolume": quote.get("avg_volume"),
            "peRatio": quote.get("pe_ratio"),
            "dividend": quote.get("dividend_rate"),
            "yield": quote.get("dividend_yield"),
            "marketCap": quote.get("market_cap"),
            "currency": quote.get("currency", "USD"),
            "history": quote.get("history", []),
        }


builder = QuoteBuilder()
