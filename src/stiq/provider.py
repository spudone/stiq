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
    def fetch_market(self) -> dict[str, any]:
        """Fetches market indices and status"""
        pass

    @abstractmethod
    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, any]]:
        """Fetches detailed quotes for a list of symbols"""
        pass


def get_provider() -> DataProvider:
    """Factory to return the configured provider."""
    if os.environ.get("USE_YFINANCE") == "1":
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    else:
        from .yahoo_provider import YahooProvider

        return YahooProvider()
