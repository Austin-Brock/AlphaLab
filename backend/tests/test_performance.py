from datetime import date, timedelta
from decimal import Decimal

from app.services.performance import Fill, build_history

MILLION = Decimal("1000000")
MON, TUE, WED = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)
FRI, SAT = date(2026, 10, 16), date(2026, 10, 17)


def values(points):
    return [(p.date, p.value, p.benchmark_value) for p in points]


def test_all_cash_tracks_the_benchmark_from_the_first_close():
    closes = {"SPY": {MON: Decimal("500"), TUE: Decimal("510")}}
    points = build_history(MILLION, MON, [(MON, MILLION)], [], closes, "SPY")
    assert values(points) == [(MON, MILLION, MILLION), (TUE, MILLION, Decimal("1020000.0000"))]


def test_holdings_are_valued_at_each_days_close():
    closes = {
        "SPY": {MON: Decimal("500"), TUE: Decimal("500"), WED: Decimal("490")},
        "AAPL": {MON: Decimal("100"), TUE: Decimal("110"), WED: Decimal("120")},
    }
    cash = [(MON, MILLION), (TUE, Decimal("-10005"))]
    fills = [Fill(TUE, "AAPL", Decimal(100), Decimal("100.05"))]

    points = build_history(MILLION, MON, cash, fills, closes, "SPY")

    assert [p.value for p in points] == [MILLION, Decimal("1000995"), Decimal("1001995")]
    assert points[-1].benchmark_value == Decimal("980000")


def test_sold_shares_stop_counting():
    closes = {
        "SPY": {MON: Decimal("1"), TUE: Decimal("1")},
        "AAPL": {MON: Decimal("100"), TUE: Decimal("200")},
    }
    cash = [(MON, MILLION), (MON, Decimal("-1000")), (TUE, Decimal("2000"))]
    fills = [
        Fill(MON, "AAPL", Decimal(10), Decimal(100)),
        Fill(TUE, "AAPL", Decimal(-10), Decimal(200)),
    ]
    points = build_history(MILLION, MON, cash, fills, closes, "SPY")
    assert [p.value for p in points] == [MILLION, Decimal("1001000")]


def test_weekend_start_begins_at_the_previous_close():
    closes = {"SPY": {FRI: Decimal("500"), MON: Decimal("505")}}
    points = build_history(MILLION, SAT, [(SAT, MILLION)], [], closes, "SPY")
    assert values(points) == [(FRI, MILLION, MILLION), (MON, MILLION, Decimal("1010000.0000"))]


def test_live_prices_replace_todays_close():
    closes = {"SPY": {MON: Decimal("500"), TUE: Decimal("500")}, "AAPL": {TUE: Decimal("100")}}
    cash = [(MON, MILLION), (TUE, Decimal("-10000"))]
    fills = [Fill(TUE, "AAPL", Decimal(100), Decimal(100))]
    live = (TUE, {"SPY": Decimal("505"), "AAPL": Decimal("101")})

    points = build_history(MILLION, MON, cash, fills, closes, "SPY", live=live)

    assert values(points)[-1] == (TUE, Decimal("1000100"), Decimal("1010000.0000"))


def test_live_prices_add_today_before_its_close_exists():
    closes = {"SPY": {MON: Decimal("500")}}
    cash = [(MON, MILLION), (TUE, Decimal("-10000"))]
    # Bought today: no close for AAPL yet, so it's valued at the live price.
    fills = [Fill(TUE, "AAPL", Decimal(100), Decimal(100))]
    live = (TUE, {"SPY": Decimal("500"), "AAPL": Decimal("98")})

    points = build_history(MILLION, MON, cash, fills, closes, "SPY", live=live)

    assert values(points) == [(MON, MILLION, MILLION), (TUE, Decimal("999800"), MILLION)]


def test_stale_live_prices_are_ignored():
    closes = {"SPY": {MON: Decimal("500"), TUE: Decimal("500")}}
    live = (MON, {"SPY": Decimal("1")})
    points = build_history(MILLION, MON, [(MON, MILLION)], [], closes, "SPY", live=live)
    assert [p.benchmark_value for p in points] == [MILLION, MILLION]


def test_missing_prices_fall_back_to_the_fill_price():
    closes = {"SPY": {MON: Decimal("500"), TUE: Decimal("500")}}
    cash = [(MON, MILLION), (MON, Decimal("-10000"))]
    fills = [Fill(MON, "AAPL", Decimal(100), Decimal(100))]
    points = build_history(MILLION, MON, cash, fills, closes, "SPY")
    assert [p.value for p in points] == [MILLION, MILLION]


def test_no_market_data_still_returns_the_starting_point():
    points = build_history(MILLION, MON, [(MON, MILLION)], [], {}, "SPY")
    assert values(points) == [(MON, MILLION, None)]


# API, with the fake provider: one bar per calendar day at a constant price.


def create_portfolio(client) -> str:
    return client.post(
        "/portfolios",
        json={"name": "Manual", "starting_capital": "1000000", "strategy_id": "manual"},
    ).json()["id"]


def test_value_history_api(client, fake_market):
    pid = create_portfolio(client)
    client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 100}
    )

    history = client.get(f"/portfolios/{pid}/value-history").json()

    assert history["benchmark"] == "SPY"
    assert not history["stale"]
    first, last = history["points"][0], history["points"][-1]
    assert (first["value"], first["benchmark_value"]) == ("1000000.0000", "1000000.0000")
    # Bought at $100.05, now worth $100: down the $5 of slippage.
    assert last["value"] == client.get(f"/portfolios/{pid}/value").json()["total_value"]
    assert last["value"] == "999995.0000"
    assert last["benchmark_value"] == "1000000.0000"


def test_value_history_reuses_recent_daily_bars(client, fake_market):
    pid = create_portfolio(client)
    client.get(f"/portfolios/{pid}/value-history")
    calls = fake_market.bar_calls
    client.get(f"/portfolios/{pid}/value-history")
    assert fake_market.bar_calls == calls


def test_value_history_survives_a_provider_outage(client, fake_market):
    pid = create_portfolio(client)
    fake_market.fail = True
    history = client.get(f"/portfolios/{pid}/value-history").json()
    assert history["stale"]
    assert history["points"][0]["value"] == "1000000.0000"


def test_visitors_can_see_the_chart(visitor, client):
    pid = create_portfolio(client)
    assert visitor.get(f"/portfolios/{pid}/value-history").status_code == 200


def test_bars_cache_needs_the_full_range(session):
    from datetime import UTC, datetime

    from app.market_data.provider import Timeframe
    from app.services.market_data import MarketDataService
    from tests.fakes import FakeMarketDataProvider

    provider = FakeMarketDataProvider({"SPY": Decimal("500")})
    market = MarketDataService(session, provider)
    end = datetime.now(UTC)
    market.get_bars("SPY", Timeframe.DAY_1, end - timedelta(days=3), end)
    calls = provider.bar_calls

    market.get_bars(
        "SPY", Timeframe.DAY_1, end - timedelta(days=3), end, max_age=timedelta(minutes=15)
    )
    assert provider.bar_calls == calls
    # A longer range than what's cached goes back to the provider.
    market.get_bars(
        "SPY", Timeframe.DAY_1, end - timedelta(days=30), end, max_age=timedelta(minutes=15)
    )
    assert provider.bar_calls == calls + 1
