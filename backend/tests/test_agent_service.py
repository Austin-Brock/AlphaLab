from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.agent.service import AgentRunService, MarketResearchTools, UnknownStrategyError
from app.llm.client import LLMUnavailableError
from app.models import AgentRunStatus, OrderStatus
from app.services.market_data import MarketDataService
from app.services.portfolio import PortfolioService
from app.strategies.ai import PROMPT_VERSION, AITradingStrategy
from app.trading.service import ExecutionSettings, TradingService
from tests.fakes import Clock, FakeLLM, FakeMarketDataProvider, final, history, propose, tool_call

WATCHLIST = ["AAPL", "MSFT", "NVDA"]
MILLION = Decimal("1000000")


@pytest.fixture
def provider() -> FakeMarketDataProvider:
    return FakeMarketDataProvider(
        {"AAPL": Decimal("100"), "MSFT": Decimal("400"), "NVDA": Decimal("200")}
    )


@pytest.fixture
def market(session: Session, provider) -> MarketDataService:
    return MarketDataService(session, provider, now=Clock())


@pytest.fixture
def portfolios(session: Session) -> PortfolioService:
    return PortfolioService(session)


@pytest.fixture
def portfolio(portfolios):
    return portfolios.create_portfolio("AI", MILLION, "ai-trading-v1")


def make_agent(session, market, llm, require_market_open=True) -> AgentRunService:
    trading = TradingService(session, market, ExecutionSettings())
    return AgentRunService(
        session,
        market,
        trading,
        strategy_for=lambda sid: AITradingStrategy(llm) if sid == "ai-trading-v1" else None,
        watchlist=WATCHLIST,
        require_market_open=require_market_open,
    )


def test_milestone_4_definition_of_done(session, market, portfolios, portfolio):
    """The AI proposes a trade that the backend validates and executes in the simulator."""
    llm = FakeLLM(
        [
            tool_call("get_portfolio"),
            history("AAPL"),
            propose("AAPL", "BUY", 100, "AAPL looks cheap", n=1),
            final("Bought 100 AAPL."),
        ]
    )

    run = make_agent(session, market, llm).run(portfolio.id)

    assert run.status is AgentRunStatus.COMPLETED
    assert run.summary == "Bought 100 AAPL."
    [decision] = run.decisions
    assert (decision.symbol, decision.quantity, decision.rationale) == (
        "AAPL",
        Decimal(100),
        "AAPL looks cheap",
    )
    order = decision.order
    assert order.status is OrderStatus.FILLED
    assert order.source == "ai-trading-v1"
    assert order.client_order_id == f"agent-run:{run.id}:0"
    assert all(c.passed for c in order.risk_checks)
    assert portfolios.get_cash_balance(portfolio.id) == Decimal("989995.00")


def test_run_records_everything_needed_to_reconstruct_the_decision(session, market, portfolio):
    llm = FakeLLM(
        [tool_call("get_portfolio"), history("MSFT"), propose("MSFT", "BUY", 10), final("Done.")]
    )
    run = make_agent(session, market, llm).run(portfolio.id)

    snap = run.input_snapshot
    assert snap["cash"] == "1000000.0000"
    assert snap["holdings"] == []
    assert snap["prices"] == {"AAPL": "100.0000", "MSFT": "400.0000", "NVDA": "200.0000"}
    assert (snap["max_position_pct"], snap["min_cash_pct"]) == ("0.1000", "0.0500")
    assert snap["market_open"] is True
    assert (run.model_id, run.prompt_version) == ("fake-model", PROMPT_VERSION)
    assert (run.input_tokens, run.output_tokens) == (400, 80)
    assert len(run.transcript) == 8
    assert run.transcript[0]["role"] == "user"
    assert run.finished_at is not None


def test_rejected_proposal_is_linked_to_its_rejected_order(session, market, portfolios, portfolio):
    # 2,000 AAPL at $100 is 20% of the portfolio.
    llm = FakeLLM([history("AAPL"), propose("AAPL", "BUY", 2000), final("Big bet.")])
    run = make_agent(session, market, llm).run(portfolio.id)

    assert run.status is AgentRunStatus.COMPLETED
    order = run.decisions[0].order
    assert order.status is OrderStatus.REJECTED
    assert "limit 10.0%" in order.rejection_reason
    assert portfolios.get_cash_balance(portfolio.id) == MILLION


def test_sells_execute_before_buys(session, market, portfolios, portfolio):
    first = FakeLLM([history("AAPL"), propose("AAPL", "BUY", 900), final("Buy.")])
    make_agent(session, market, first).run(portfolio.id)

    second = FakeLLM(
        [
            history("MSFT", "AAPL"),
            propose("MSFT", "BUY", 10, n=1),
            propose("AAPL", "SELL", 500, n=2),
            final("Rotate."),
        ]
    )
    run = make_agent(session, market, second).run(portfolio.id)

    assert [(d.symbol, d.side.value) for d in run.decisions] == [("AAPL", "SELL"), ("MSFT", "BUY")]
    assert [d.order.status for d in run.decisions] == [OrderStatus.FILLED, OrderStatus.FILLED]


