from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from app.agent.service import AgentRunService
from app.daily_run import run_daily
from app.models import AgentRunStatus
from app.services.market_data import MarketDataService
from app.services.portfolio import PortfolioService
from app.strategies.ai import AITradingStrategy
from app.trading.service import ExecutionSettings, TradingService
from tests.fakes import Clock, FakeLLM, FakeMarketDataProvider, final, history, propose

WATCHLIST = ["AAPL", "MSFT"]
# 14:30 UTC on a Tuesday in October = 10:30 ET (EDT).
AFTER_TEN = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
TEN = time(10, 0)


@pytest.fixture
def market(session) -> MarketDataService:
    provider = FakeMarketDataProvider({"AAPL": Decimal("100"), "MSFT": Decimal("400")})
    return MarketDataService(session, provider, now=Clock(AFTER_TEN))


@pytest.fixture
def portfolios(session) -> PortfolioService:
    return PortfolioService(session)


def agent_with(session, market, llm) -> AgentRunService:
    return AgentRunService(
        session,
        market,
        TradingService(session, market, ExecutionSettings()),
        strategy_for=lambda sid: AITradingStrategy(llm) if sid == "ai-trading-v1" else None,
        watchlist=WATCHLIST,
    )


def buying_llm() -> FakeLLM:
    return FakeLLM([history("AAPL"), propose("AAPL", "BUY", 10), final("Bought AAPL.")])


def test_only_auto_trade_portfolios_run(session, market, portfolios):
    on = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.create_portfolio("Off", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(on.id, True)

    result = run_daily(session, agent_with(session, market, buying_llm()), AFTER_TEN, TEN)

    [run] = result.runs
    assert run.portfolio_id == on.id
    assert run.status is AgentRunStatus.COMPLETED
    assert run.run_key == "daily:2026-10-20"
    assert portfolios.get_positions(on.id)[0].quantity == Decimal(10)
    assert not result.failed


def test_runs_at_most_once_per_day(session, market, portfolios):
    p = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(p.id, True)
    llm = buying_llm()
    agent = agent_with(session, market, llm)

    first = run_daily(session, agent, AFTER_TEN, TEN)
    # The workflow fires twice a day (for daylight saving); the second is a no-op.
    second = run_daily(session, agent, AFTER_TEN.replace(hour=15), TEN)

    assert second.runs[0].id == first.runs[0].id
    assert len(llm.calls) == 3
    assert len(portfolios.get_positions(p.id)) == 1


def test_waits_until_the_configured_time(session, market, portfolios):
    p = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(p.id, True)
    llm = buying_llm()

    # 13:30 UTC = 9:30 ET: market just opened, too early.
    result = run_daily(session, agent_with(session, market, llm), AFTER_TEN.replace(hour=13), TEN)

    assert result.runs == []
    assert "Too early: 09:30 ET" in result.not_yet
    assert llm.calls == []


def test_eastern_time_handles_winter(session, market, portfolios):
    p = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(p.id, True)
    january = datetime(2027, 1, 12, 14, 30, tzinfo=UTC)  # 9:30 EST

    result = run_daily(session, agent_with(session, market, buying_llm()), january, TEN)
    assert result.not_yet is not None


def test_manual_run_ignores_the_time_and_can_target_one_portfolio(session, market, portfolios):
    off = portfolios.create_portfolio("Off", Decimal("1000000"), "ai-trading-v1")
    early = AFTER_TEN.replace(hour=13)

    result = run_daily(
        session,
        agent_with(session, market, buying_llm()),
        early,
        TEN,
        manual=True,
        portfolio_id=off.id,
        manual_key="12345",
    )

    [run] = result.runs
    assert run.portfolio_id == off.id
    assert run.run_key == "manual:12345"
    assert run.status is AgentRunStatus.COMPLETED


def test_paused_portfolio_is_skipped_not_traded(session, market, portfolios):
    p = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(p.id, True)
    portfolios.pause(p.id)
    llm = buying_llm()

    [run] = run_daily(session, agent_with(session, market, llm), AFTER_TEN, TEN).runs

    assert run.status is AgentRunStatus.SKIPPED
    assert llm.calls == []


def test_one_failure_does_not_stop_the_others(session, market, portfolios):
    manual = portfolios.create_portfolio("No strategy", Decimal("1000000"), "manual")
    ai = portfolios.create_portfolio("AI", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(manual.id, True)
    portfolios.set_auto_trade(ai.id, True)

    result = run_daily(session, agent_with(session, market, buying_llm()), AFTER_TEN, TEN)

    assert [r.portfolio_id for r in result.runs] == [ai.id]
    assert "No strategy registered for 'manual'" in result.errors[0]
    assert result.failed


def test_failed_run_marks_the_job_failed(session, market, portfolios):
    p = portfolios.create_portfolio("On", Decimal("1000000"), "ai-trading-v1")
    portfolios.set_auto_trade(p.id, True)
    llm = FakeLLM([{"content": [{"text": "..."}], "stop": "max_tokens"}])

    result = run_daily(session, agent_with(session, market, llm), AFTER_TEN, TEN)
    assert result.runs[0].status is AgentRunStatus.FAILED
    assert result.failed


def test_auto_trade_switch_is_owner_only(client, visitor):
    pid = client.post(
        "/portfolios", json={"name": "P", "starting_capital": "1000000", "strategy_id": "manual"}
    ).json()["id"]
    assert visitor.get(f"/portfolios/{pid}").json()["auto_trade"] is False
    assert visitor.post(f"/portfolios/{pid}/auto-trade", json={"enabled": True}).status_code == 401

    response = client.post(f"/portfolios/{pid}/auto-trade", json={"enabled": True})
    assert response.json()["auto_trade"] is True
    assert visitor.get(f"/portfolios/{pid}").json()["auto_trade"] is True
