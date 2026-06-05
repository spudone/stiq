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

import os
from abc import ABC, abstractmethod

# Note: this could move to a new file if/when other providers are implemented
YAHOO_MARKET_TICKERS = {
    "Dow": "^DJI",
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Tokyo": "^N225",
    "HK": "^HSI",
    "London": "^FTSE",
    "Frankfurt": "^GDAXI",
    "10-Year Yield": "^TNX",
    "Euro": "EUR=X",
    "Yen": "JPY=X",
    "Oil": "CL=F",
    "Gold": "GC=F",
}


class DataProvider(ABC):
    @abstractmethod
    async def fetch_market(self) -> dict[str, any]:
        """Fetches market indices and status"""
        pass

    @abstractmethod
    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        """Fetches realtime quotes for a list of symbols"""
        pass

    @abstractmethod
    async def fetch_history(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        """Fetches historical data for a list of symbols"""
        pass


class MultiplexProvider(DataProvider):
    """Routes different data fetch requests to independently configured providers."""

    def __init__(
        self, market: DataProvider, quotes: DataProvider, history: DataProvider
    ):
        self.market = market
        self.quotes = quotes
        self.history = history

    async def fetch_market(self) -> dict[str, any]:
        return await self.market.fetch_market()

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        return await self.quotes.fetch_quotes(symbols)

    async def fetch_history(self, symbols: list[str]) -> dict[str, dict[str, any]]:
        return await self.history.fetch_history(symbols)


_provider_instances: dict[str, DataProvider] = {}


def _get_single_provider(name: str) -> DataProvider:
    name = name.lower()
    if name not in _provider_instances:
        if name == "yfinance":
            from .yfinance_provider import YFinanceProvider

            _provider_instances[name] = YFinanceProvider()
        elif name == "tiingo":
            from .tiingo_provider import TiingoWebSocketProvider

            _provider_instances[name] = TiingoWebSocketProvider()
        else:
            from .yahoo_provider import YahooProvider

            _provider_instances[name] = YahooProvider()
    return _provider_instances[name]


def get_provider() -> DataProvider:
    """Factory to return the configured provider."""
    from .config import config
    from .builder import builder

    market_prov = config.market_provider
    quotes_prov = config.quotes_provider
    history_prov = config.history_provider

    # Intelligent weekend/closed market fallback for quotes
    if not builder.is_market_open():
        if "yfinance" in (market_prov, quotes_prov, history_prov):
            quotes_prov = "yfinance"
        else:
            quotes_prov = "yahoo"

    # Legacy STIQ_PROVIDER environment variable from Makefile overrides config
    env_prov = os.environ.get("STIQ_PROVIDER")
    if env_prov:
        env_prov = env_prov.lower()
        market_prov = env_prov
        quotes_prov = env_prov
        history_prov = env_prov

    return MultiplexProvider(
        _get_single_provider(market_prov),
        _get_single_provider(quotes_prov),
        _get_single_provider(history_prov),
    )
