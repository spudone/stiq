from typing import List, Optional
from pydantic import BaseModel, Field


class WatchlistConfig(BaseModel):
    symbols: List[str]
    poll_interval_secs: int = Field(default=300, ge=60)
    quotes_provider: str
    market_provider: str
    history_provider: str
    use_rate_limit: bool = True
    tiingo_threshold_level: int = 6


class TiingoUsage(BaseModel):
    hourly_requests: int
    daily_requests: int
    monthly_bandwidth_mb: float


class MarketIndex(BaseModel):
    name: str
    value: float
    change: float


class MarketResponse(BaseModel):
    indices: List[MarketIndex]
    is_open: bool


class RealtimeQuote(BaseModel):
    quote: str
    last: float
    change: float
    changePct: float
    open: float
    high: float
    low: float
    volume: float


class HistoricalQuote(BaseModel):
    quote: str
    low52: Optional[float] = None
    high52: Optional[float] = None
    avgVolume: Optional[float] = None
    peRatio: Optional[float] = None
    dividend: Optional[float] = None
    dividend_yield: Optional[float] = None
    marketCap: Optional[float] = None
    currency: str = "USD"
    history: List[float] = []


class UnifiedQuote(RealtimeQuote, HistoricalQuote):
    pass


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)


class WatchlistRemoveRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)


class WatchlistIntervalRequest(BaseModel):
    seconds: int = Field(..., ge=60)


class ErrorResponse(BaseModel):
    detail: str
