"""Portfolio accounting.

This service knows nothing about strategies, LLMs, or market data providers.
Its only job is keeping accurate financial records.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CashLedgerEntry, LedgerEntryType, Portfolio, Position


class PortfolioNotFoundError(Exception):
    def __init__(self, portfolio_id: uuid.UUID):
        super().__init__(f"Portfolio {portfolio_id} not found")
        self.portfolio_id = portfolio_id


@dataclass(frozen=True)
class PositionValuation:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    price: Decimal
    # True when no market price was supplied and the position is valued at cost.
    priced_at_cost: bool

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.price


@dataclass(frozen=True)
class PortfolioValuation:
    portfolio_id: uuid.UUID
    cash: Decimal
    positions: list[PositionValuation]

    @property
    def positions_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions), Decimal("0"))

    @property
    def total_value(self) -> Decimal:
        return self.cash + self.positions_value


class PortfolioService:
    def __init__(self, session: Session):
        self.session = session

    def create_portfolio(self, name: str, starting_capital: Decimal, strategy_id: str) -> Portfolio:
        """Create a portfolio funded by a single opening DEPOSIT ledger entry."""
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")

        portfolio = Portfolio(name=name, starting_capital=starting_capital, strategy_id=strategy_id)
        self.session.add(portfolio)
        self.session.flush()
        self.session.add(
            CashLedgerEntry(
                portfolio_id=portfolio.id,
                entry_type=LedgerEntryType.DEPOSIT,
                amount=starting_capital,
                description="Starting capital",
                idempotency_key="starting-capital",
            )
        )
        self.session.commit()
        return portfolio

    def list_portfolios(self) -> list[Portfolio]:
        return list(self.session.scalars(select(Portfolio).order_by(Portfolio.created_at)))

    def get_portfolio(self, portfolio_id: uuid.UUID) -> Portfolio:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)
        return portfolio

    def get_positions(self, portfolio_id: uuid.UUID) -> list[Position]:
        self.get_portfolio(portfolio_id)
        return list(
            self.session.scalars(
                select(Position)
                .where(Position.portfolio_id == portfolio_id, Position.quantity > 0)
                .order_by(Position.symbol)
            )
        )

    def get_cash_balance(self, portfolio_id: uuid.UUID) -> Decimal:
        self.get_portfolio(portfolio_id)
        total = self.session.scalar(
            select(func.coalesce(func.sum(CashLedgerEntry.amount), 0)).where(
                CashLedgerEntry.portfolio_id == portfolio_id
            )
        )
        return Decimal(total)

    def get_ledger(self, portfolio_id: uuid.UUID) -> list[CashLedgerEntry]:
        self.get_portfolio(portfolio_id)
        return list(
            self.session.scalars(
                select(CashLedgerEntry)
                .where(CashLedgerEntry.portfolio_id == portfolio_id)
                .order_by(CashLedgerEntry.created_at, CashLedgerEntry.id)
            )
        )

    def calculate_portfolio_value(
        self, portfolio_id: uuid.UUID, prices: Mapping[str, Decimal] | None = None
    ) -> PortfolioValuation:
        """Value the portfolio as cash plus positions.

        `prices` maps symbol to current price. Positions without a supplied price
        are valued at average cost and flagged, until market data lands in Milestone 2.
        """
        prices = prices or {}
        valuations = [
            PositionValuation(
                symbol=p.symbol,
                quantity=p.quantity,
                average_cost=p.average_cost,
                price=prices.get(p.symbol, p.average_cost),
                priced_at_cost=p.symbol not in prices,
            )
            for p in self.get_positions(portfolio_id)
        ]
        return PortfolioValuation(
            portfolio_id=portfolio_id,
            cash=self.get_cash_balance(portfolio_id),
            positions=valuations,
        )
