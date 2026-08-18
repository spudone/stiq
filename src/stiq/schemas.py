"""
Stiq - Stock Ticker
Copyright (C) 2026 spudone

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from pydantic import BaseModel, Field


class WatchlistConfig(BaseModel):
    symbols: list[str]
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
    indices: list[MarketIndex]
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
    low52: float | None = None
    high52: float | None = None
    avgVolume: float | None = None
    peRatio: float | None = None
    dividend: float | None = None
    dividend_yield: float | None = None
    marketCap: float | None = None
    currency: str = "USD"
    history: list[float] = []


class UnifiedQuote(RealtimeQuote, HistoricalQuote):
    pass


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)


class WatchlistRemoveRequest(BaseModel):
    symbol: str = Field(..., min_length=1)


class WatchlistIntervalRequest(BaseModel):
    seconds: int = Field(..., ge=60)


class ErrorResponse(BaseModel):
    detail: str
