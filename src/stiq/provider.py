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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .builder import QuoteBuilder
    from .cache import CacheManager
    from .config import ConfigManager
    from .events import EventBus
    from .tiingo_usage import TiingoUsageTracker

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


class ProviderFactory:
    """Responsible for instantiating and caching individual providers."""

    def __init__(
        self,
        config: "ConfigManager",
        event_bus: "EventBus",
        usage_tracker: "TiingoUsageTracker",
        cache: "CacheManager",
        builder: "QuoteBuilder",
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.usage_tracker = usage_tracker
        self.cache = cache
        self.builder = builder
        self._instance_cache: dict[str, DataProvider] = {}
        self._provider_creators = {
            "yfinance": self._create_yfinance,
            "tiingo": self._create_tiingo,
            "yahoo": self._create_yahoo,
        }

    def _create_yfinance(self) -> DataProvider:
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider(
            self.config,
            self.event_bus,
            self.usage_tracker,
            self.cache,
            self.builder,
        )

    def _create_tiingo(self) -> DataProvider:
        from .tiingo_provider import TiingoWebSocketProvider

        return TiingoWebSocketProvider(
            self.config,
            self.event_bus,
            self.usage_tracker,
            self.cache,
            self.builder,
        )

    def _create_yahoo(self) -> DataProvider:
        from .yahoo_provider import YahooProvider

        return YahooProvider(
            self.config,
            self.event_bus,
            self.usage_tracker,
            self.cache,
            self.builder,
        )

    def get(self, name: str) -> DataProvider:
        """Return a cached provider instance, creating it if needed."""
        name = name.lower()
        if name not in self._instance_cache:
            creator = self._provider_creators.get(name, self._create_yahoo)
            self._instance_cache[name] = creator()
        return self._instance_cache[name]


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


def create_provider(
    config: "ConfigManager",
    event_bus: "EventBus",
    usage_tracker: "TiingoUsageTracker",
    cache: "CacheManager",
    builder: "QuoteBuilder",
) -> DataProvider:
    """Factory to return the configured multiplex provider."""
    factory = ProviderFactory(config, event_bus, usage_tracker, cache, builder)

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
        factory.get(market_prov),
        factory.get(quotes_prov),
        factory.get(history_prov),
    )
