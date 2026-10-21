"""The AI strategy: a tool-using model researches the watchlist and proposes trades.

The model never executes anything. `propose_trade` only records a proposal; the
agent runner sends proposals to the risk engine after the model has finished.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.llm.client import LLMClient, ToolSpec
from app.models import OrderSide
from app.strategies.base import (
    StrategyContext,
    StrategyError,
    StrategyResult,
    TradeProposal,
    TradingStrategy,
)

# Bump whenever SYSTEM_PROMPT or the tool definitions change, so every stored
# run records exactly which instructions produced it.
PROMPT_VERSION = "ai-trading-v1.3"

SYSTEM_PROMPT = """\
You are the portfolio manager for AlphaLab, a simulated portfolio that trades real \
US stocks with simulated money. Your goal is strong risk-adjusted returns over months, \
not days.

The first message includes your memory from earlier sessions on this portfolio, when \
there are any: the notes you left last time, recent sessions and how their trades turned \
out, why you bought what you hold and how it has done, and your return since your first \
trade next to simply holding the benchmark. Treat it as context, not a commitment: \
check whether each earlier reason still holds, and change course when the data has changed.

Each session:
1. Call get_portfolio to see cash, holdings, limits, and how much you can buy of each symbol.
2. Call get_market_overview to see recent performance of every symbol you can trade, \
and use it to pick a short list worth a closer look.
3. Research that short list with get_price_history (and get_latest_prices if useful). \
You must call get_price_history for a symbol before you can propose a trade in it.
4. Call propose_trade once per trade you want to make. Proposing nothing is a valid decision.
5. Call save_notes with a short plan for your next session: what you are watching, and \
what would make you buy, sell or hold. Your next session sees these notes.
6. Finish with a short plain-text summary of what you decided and why.

Rules (enforced by a separate risk engine; orders that break them are rejected, not resized):
- Trade only these symbols: {watchlist}.
- No single stock may exceed {max_position} of total portfolio value after a buy.
- At least {min_cash} of the portfolio must remain in cash after a buy.
- You can only sell shares you hold. No short selling.
- Whole shares only. At most {max_proposals} proposals per session.
- Buys fill about 0.05% above the quoted price, so size buys 1-2% below the \
max_buy_value that get_portfolio reports.

