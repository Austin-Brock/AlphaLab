import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import OrderSide
from app.strategies.ai import PROMPT_VERSION, WRAP_UP_NOTE, AITradingStrategy
from app.strategies.base import (
    HoldingSnapshot,
    PortfolioSnapshot,
    StrategyContext,
    StrategyError,
)
from tests.fakes import FakeLLM, final, history, propose, tool_call, tool_calls

WATCHLIST = ["AAPL", "MSFT", "NVDA"]


class FakeResearch:
    def __init__(self):
        self.calls = []

    def latest_prices(self, symbols):
        self.calls.append(("latest_prices", list(symbols)))
        return {"prices": {s: {"price": 100.0} for s in symbols}, "missing": []}

    def price_history(self, symbol, days):
        self.calls.append(("price_history", symbol, days))
        return {"symbol": symbol, "days": days, "change_pct": 5.0}

    def market_overview(self):
        self.calls.append(("market_overview",))
        return {"symbols": {"AAPL": {"last_close": 100.0, "change_1m_pct": 5.0}}, "missing": []}


def snapshot(**overrides) -> PortfolioSnapshot:
    base = dict(
        portfolio_id=uuid.uuid4(),
        as_of=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        cash=Decimal("900000"),
        total_value=Decimal("1000000"),
        holdings=[
            HoldingSnapshot(
                "AAPL",
                Decimal("400"),
                Decimal("240"),
                Decimal("250"),
                Decimal("100000"),
                Decimal("0.1"),
            )
        ],
        max_position_pct=Decimal("0.10"),
        min_cash_pct=Decimal("0.05"),
        market_open=True,
        prices={"AAPL": Decimal("250"), "MSFT": Decimal("400"), "NVDA": Decimal("200")},
    )
    return PortfolioSnapshot(**(base | overrides))


@pytest.fixture
def research() -> FakeResearch:
    return FakeResearch()


def context(research, max_proposals: int = 5, **snap) -> StrategyContext:
    return StrategyContext(snapshot(**snap), WATCHLIST, max_proposals, research)


def tool_results(llm: FakeLLM, call_index: int) -> list[dict]:
    """The tool results sent to the model on its Nth call."""
    last = llm.calls[call_index]["messages"][-1]
    return [b["toolResult"] for b in last["content"]]


def test_full_session_produces_proposals_and_a_transcript(research):
    llm = FakeLLM(
        [
            tool_call("get_portfolio"),
            tool_call("get_price_history", {"symbol": "msft", "days": 90}),
            propose("MSFT", "BUY", 200, "Up 5% over 90 days", n=1),
            tool_call("save_notes", {"notes": "Add to MSFT if the trend holds."}),
            final("Bought MSFT on momentum."),
        ]
    )

    result = AITradingStrategy(llm).generate_proposals(context(research))

    [proposal] = result.proposals
    assert proposal.symbol == "MSFT"
    assert proposal.side is OrderSide.BUY
    assert proposal.quantity == Decimal(200)
    assert proposal.rationale == "Up 5% over 90 days"
    assert result.summary == "Bought MSFT on momentum."
    assert (result.model_id, result.prompt_version) == ("fake-model", PROMPT_VERSION)
    assert (result.input_tokens, result.output_tokens) == (500, 100)
    assert result.notes == "Add to MSFT if the trend holds."
    assert research.calls == [("price_history", "MSFT", 90)]
    # user kickoff + 5 assistant turns + 4 tool-result turns; no reminders needed
    assert len(result.transcript) == 10
    assert result.transcript[-1] == {"role": "assistant", "content": [{"text": result.summary}]}


def test_get_portfolio_reports_holdings_limits_and_buying_room(research):
    llm = FakeLLM([tool_call("get_portfolio"), final("Holding.")])
    AITradingStrategy(llm).generate_proposals(context(research))

    [result] = tool_results(llm, 1)
    portfolio = result["content"][0]["json"]
    assert portfolio["cash"] == 900000.0
    assert portfolio["holdings"][0]["weight_pct"] == 10.0
    assert portfolio["limits"] == {
        "max_position_pct": 10.0,
        "min_cash_pct": 5.0,
        "max_proposals": 5,
    }
    # AAPL already at the 10% cap; others can take a full $100K.
    assert portfolio["max_buy_value"] == {"AAPL": 0.0, "MSFT": 100000.0, "NVDA": 100000.0}


def test_max_buy_value_is_limited_by_cash_reserve():
    snap = snapshot(cash=Decimal("80000"), holdings=[])
    # Must keep 5% of $1M = $50K in cash, so only $30K can be spent.
    assert snap.max_buy_value("MSFT") == Decimal("30000")


