"""The shared strategy interface.

Engineering rule: no strategy-specific trading logic. A strategy only returns
proposals; the agent runner sends every proposal through the same risk engine
and execution path, whatever strategy produced it.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.models import OrderSide


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    side: OrderSide
    quantity: Decimal
    rationale: str


@dataclass(frozen=True)
class HoldingSnapshot:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    price: Decimal
    market_value: Decimal
    # Fraction of total portfolio value.
    weight: Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    """The portfolio exactly as the strategy saw it. Stored with every agent run."""

    portfolio_id: uuid.UUID
    as_of: datetime
    cash: Decimal
    total_value: Decimal
    holdings: list[HoldingSnapshot]
    max_position_pct: Decimal
    min_cash_pct: Decimal
    market_open: bool | None
    # symbol -> latest price for every watchlist symbol that had one
    prices: dict[str, Decimal]

    def max_buy_value(self, symbol: str) -> Decimal:
        """Largest buy (in dollars) that stays within the concentration and cash limits."""
        held = next((h.market_value for h in self.holdings if h.symbol == symbol), Decimal("0"))
        concentration_room = self.max_position_pct * self.total_value - held
        cash_room = self.cash - self.min_cash_pct * self.total_value
        return max(Decimal("0"), min(concentration_room, cash_room))

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_id": str(self.portfolio_id),
            "as_of": self.as_of.isoformat(),
            "cash": str(self.cash),
            "total_value": str(self.total_value),
            "max_position_pct": str(self.max_position_pct),
            "min_cash_pct": str(self.min_cash_pct),
            "market_open": self.market_open,
            "holdings": [
                {
                    "symbol": h.symbol,
                    "quantity": str(h.quantity),
                    "average_cost": str(h.average_cost),
                    "price": str(h.price),
                    "market_value": str(h.market_value),
                    "weight": str(h.weight),
                }
                for h in self.holdings
            ],
            "prices": {symbol: str(price) for symbol, price in self.prices.items()},
        }


class ResearchTools(Protocol):
    """Read-only market data a strategy may use. Restricted to the watchlist."""

    def latest_prices(self, symbols: Sequence[str]) -> dict[str, Any]: ...

    def price_history(self, symbol: str, days: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StrategyContext:
    snapshot: PortfolioSnapshot
    watchlist: list[str]
    max_proposals: int
    research: ResearchTools


@dataclass
class StrategyResult:
    proposals: list[TradeProposal]
    summary: str
    model_id: str | None = None
    prompt_version: str | None = None
    # Full model conversation, including every tool call and result.
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class StrategyError(Exception):
    """The strategy could not produce a decision. No trades are placed."""

    def __init__(self, message: str, partial: StrategyResult | None = None):
        super().__init__(message)
        self.partial = partial


class TradingStrategy(ABC):
    strategy_id: str

    @abstractmethod
    def generate_proposals(self, context: StrategyContext) -> StrategyResult: ...
