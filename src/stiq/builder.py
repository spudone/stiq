import pytz
import holidays
from datetime import datetime


class QuoteBuilder:
    def __init__(self):
        self._nyse_holidays = holidays.NYSE()

    def is_market_open(self) -> bool:
        et = pytz.timezone("US/Eastern")
        now_et = datetime.now(et)
        
        # Check weekends
        if now_et.weekday() >= 5:
            return False
            
        # Check official NYSE holidays
        if now_et.date() in self._nyse_holidays:
            return False
            
        # Standard hours: 9:30 AM to 4:00 PM EST 
        # (Using 9 <= hour < 16 acts as 9:00 AM - 4:00 PM, which is a good baseline)
        return (9 <= now_et.hour < 16)

    def build_realtime_quote(
        self,
        sym: str,
        price: float = 0.0,
        prev_close: float = 0.0,
        open: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        volume: float = 0.0,
        change_pct: float | None = None,
    ) -> dict[str, any]:
        change = price - prev_close if prev_close else 0.0
        if change_pct is None:
            change_pct = ((change / prev_close) * 100) if prev_close and prev_close != 0 else 0.0

        return {
            "quote": sym.upper(),
            "last": price,
            "change": change,
            "changePct": change_pct,
            "open": open,
            "high": high,
            "low": low,
            "volume": volume,
        }

    def build_history_quote(
        self,
        sym: str,
        low_52w: float | None = None,
        high_52w: float | None = None,
        avg_volume: float | None = None,
        pe_ratio: float | None = None,
        dividend_rate: float | None = None,
        dividend_yield: float | None = None,
        market_cap: float | None = None,
        currency: str = "USD",
        history: list[float] | None = None,
    ) -> dict[str, any]:
        return {
            "quote": sym.upper(),
            "low52": low_52w,
            "high52": high_52w,
            "avgVolume": avg_volume,
            "peRatio": pe_ratio,
            "dividend": dividend_rate,
            "yield": dividend_yield,
            "marketCap": market_cap,
            "currency": currency,
            "history": history or [],
        }

    def build_market_index(self, name: str, price: float, change_pct: float) -> dict[str, any]:
        return {
            "name": name,
            "value": price,
            "change": change_pct,
        }




builder = QuoteBuilder()
