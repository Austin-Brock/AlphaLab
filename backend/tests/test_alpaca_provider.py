from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest

from app.market_data.alpaca import AlpacaMarketDataProvider
from app.market_data.provider import MarketDataUnavailableError, Timeframe


def make_provider(handler, sleeps: list[float] | None = None) -> AlpacaMarketDataProvider:
    return AlpacaMarketDataProvider(
        api_key="key",
        secret_key="secret",
        client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_latest_quotes_parses_decimals_and_nanosecond_timestamps():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/stocks/trades/latest"
        assert request.url.params["symbols"] == "AAPL,MSFT"
        assert request.url.params["feed"] == "iex"
        assert request.headers["APCA-API-KEY-ID"] == "key"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret"
        return httpx2.Response(
            200,
            text='{"trades": {"AAPL": {"t": "2026-10-16T19:59:59.123456789Z", "p": 231.07},'
            ' "MSFT": {"t": "2026-10-16T19:59:58Z", "p": 410}}}',
        )

    quotes = make_provider(handler).get_latest_quotes(["AAPL", "MSFT"])

    assert quotes["AAPL"].price == Decimal("231.07")
    assert quotes["AAPL"].price_time == datetime(2026, 10, 16, 19, 59, 59, 123456, tzinfo=UTC)
    assert quotes["MSFT"].price == Decimal("410")
    assert isinstance(quotes["MSFT"].price, Decimal)


def test_bars_follow_pagination():
    pages = {
        None: '{"bars": {"AAPL": [{"t": "2026-10-15T04:00:00Z", "o": 1, "h": 2, "l": 0.5,'
        ' "c": 1.5, "v": 100}]}, "next_page_token": "abc"}',
        "abc": '{"bars": {"AAPL": [{"t": "2026-10-16T04:00:00Z", "o": 1.5, "h": 3, "l": 1,'
        ' "c": 2.5, "v": 200}]}, "next_page_token": null}',
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params["timeframe"] == "1Day"
        assert request.url.params["adjustment"] == "split"
        return httpx2.Response(200, text=pages[request.url.params.get("page_token")])

    bars = make_provider(handler).get_bars(
        "AAPL",
        Timeframe.DAY_1,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 17, tzinfo=UTC),
    )

    assert [b.close for b in bars] == [Decimal("1.5"), Decimal("2.5")]
    assert bars[1].volume == 200


def test_retries_rate_limits_then_succeeds():
    responses = iter([httpx2.Response(429), httpx2.Response(503), httpx2.Response(200, json={})])
    sleeps: list[float] = []

    quotes = make_provider(lambda _: next(responses), sleeps).get_latest_quotes(["AAPL"])

    assert quotes == {}
    assert sleeps == [0.5, 1.0]


def test_does_not_retry_auth_errors():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(401, text="forbidden")

    with pytest.raises(MarketDataUnavailableError, match="HTTP 401"):
        make_provider(handler).get_latest_quotes(["AAPL"])
    assert len(calls) == 1


def test_network_errors_raise_after_all_attempts():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx2.ConnectError("connection refused")

    with pytest.raises(MarketDataUnavailableError, match="network error"):
        make_provider(handler).get_latest_quotes(["AAPL"])
    assert len(calls) == 3


def test_error_messages_are_short_and_readable():
    html = "<html><head><title>401 Authorization Required</title></head><body></body></html>"
    with pytest.raises(MarketDataUnavailableError) as exc_info:
        make_provider(lambda _: httpx2.Response(401, text=html)).get_latest_quotes(["AAPL"])
    assert str(exc_info.value).endswith("(HTTP 401: 401 Authorization Required)")

    json_error = httpx2.Response(422, json={"message": "invalid symbol"})
    with pytest.raises(MarketDataUnavailableError, match=r"HTTP 422: invalid symbol\)"):
        make_provider(lambda _: json_error).get_latest_quotes(["AAPL"])


def test_market_clock_uses_trading_api():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "paper-api.alpaca.markets"
        assert request.url.path == "/v2/clock"
        return httpx2.Response(
            200,
            json={
                "timestamp": "2026-10-19T18:30:00.123456789-04:00",
                "is_open": False,
                "next_open": "2026-10-20T09:30:00-04:00",
                "next_close": "2026-10-20T16:00:00-04:00",
            },
        )

    clock = make_provider(handler).get_market_clock()
    assert clock.is_open is False
    assert clock.next_open == datetime(2026, 10, 20, 13, 30, tzinfo=UTC)
