from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.market_data.provider import MarketDataUnavailableError, Timeframe
from app.services.market_data import MarketDataService
from tests.fakes import Clock, FakeMarketDataProvider


@pytest.fixture
def provider() -> FakeMarketDataProvider:
    return FakeMarketDataProvider({"AAPL": Decimal("231.07"), "MSFT": Decimal("410.50")})


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def market(session: Session, provider, clock) -> MarketDataService:
    return MarketDataService(session, provider, cache_ttl=timedelta(seconds=60), now=clock)


def prices_by_symbol(result):
    return {p.symbol: p for p in result.prices}


def test_fetches_and_records_when_data_was_updated(market, clock):
    result = market.get_latest_prices(["AAPL", "MSFT"])

    aapl = prices_by_symbol(result)["AAPL"]
    assert aapl.price == Decimal("231.07")
    assert aapl.fetched_at == clock.current
    assert aapl.source == "fake"
    assert not aapl.stale
    assert result.missing == []
    assert result.provider_error is None


def test_serves_from_cache_within_ttl(market, provider, clock):
    market.get_latest_prices(["AAPL"])
    clock.advance(seconds=30)
    market.get_latest_prices(["AAPL"])
    assert provider.quote_calls == [["AAPL"]]


def test_refetches_after_ttl_and_updates_price(market, provider, clock):
    market.get_latest_prices(["AAPL"])
    clock.advance(seconds=61)
    provider.prices["AAPL"] = Decimal("240.00")

    result = market.get_latest_prices(["AAPL"])

    assert provider.quote_calls == [["AAPL"], ["AAPL"]]
    assert prices_by_symbol(result)["AAPL"].price == Decimal("240.00")
    assert prices_by_symbol(result)["AAPL"].fetched_at == clock.current


def test_only_fetches_symbols_not_in_cache(market, provider):
    market.get_latest_prices(["AAPL"])
    market.get_latest_prices(["AAPL", "MSFT"])
    assert provider.quote_calls == [["AAPL"], ["MSFT"]]


def test_falls_back_to_stale_cache_when_provider_fails(market, provider, clock):
    market.get_latest_prices(["AAPL"])
    clock.advance(minutes=10)
    provider.fail = True

    result = market.get_latest_prices(["AAPL"])

    aapl = prices_by_symbol(result)["AAPL"]
    assert aapl.price == Decimal("231.07")
    assert aapl.stale
    assert result.provider_error == "fake outage"


def test_raises_when_provider_fails_and_nothing_is_cached(market, provider):
    provider.fail = True
    with pytest.raises(MarketDataUnavailableError):
        market.get_latest_prices(["AAPL"])


def test_unknown_symbols_are_reported_missing(market):
    result = market.get_latest_prices(["AAPL", "ZZZZ"])
    assert [p.symbol for p in result.prices] == ["AAPL"]
    assert result.missing == ["ZZZZ"]


def test_unconfigured_provider_explains_how_to_fix(session):
    with pytest.raises(MarketDataUnavailableError, match="ALPHALAB_ALPACA_API_KEY"):
        MarketDataService(session, provider=None).get_latest_prices(["AAPL"])


START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 5, tzinfo=UTC)


def test_bars_are_fetched_and_stored(market):
    series = market.get_bars("AAPL", Timeframe.DAY_1, START, END)
    assert len(series.bars) == 5
    assert series.bars[0].timestamp == START
    assert series.bars[0].close == Decimal("231.07")
    assert not series.stale


def test_refetching_bars_updates_instead_of_duplicating(market, provider):
    market.get_bars("AAPL", Timeframe.DAY_1, START, END)
    provider.prices["AAPL"] = Decimal("250")
    series = market.get_bars("AAPL", Timeframe.DAY_1, START, END)
    assert len(series.bars) == 5
    assert series.bars[0].close == Decimal("250")


def test_bars_fall_back_to_cache_when_provider_fails(market, provider):
    market.get_bars("AAPL", Timeframe.DAY_1, START, END)
    provider.fail = True

    series = market.get_bars("AAPL", Timeframe.DAY_1, START, END)

    assert len(series.bars) == 5
    assert series.stale
    assert series.provider_error == "fake outage"


def test_bars_raise_when_provider_fails_and_nothing_is_cached(market, provider):
    provider.fail = True
    with pytest.raises(MarketDataUnavailableError):
        market.get_bars("AAPL", Timeframe.DAY_1, START, END)