def test_market_closed_skips_without_calling_the_model(session, market, provider, portfolio):
    provider.market_open = False
    llm = FakeLLM([final("should not be called")])

    run = make_agent(session, market, llm).run(portfolio.id)

    assert run.status is AgentRunStatus.SKIPPED
    assert run.summary == "Market is closed"
    assert llm.calls == []
    assert run.input_snapshot["market_open"] is False


def test_market_hours_can_be_relaxed_for_testing(session, market, provider, portfolio):
    provider.market_open = False
    llm = FakeLLM([final("Held.")])
    run = make_agent(session, market, llm, require_market_open=False).run(portfolio.id)
    assert run.status is AgentRunStatus.COMPLETED


def test_strategy_failure_places_no_trades_but_keeps_the_transcript(
    session, market, portfolios, portfolio
):
    llm = FakeLLM(
        [
            history("AAPL"),
            propose("AAPL", "BUY", 10),
            {"content": [{"text": "..."}], "stop": "max_tokens"},
        ]
    )
    run = make_agent(session, market, llm).run(portfolio.id)

    assert run.status is AgentRunStatus.FAILED
    assert "max_tokens" in run.error
    assert run.decisions == []
    assert len(run.transcript) == 6
    assert portfolios.get_cash_balance(portfolio.id) == MILLION


def test_model_outage_fails_the_run(session, market, portfolio):
    llm = FakeLLM(error=LLMUnavailableError("Bedrock request failed: throttled"))
    run = make_agent(session, market, llm).run(portfolio.id)
    assert run.status is AgentRunStatus.FAILED
    assert run.error == "Bedrock request failed: throttled"


def test_run_key_prevents_running_twice(session, market, portfolio):
    llm = FakeLLM([history("AAPL"), propose("AAPL", "BUY", 10), final("Done.")])
    agent = make_agent(session, market, llm)

    first = agent.run(portfolio.id, run_key="daily:2026-10-20")
    second = agent.run(portfolio.id, run_key="daily:2026-10-20")

    assert second.id == first.id
    assert len(llm.calls) == 3  # only the first run talked to the model
    assert len(agent.trading.list_orders(portfolio.id)) == 1


def test_portfolio_without_a_registered_strategy(session, market, portfolios):
    manual = portfolios.create_portfolio("Manual", MILLION, "manual")
    with pytest.raises(UnknownStrategyError):
        make_agent(session, market, FakeLLM()).run(manual.id)


def test_snapshot_values_holdings_at_market(session, market, provider, portfolio):
    llm = FakeLLM([history("AAPL"), propose("AAPL", "BUY", 500), final(".")])
    make_agent(session, market, llm).run(portfolio.id)
    provider.prices["AAPL"] = Decimal("120")
    market.now.advance(seconds=61)

    run = make_agent(session, market, FakeLLM([final("Held.")])).run(portfolio.id)

    [holding] = run.input_snapshot["holdings"]
    assert holding["symbol"] == "AAPL"
    assert holding["price"] == "120.0000"
    assert holding["market_value"] == "60000.0000"


def test_research_tools_summarize_history_and_enforce_watchlist(session, market):
    tools = MarketResearchTools(session, market, WATCHLIST)

    history = tools.price_history("NVDA", 10)
    assert history["trading_days"] == 11  # the fake returns one bar per calendar day
    assert history["change_pct"] == 0.0
    assert (history["high"], history["low"]) == (201.0, 199.0)
    assert history["closes"][-1]["close"] == 200.0

    assert tools.latest_prices(["AAPL"])["prices"]["AAPL"]["price"] == 100.0
    with pytest.raises(ValueError, match="watchlist"):
        tools.latest_prices(["GME"])


def test_market_overview_summarizes_every_watchlist_symbol(session, market, provider):
    tools = MarketResearchTools(session, market, [*WATCHLIST, "SPY"])

    overview = tools.market_overview()

    assert overview["missing"] == ["SPY"]  # the fake has no SPY price
    assert list(overview["symbols"]) == WATCHLIST
    assert overview["symbols"]["MSFT"] == {
        "last_close": 400.0,
        "change_5d_pct": 0.0,
        "change_1m_pct": 0.0,
        "change_3m_pct": 0.0,
    }
    calls = provider.bar_calls
    tools.market_overview()
    # Cached symbols are reused; only SPY, which had nothing to cache, is asked for again.
    assert provider.bar_calls == calls + 1