Base every decision on the data the tools return. In each proposal's rationale, cite \
the specific numbers that drove it.
"""

MAX_NOTES_CHARS = 1000

TOOLS = [
    ToolSpec(
        name="get_portfolio",
        description=(
            "Current cash, total value, holdings with their portfolio weights, risk limits, "
            "and max_buy_value: the largest dollar amount you can buy of each symbol."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="get_market_overview",
        description=(
            "Every watchlist symbol's last close and percent change over the last 5, 21 and "
            "63 trading days (about a week, a month and three months). Use it to choose "
            "which symbols to research."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="get_latest_prices",
        description="Latest trade price for one or more watchlist symbols.",
        input_schema={
            "type": "object",
            "properties": {"symbols": {"type": "array", "items": {"type": "string"}}},
            "required": ["symbols"],
        },
    ),
    ToolSpec(
        name="get_price_history",
        description=(
            "Daily closing prices and summary statistics (change, high, low, average volume) "
            "for one watchlist symbol over the last N calendar days."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "days": {"type": "integer", "minimum": 5, "maximum": 365},
            },
            "required": ["symbol", "days"],
        },
    ),
    ToolSpec(
        name="save_notes",
        description=(
            "Leave notes for your next session on this portfolio, such as what you are "
            "watching and the conditions for your next move. Calling it again replaces "
            f"the notes. At most {MAX_NOTES_CHARS} characters."
        ),
        input_schema={
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "required": ["notes"],
        },
    ),
    ToolSpec(
        name="propose_trade",
        description=(
            "Propose one trade. Requires a get_price_history call for the symbol first. It is "
            "not executed now: after you finish, a risk engine checks it against the rules and "
            "fills or rejects it."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                "quantity": {"type": "integer", "minimum": 1},
                "rationale": {
                    "type": "string",
                    "description": "Why, citing the specific data behind the decision.",
                },
            },
            "required": ["symbol", "side", "quantity", "rationale"],
        },
    ),
]


class ToolInputError(Exception):
    """Bad tool input; reported back to the model so it can correct itself."""


def _num(value: Decimal) -> float:
    # Tool results are for the model to read, so plain numbers are clearer than strings.
    return round(float(value), 4)


@dataclass
class _Session:
    context: StrategyContext
    proposals: list[TradeProposal] = field(default_factory=list)
    # Symbols whose price history the model has pulled this session.
    researched: set[str] = field(default_factory=set)
    notes: str | None = None

    def get_portfolio(self, _: dict[str, Any]) -> dict[str, Any]:
        snap = self.context.snapshot
        return {
            "as_of": snap.as_of.isoformat(),
            "market_open": snap.market_open,
            "cash": _num(snap.cash),
            "total_value": _num(snap.total_value),
            "holdings": [
                {
                    "symbol": h.symbol,
                    "quantity": _num(h.quantity),
                    "average_cost": _num(h.average_cost),
                    "price": _num(h.price),
                    "market_value": _num(h.market_value),
                    "weight_pct": round(float(h.weight) * 100, 2),
                }
                for h in snap.holdings
            ],
            "limits": {
                "max_position_pct": round(float(snap.max_position_pct) * 100, 2),
                "min_cash_pct": round(float(snap.min_cash_pct) * 100, 2),
                "max_proposals": self.context.max_proposals,
            },
            "max_buy_value": {s: _num(snap.max_buy_value(s)) for s in self.context.watchlist},
        }

    def get_market_overview(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.context.research.market_overview()

    def get_latest_prices(self, args: dict[str, Any]) -> dict[str, Any]:
        symbols = [str(s).upper() for s in args.get("symbols") or []]
        if not symbols:
            raise ToolInputError("Provide at least one symbol")
        return self.context.research.latest_prices(self._check_watchlist(symbols))

    def get_price_history(self, args: dict[str, Any]) -> dict[str, Any]:
        [symbol] = self._check_watchlist([str(args.get("symbol", "")).upper()])
        try:
            days = int(args.get("days", 30))
        except (TypeError, ValueError) as exc:
            raise ToolInputError("days must be an integer") from exc
        history = self.context.research.price_history(symbol, max(5, min(days, 365)))
        self.researched.add(symbol)
        return history

    def save_notes(self, args: dict[str, Any]) -> dict[str, Any]:
        notes = str(args.get("notes", "")).strip()
        if not notes:
            raise ToolInputError("notes must not be empty")
        if len(notes) > MAX_NOTES_CHARS:
            raise ToolInputError(
                f"Notes are {len(notes)} characters; keep them under {MAX_NOTES_CHARS}."
            )
        self.notes = notes
        return {"saved": True}

    def propose_trade(self, args: dict[str, Any]) -> dict[str, Any]:
        if len(self.proposals) >= self.context.max_proposals:
            raise ToolInputError(
                f"Limit of {self.context.max_proposals} proposals reached; finish the session."
            )
        [symbol] = self._check_watchlist([str(args.get("symbol", "")).upper()])
        if symbol not in self.researched:
            # Keeps decisions grounded in data rather than the latest price alone.
            raise ToolInputError(
                f"Call get_price_history for {symbol} before proposing a trade in it."
            )
        try:
            side = OrderSide(str(args.get("side", "")).upper())
        except ValueError as exc:
            raise ToolInputError("side must be BUY or SELL") from exc
        try:
            quantity = Decimal(str(args.get("quantity")))
        except InvalidOperation as exc:
            raise ToolInputError("quantity must be a whole number of shares") from exc
        if quantity <= 0 or quantity != quantity.to_integral_value():
            raise ToolInputError("quantity must be a positive whole number of shares")
        rationale = str(args.get("rationale", "")).strip()
        if not rationale:
            raise ToolInputError("rationale is required")
        self.proposals.append(TradeProposal(symbol, side, quantity, rationale))
        return {
            "recorded": True,
            "proposal_number": len(self.proposals),
            "remaining_proposals": self.context.max_proposals - len(self.proposals),
        }

    def _check_watchlist(self, symbols: list[str]) -> list[str]:
        outside = [s for s in symbols if s not in self.context.watchlist]
        if outside:
            raise ToolInputError(
                f"Not in the watchlist: {outside}. Allowed: {self.context.watchlist}"
            )
        return symbols


class AITradingStrategy(TradingStrategy):
    strategy_id = "ai-trading-v1"

    def __init__(self, llm: LLMClient, max_turns: int = 20, max_tokens: int = 4096):
        self.llm = llm
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    def generate_proposals(self, context: StrategyContext) -> StrategyResult:
        session = _Session(context)
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_portfolio": session.get_portfolio,
            "get_market_overview": session.get_market_overview,
            "get_latest_prices": session.get_latest_prices,
            "get_price_history": session.get_price_history,
            "propose_trade": session.propose_trade,
            "save_notes": session.save_notes,
        }
        system = SYSTEM_PROMPT.format(
            watchlist=", ".join(context.watchlist),
            max_position=f"{context.snapshot.max_position_pct * 100:.0f}%",
            min_cash=f"{context.snapshot.min_cash_pct * 100:.0f}%",
            max_proposals=context.max_proposals,
        )
        market = {True: "open", False: "closed", None: "unknown"}[context.snapshot.market_open]
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "text": f"It is {context.snapshot.as_of:%Y-%m-%d %H:%M} UTC and the US "
                        f"market is {market}. Review the portfolio and decide which trades, "
                        "if any, to make."
                    },
                    {"text": self._memory_text(context.memory)},
                ],
            }
        ]
        result = StrategyResult(
            proposals=session.proposals,
            summary="",
            model_id=self.llm.model_id,
            prompt_version=PROMPT_VERSION,
            transcript=messages,
        )

        for _ in range(self.max_turns):
            response = self.llm.converse(system, messages, TOOLS, self.max_tokens)
            result.input_tokens += response.input_tokens
            result.output_tokens += response.output_tokens
            messages.append(response.message)

            tool_uses = [b["toolUse"] for b in response.message["content"] if "toolUse" in b]
            if tool_uses:
                messages.append(
                    {"role": "user", "content": [self._run_tool(handlers, t) for t in tool_uses]}
                )
                result.notes = session.notes
                continue
            if response.stop_reason == "end_turn":
                result.summary = "\n".join(
                    b["text"] for b in response.message["content"] if "text" in b
                ).strip()
                return result
            raise StrategyError(f"Model stopped unexpectedly ({response.stop_reason})", result)

        raise StrategyError(f"Model did not finish within {self.max_turns} turns", result)

    @staticmethod
    def _memory_text(memory: dict[str, Any]) -> str:
        if not memory:
            return "This is your first session on this portfolio, so there is no memory yet."
        return "Your memory from earlier sessions (JSON):\n" + json.dumps(memory, default=str)

    @staticmethod
    def _run_tool(
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]], tool_use: dict[str, Any]
    ) -> dict[str, Any]:
        handler = handlers.get(tool_use["name"])
        try:
            if handler is None:
                raise ToolInputError(f"Unknown tool {tool_use['name']}")
            output = handler(tool_use.get("input") or {})
        except ToolInputError as exc:
            output = {"error": str(exc)}
        except Exception as exc:  # e.g. market data outage; let the model carry on
            output = {"error": f"Tool failed: {exc}"}
        # Round-trip through JSON so the stored transcript holds only JSON types.
        # Errors go in the content: Converse's "status" field isn't supported by every model.
        content = json.loads(json.dumps(output, default=str))
        return {"toolResult": {"toolUseId": tool_use["toolUseId"], "content": [{"json": content}]}}
