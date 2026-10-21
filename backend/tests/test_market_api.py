from decimal import Decimal

from app.config import DEFAULT_WATCHLIST
from app.models import Position


def test_milestone_2_definition_of_done(client):
    """Retrieve prices for the selected securities (10 at Milestone 2, now 50)."""
    assert client.get("/market/watchlist").json() == DEFAULT_WATCHLIST

    body = client.get("/market/prices").json()

    assert [p["symbol"] for p in body["prices"]] == DEFAULT_WATCHLIST
    assert len(body["prices"]) == 50
    assert body["prices"][0]["price"] == "100.0000"
    assert body["prices"][0]["fetched_at"]
    assert body["prices"][0]["price_time"]
    assert body["missing"] == []


def test_prices_for_requested_symbols(client):
    body = client.get("/market/prices", params={"symbols": "msft, aapl,ZZZZ"}).json()
    assert [p["symbol"] for p in body["prices"]] == ["MSFT", "AAPL"]
    assert body["missing"] == ["ZZZZ"]


def test_rejects_invalid_symbols(client):
    assert client.get("/market/prices", params={"symbols": "AAPL;DROP"}).status_code == 422
    assert client.get("/market/bars/12345").status_code == 422


def test_outage_with_empty_cache_returns_503(client, fake_market):
    fake_market.fail = True
    response = client.get("/market/prices", params={"symbols": "AAPL"})
    assert response.status_code == 503
    assert "fake outage" in response.json()["detail"]


def test_bars(client):
    body = client.get(
        "/market/bars/aapl",
        params={
            "timeframe": "1Day",
            "start": "2026-10-01T00:00:00Z",
            "end": "2026-10-03T00:00:00Z",
        },
    ).json()
    assert body["symbol"] == "AAPL"
    assert body["timeframe"] == "1Day"
    assert [b["close"] for b in body["bars"]] == ["100.0000"] * 3
    assert body["stale"] is False


def test_bars_reject_reversed_range(client):
    response = client.get(
        "/market/bars/AAPL",
        params={"start": "2026-10-05T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
    )
    assert response.status_code == 422


def test_portfolio_value_uses_market_prices(client, session, fake_market):
    portfolio_id = client.post(
        "/portfolios",
        json={"name": "P", "starting_capital": "1000000", "strategy_id": "ai-trading-v1"},
    ).json()["id"]
    session.add(
        Position(
            portfolio_id=portfolio_id,
            symbol="AAPL",
            quantity=Decimal("10"),
            average_cost=Decimal("50"),
        )
    )
    session.flush()

    value = client.get(f"/portfolios/{portfolio_id}/value").json()
    [aapl] = value["positions"]
    assert aapl["price"] == "100.0000"
    assert aapl["priced_at_cost"] is False
    assert Decimal(value["total_value"]) == Decimal("1001000")

    # During an outage with nothing cached, valuation falls back to cost instead of failing.
    session.rollback()
    fake_market.fail = True
    other_id = client.post(
        "/portfolios",
        json={"name": "Q", "starting_capital": "1000", "strategy_id": "ai-trading-v1"},
    ).json()["id"]
    session.add(
        Position(
            portfolio_id=other_id, symbol="NVDA", quantity=Decimal("1"), average_cost=Decimal("5")
        )
    )
    session.flush()
    [nvda] = client.get(f"/portfolios/{other_id}/value").json()["positions"]
    assert nvda["priced_at_cost"] is True
    assert nvda["price"] == "5.0000"


def test_market_clock(client, fake_market):
    fake_market.market_open = False
    body = client.get("/market/clock").json()
    assert body == {
        "is_open": False,
        "next_open": "2026-10-20T13:30:00Z",
        "next_close": "2026-10-19T20:00:00Z",
    }


def test_market_clock_outage_returns_503(client, fake_market):
    fake_market.fail = True
    assert client.get("/market/clock").status_code == 503
