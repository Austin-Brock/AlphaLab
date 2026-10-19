"""Database models for portfolio accounting.

Engineering rule: no direct balance mutations. A portfolio has no cash column;
cash is always the sum of its append-only `cash_ledger` entries.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Money is stored with 4 decimal places; share quantities allow fractional shares.
Money = Numeric(20, 4)
Quantity = Numeric(20, 6)


class Base(DeclarativeBase):
    pass


class PortfolioStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class LedgerEntryType(enum.StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"
    DIVIDEND = "DIVIDEND"


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (CheckConstraint("starting_capital > 0", name="starting_capital_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    starting_capital: Mapped[Decimal] = mapped_column(Money)
    strategy_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[PortfolioStatus] = mapped_column(
        Enum(PortfolioStatus, name="portfolio_status"), default=PortfolioStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CashLedgerEntry(Base):
    """An immutable cash movement. Positive amounts add cash, negative remove it.

    The database rejects UPDATE and DELETE on this table (see the initial migration).
    """

    __tablename__ = "cash_ledger"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_nonzero"),
        UniqueConstraint("portfolio_id", "idempotency_key", name="uq_cash_ledger_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType, name="ledger_entry_type")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    description: Mapped[str] = mapped_column(String(500))
    # Links the entry to whatever caused it (e.g. an execution id from Milestone 3).
    reference_id: Mapped[str | None] = mapped_column(String(100))
    # Lets callers retry a write safely without double-posting cash.
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Position(Base):
    """Current holding of one symbol.

    This is a projection: from Milestone 3 onward it is written only by the
    execution engine and can be rebuilt from the executions table.
    """

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_positions_portfolio_symbol"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("average_cost >= 0", name="average_cost_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    average_cost: Mapped[Decimal] = mapped_column(Money)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
