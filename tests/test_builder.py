import pytest
import pytz
from datetime import datetime
from unittest.mock import patch, MagicMock

from stiq.builder import QuoteBuilder


@pytest.fixture
def builder():
    return QuoteBuilder()


def test_build_realtime_quote(builder):
    # Test typical values
    result = builder.build_realtime_quote(
        sym="aapl",
        price=150.0,
        prev_close=145.0,
        open=146.0,
        high=151.0,
        low=144.0,
        volume=1000.0,
    )
    assert result["quote"] == "AAPL"
    assert result["last"] == 150.0
    assert result["change"] == 5.0
    assert pytest.approx(result["changePct"]) == 3.448275
    assert result["open"] == 146.0

    # Test explicit change_pct override
    result_pct = builder.build_realtime_quote(
        sym="msft", price=200.0, prev_close=190.0, change_pct=5.5
    )
    assert result_pct["changePct"] == 5.5

    # Test zero prev_close to prevent div by zero
    result_zero = builder.build_realtime_quote(sym="tsla", price=100.0, prev_close=0.0)
    assert result_zero["change"] == 0.0
    assert result_zero["changePct"] == 0.0


def test_build_history_quote(builder):
    result = builder.build_history_quote(
        sym="aapl",
        low_52w=120.0,
        high_52w=160.0,
        avg_volume=2000.0,
        currency="EUR",
        history=[140.0, 145.0, 150.0],
    )
    assert result["quote"] == "AAPL"
    assert result["low52"] == 120.0
    assert result["high52"] == 160.0
    assert result["avgVolume"] == 2000.0
    assert result["currency"] == "EUR"
    assert result["history"] == [140.0, 145.0, 150.0]

    # Test defaults
    result_default = builder.build_history_quote(sym="msft")
    assert result_default["quote"] == "MSFT"
    assert result_default["peRatio"] is None
    assert result_default["history"] == []
    assert result_default["currency"] == "USD"


def test_build_market_index(builder):
    result = builder.build_market_index(name="S&P 500", price=4500.0, change_pct=1.5)
    assert result["name"] == "S&P 500"
    assert result["value"] == 4500.0
    assert result["change"] == 1.5


@patch("stiq.builder.datetime")
def test_is_market_open(mock_dt, builder):
    et = pytz.timezone("US/Eastern")

    # 1. Test normal weekday, open hours (Tuesday, 10:00 AM)
    # 2026-03-03 is a Tuesday
    dt_open = et.localize(datetime(2026, 3, 3, 10, 0, 0))
    mock_dt.now.return_value = dt_open
    mock_dt.date = MagicMock()
    assert builder.is_market_open() is True

    # 2. Test normal weekday, closed hours (Tuesday, 8:00 AM and 9:15 AM)
    dt_closed_early = et.localize(datetime(2026, 3, 3, 8, 0, 0))
    mock_dt.now.return_value = dt_closed_early
    assert builder.is_market_open() is False

    dt_closed_915 = et.localize(datetime(2026, 3, 3, 9, 15, 0))
    mock_dt.now.return_value = dt_closed_915
    assert builder.is_market_open() is False

    dt_open_930 = et.localize(datetime(2026, 3, 3, 9, 30, 0))
    mock_dt.now.return_value = dt_open_930
    assert builder.is_market_open() is True

    # 3. Test normal weekday, closed hours (Tuesday, 5:00 PM)
    dt_closed_late = et.localize(datetime(2026, 3, 3, 17, 0, 0))
    mock_dt.now.return_value = dt_closed_late
    assert builder.is_market_open() is False

    # 4. Test weekend (Saturday, 10:00 AM)
    # 2026-03-07 is a Saturday
    dt_weekend = et.localize(datetime(2026, 3, 7, 10, 0, 0))
    mock_dt.now.return_value = dt_weekend
    assert builder.is_market_open() is False

    # 5. Test holiday (e.g. Christmas, assuming it's a weekday, 2026-12-25 is Friday)
    dt_holiday = et.localize(datetime(2026, 12, 25, 10, 0, 0))
    mock_dt.now.return_value = dt_holiday
    assert builder.is_market_open() is False
