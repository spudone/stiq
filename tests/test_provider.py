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

from unittest.mock import AsyncMock

import pytest

from stiq.provider import DataProvider, MultiplexProvider


class MockProvider(DataProvider):
    def __init__(self, name):
        self.name = name
        self.fetch_market_mock = AsyncMock()
        self.fetch_quotes_mock = AsyncMock()
        self.fetch_history_mock = AsyncMock()

    async def fetch_market(self):
        return await self.fetch_market_mock()

    async def fetch_quotes(self, symbols: list[str]):
        return await self.fetch_quotes_mock(symbols)

    async def fetch_history(self, symbols: list[str]):
        return await self.fetch_history_mock(symbols)


@pytest.mark.asyncio
async def test_multiplex_provider_routing():
    # Setup mock providers for injection
    market_prov = MockProvider("market")
    market_prov.fetch_market_mock.return_value = {"is_open": True, "indices": []}

    quotes_prov = MockProvider("quotes")
    quotes_prov.fetch_quotes_mock.return_value = {"AAPL": {"last": 150.0}}

    history_prov = MockProvider("history")
    history_prov.fetch_history_mock.return_value = {"AAPL": {"history": [100.0]}}

    # Create multiplexer
    multiplex = MultiplexProvider(
        market=market_prov, quotes=quotes_prov, history=history_prov
    )

    # Test market routing
    mkt = await multiplex.fetch_market()
    assert mkt == {"is_open": True, "indices": []}
    market_prov.fetch_market_mock.assert_called_once()
    quotes_prov.fetch_market_mock.assert_not_called()
    history_prov.fetch_market_mock.assert_not_called()

    # Test quotes routing
    quotes = await multiplex.fetch_quotes(["AAPL"])
    assert quotes == {"AAPL": {"last": 150.0}}
    quotes_prov.fetch_quotes_mock.assert_called_once_with(["AAPL"])
    market_prov.fetch_quotes_mock.assert_not_called()
    history_prov.fetch_quotes_mock.assert_not_called()

    # Test history routing
    history = await multiplex.fetch_history(["AAPL"])
    assert history == {"AAPL": {"history": [100.0]}}
    history_prov.fetch_history_mock.assert_called_once_with(["AAPL"])
    market_prov.fetch_history_mock.assert_not_called()
    quotes_prov.fetch_history_mock.assert_not_called()
