from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.market_data.provider import (
    Bar,
    MarketClock,
    MarketDataUnavailableError,
    Quote,
    Timeframe,
)

TRADE_TIME = datetime(2026, 10, 16, 19, 59, 59, tzinfo=UTC)


class FakeMarketDataProvider:
    """In-memory provider. Set `fail = True` to simulate an outage."""

    source = "fake"

    def __init__(self, prices: dict[str, Decimal] | None = None):
        self.prices = prices or {}
        self.fail = False
        self.market_open = True
        self.quote_calls: list[list[str]] = []
        self.bar_calls = 0

    def get_latest_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        self.quote_calls.append(list(symbols))
        if self.fail:
            raise MarketDataUnavailableError("fake outage")
        return {
            s: Quote(symbol=s, price=self.prices[s], price_time=TRADE_TIME)
            for s in symbols
            if s in self.prices
        }

    def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        self.bar_calls += 1
        if self.fail:
            raise MarketDataUnavailableError("fake outage")
        price = self.prices.get(symbol)
        if price is None:
            return []
        bars, day = [], start
        while day <= end:
            bars.append(Bar(symbol, timeframe, day, price, price + 1, price - 1, price, 1_000_000))
            day += timedelta(days=1)
        return bars

    def get_market_clock(self) -> MarketClock:
        if self.fail:
            raise MarketDataUnavailableError("fake outage")
        return MarketClock(
            is_open=self.market_open,
            next_open=datetime(2026, 10, 20, 13, 30, tzinfo=UTC),
            next_close=datetime(2026, 10, 19, 20, 0, tzinfo=UTC),
        )


class Clock:
    def __init__(self, start: datetime = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> None:
        self.current += timedelta(**kwargs)


class FakeLLM:
    """Replays scripted assistant turns and records what it was sent."""

    model_id = "fake-model"

    def __init__(self, turns: list[dict] | None = None, error: Exception | None = None):
        self.turns = list(turns or [])
        self.error = error
        self.calls: list[dict] = []

    def converse(self, system, messages, tools, max_tokens):
        from app.llm.client import LLMResponse

        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if self.error:
            raise self.error
        # Once the script runs out, acknowledge (e.g. the reminder to save notes).
        turn = self.turns.pop(0) if self.turns else final("Done.")
        return LLMResponse(
            message={"role": "assistant", "content": turn["content"]},
            stop_reason=turn["stop"],
            input_tokens=100,
            output_tokens=20,
        )


def tool_call(name: str, input: dict | None = None, call_id: str | None = None) -> dict:
    """An assistant turn that calls one tool."""
    return tool_calls((name, input or {}, call_id or f"call-{name}"))


def tool_calls(*calls: tuple[str, dict, str]) -> dict:
    return {
        "content": [
            {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
            *({"toolUse": {"toolUseId": i, "name": n, "input": inp}} for n, inp, i in calls),
        ],
        "stop": "tool_use",
    }


def final(text: str) -> dict:
    return {"content": [{"text": text}], "stop": "end_turn"}


def propose(symbol: str, side: str, quantity, rationale: str = "test rationale", n: int = 0):
    return tool_call(
        "propose_trade",
        {"symbol": symbol, "side": side, "quantity": quantity, "rationale": rationale},
        call_id=f"propose-{n}",
    )


def history(*symbols: str, days: int = 30) -> dict:
    """An assistant turn that pulls price history, which propose_trade requires first."""
    return tool_calls(
        *(("get_price_history", {"symbol": s, "days": days}, f"history-{s}") for s in symbols)
    )