def test_symbols_outside_the_watchlist_are_refused(research):
    llm = FakeLLM([propose("GME", "BUY", 10), final("Done.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))

    assert result.proposals == []
    [error] = tool_results(llm, 1)
    assert "Not in the watchlist" in error["content"][0]["json"]["error"]


@pytest.mark.parametrize(
    ("quantity", "side", "message"),
    [(1.5, "BUY", "whole number"), (0, "BUY", "whole number"), (10, "HOLD", "BUY or SELL")],
)
def test_invalid_proposals_are_refused(research, quantity, side, message):
    llm = FakeLLM([history("AAPL"), propose("AAPL", side, quantity), final("Done.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.proposals == []
    assert message in tool_results(llm, 2)[0]["content"][0]["json"]["error"]


def test_proposal_limit_is_enforced(research):
    turns = [history("MSFT"), *(propose("MSFT", "BUY", 1, n=i) for i in range(3)), final("Done.")]
    llm = FakeLLM(turns)
    result = AITradingStrategy(llm).generate_proposals(context(research, max_proposals=2))
    assert len(result.proposals) == 2
    assert "Limit of 2 proposals" in tool_results(llm, 4)[0]["content"][0]["json"]["error"]


def test_multiple_tool_calls_in_one_turn_get_one_result_each(research):
    llm = FakeLLM(
        [
            tool_calls(
                ("get_latest_prices", {"symbols": ["AAPL"]}, "a"),
                ("get_price_history", {"symbol": "NVDA", "days": 30}, "b"),
            ),
            final("Done."),
        ]
    )
    AITradingStrategy(llm).generate_proposals(context(research))
    assert [r["toolUseId"] for r in tool_results(llm, 1)] == ["a", "b"]


def test_unknown_tool_is_reported_to_the_model(research):
    llm = FakeLLM([tool_call("place_order_directly"), final("Done.")])
    AITradingStrategy(llm).generate_proposals(context(research))
    assert "Unknown tool" in tool_results(llm, 1)[0]["content"][0]["json"]["error"]


def test_tool_failures_are_reported_not_raised(research):
    def broken(symbol, days):
        raise RuntimeError("market data outage")

    research.price_history = broken
    llm = FakeLLM([tool_call("get_price_history", {"symbol": "AAPL", "days": 30}), final("Held.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.summary == "Held."
    assert "market data outage" in tool_results(llm, 1)[0]["content"][0]["json"]["error"]


def test_session_that_never_finishes_fails_with_partial_transcript(research):
    llm = FakeLLM([tool_call("get_portfolio", call_id=f"c{i}") for i in range(3)])
    with pytest.raises(StrategyError, match="did not finish within 3 turns") as exc_info:
        AITradingStrategy(llm, max_turns=3).generate_proposals(context(research))
    assert exc_info.value.partial.input_tokens == 300
    assert len(exc_info.value.partial.transcript) == 7


def test_model_is_told_to_wrap_up_before_the_turn_limit(research):
    llm = FakeLLM(
        [
            tool_call("get_portfolio", call_id="c0"),
            history("AAPL"),
            propose("AAPL", "BUY", 1),
            tool_call("save_notes", {"notes": "Watching AAPL."}),
            final("Bought AAPL."),
        ]
    )
    result = AITradingStrategy(llm, max_turns=5).generate_proposals(context(research))

    def note_sent(call):
        return {"text": WRAP_UP_NOTE} in llm.calls[call]["messages"][-1]["content"]

    # Five turns: the note goes with the results of the second, leaving three.
    assert [note_sent(i) for i in range(1, 5)] == [False, True, False, False]
    assert len(result.proposals) == 1
    assert result.summary == "Bought AAPL."


def test_truncated_reply_fails(research):
    llm = FakeLLM([{"content": [{"text": "I think we should"}], "stop": "max_tokens"}])
    with pytest.raises(StrategyError, match="max_tokens"):
        AITradingStrategy(llm).generate_proposals(context(research))


def test_system_prompt_states_the_rules(research):
    llm = FakeLLM([final("Held.")])
    AITradingStrategy(llm).generate_proposals(context(research, max_proposals=3))
    system = llm.calls[0]["system"]
    assert "AAPL, MSFT, NVDA" in system
    assert "exceed 10%" in system
    assert "At least 5%" in system
    assert "At most 3 proposals" in system
    assert "market is open" in llm.calls[0]["messages"][0]["content"][0]["text"]


def test_proposals_require_price_history_for_the_symbol(research):
    llm = FakeLLM(
        [
            tool_call("get_latest_prices", {"symbols": ["NVDA"]}),
            propose("NVDA", "BUY", 10, n=1),
            history("MSFT"),
            propose("NVDA", "BUY", 10, n=2),
            history("NVDA"),
            propose("NVDA", "BUY", 10, n=3),
            final("Bought NVDA after checking its history."),
        ]
    )
    result = AITradingStrategy(llm).generate_proposals(context(research))

    # Refused until NVDA's own history was pulled; a different symbol's doesn't count.
    for call in (2, 4):
        error = tool_results(llm, call)[0]["content"][0]["json"]["error"]
        assert "Call get_price_history for NVDA" in error
    [proposal] = result.proposals
    assert proposal.symbol == "NVDA"


def test_failed_price_history_does_not_count_as_research(research):
    def broken(symbol, days):
        raise RuntimeError("market data outage")

    research.price_history = broken
    llm = FakeLLM([history("AAPL"), propose("AAPL", "SELL", 10), final("Held.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.proposals == []


def test_market_overview_tool_screens_without_counting_as_research(research):
    llm = FakeLLM([tool_call("get_market_overview"), propose("AAPL", "BUY", 10), final("Done.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))

    overview = result.transcript[2]["content"][0]["toolResult"]["content"][0]["json"]
    assert overview["symbols"]["AAPL"]["change_1m_pct"] == 5.0
    # The overview alone isn't enough to trade: price history is still required.
    assert result.proposals == []
    error = result.transcript[4]["content"][0]["toolResult"]["content"][0]["json"]["error"]
    assert "get_price_history" in error


def test_notes_are_saved_for_the_next_session(research):
    llm = FakeLLM(
        [
            tool_call("save_notes", {"notes": "first draft"}, call_id="n1"),
            tool_call("save_notes", {"notes": "Watching AMD for a pullback."}, call_id="n2"),
            final("Held."),
        ]
    )
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.notes == "Watching AMD for a pullback."


def test_notes_must_be_short(research):
    llm = FakeLLM([tool_call("save_notes", {"notes": "x" * 1001}), final("Held.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.notes is None
    error = result.transcript[2]["content"][0]["toolResult"]["content"][0]["json"]["error"]
    assert "under 1000" in error


def test_first_session_is_told_there_is_no_memory(research):
    llm = FakeLLM([final("Held.")])
    AITradingStrategy(llm).generate_proposals(context(research))
    first = llm.calls[0]["messages"][0]["content"]
    assert "no memory yet" in first[1]["text"]


def test_memory_is_shown_in_the_first_message(research):
    ctx = context(research)
    memory = {"notes_from_last_session": {"date": "2026-10-20", "notes": "Watch AMD."}}
    llm = FakeLLM([final("Held.")])
    AITradingStrategy(llm).generate_proposals(
        StrategyContext(ctx.snapshot, ctx.watchlist, ctx.max_proposals, research, memory)
    )
    text = llm.calls[0]["messages"][0]["content"][1]["text"]
    assert "Watch AMD." in text
    assert "context, not a commitment" in llm.calls[0]["system"]


def test_trade_written_as_text_is_pointed_out_once(research):
    llm = FakeLLM(
        [
            history("MSFT"),
            final('```json\n{"symbol": "MSFT", "side": "BUY", "quantity": 5}\n```'),
            propose("MSFT", "BUY", 5),
            tool_call("save_notes", {"notes": "Watch MSFT."}),
            final("Bought MSFT."),
        ]
    )
    result = AITradingStrategy(llm).generate_proposals(context(research))

    [proposal] = result.proposals
    assert proposal.symbol == "MSFT"
    assert result.summary == "Bought MSFT."
    nudge = result.transcript[4]
    assert nudge["role"] == "user" and "propose_trade tool" in nudge["content"][0]["text"]


def test_missing_notes_get_one_reminder_and_the_summary_is_kept(research):
    llm = FakeLLM(
        [final("Held: nothing looked strong."), tool_call("save_notes", {"notes": "Watch AMD."})]
    )
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert result.notes == "Watch AMD."
    assert result.summary == "Held: nothing looked strong."


def test_the_notes_reminder_is_not_repeated(research):
    llm = FakeLLM([final("Held."), final("Done.")])
    result = AITradingStrategy(llm).generate_proposals(context(research))
    assert (result.summary, result.notes) == ("Held.", None)
    assert len(llm.calls) == 2


def test_prompt_says_there_is_no_news(research):
    llm = FakeLLM([final("Held.")])
    AITradingStrategy(llm).generate_proposals(context(research))
    assert "no news" in llm.calls[0]["system"]
