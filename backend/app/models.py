"""Database models for portfolio accounting, trading, and cached market data.

Engineering rule: no direct balance mutations. A portfolio has no cash column;
cash is always the sum of its append-only `cash_ledger` entries.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.market_data.provider import Timeframe

# Money is stored with 4 decimal places; share quantities allow fractional shares.
Money = Numeric(20, 4)
Quantity = Numeric(20, 6)
# A fraction between 0 and 1, e.g. 0.1000 for 10%.
Fraction = Numeric(5, 4)


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


class OrderSide(enum.StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    FILLED = "FILLED"


class AgentRunStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    # Not run at all, e.g. because the market was closed.
    SKIPPED = "SKIPPED"


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        CheckConstraint("starting_capital > 0", name="starting_capital_positive"),
        CheckConstraint(
            "max_position_pct > 0 AND max_position_pct <= 1", name="max_position_pct_range"
        ),
        CheckConstraint("min_cash_pct >= 0 AND min_cash_pct < 1", name="min_cash_pct_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    starting_capital: Mapped[Decimal] = mapped_column(Money)
    strategy_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[PortfolioStatus] = mapped_column(
        Enum(PortfolioStatus, name="portfolio_status"), default=PortfolioStatus.ACTIVE
    )
    # Risk limits, enforced by the risk engine on every order.
    max_position_pct: Mapped[Decimal] = mapped_column(Fraction, default=Decimal("0.10"))
    min_cash_pct: Mapped[Decimal] = mapped_column(Fraction, default=Decimal("0.05"))
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
    # clock_timestamp so entries written in one transaction (e.g. BUY then FEE) keep their order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


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


class LatestPrice(Base):
    """Most recent trade price fetched for a symbol; doubles as the price cache."""

    __tablename__ = "latest_prices"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Money)
    # When the trade happened at the exchange.
    price_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When AlphaLab last fetched it from the provider.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(50))


class PriceBar(Base):
    """A historical OHLCV candle (split-adjusted).

    On the free IEX feed, volume covers IEX trades only, a small slice of total market volume.
    """

    __tablename__ = "price_bars"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    timeframe: Mapped[Timeframe] = mapped_column(
        Enum(Timeframe, name="bar_timeframe", values_callable=lambda e: [m.value for m in e]),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(50))


class Order(Base):
    """A request to trade. Every order is kept, including rejected ones."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="order_quantity_positive"),
        # Resubmitting the same client_order_id returns the original order instead of a new one.
        UniqueConstraint("portfolio_id", "client_order_id", name="uq_orders_client_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="order_side"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="order_status"))
    # Who asked for the trade: "manual", or a strategy id such as "ai-trading-v1".
    source: Mapped[str] = mapped_column(String(100))
    # Market price the risk engine evaluated the order against.
    reference_price: Mapped[Decimal | None] = mapped_column(Money)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    risk_checks: Mapped[list["RiskCheckResult"]] = relationship(
        order_by="RiskCheckResult.sequence", lazy="selectin"
    )
    execution: Mapped["Execution | None"] = relationship(lazy="selectin")


class RiskCheckResult(Base):
    """The outcome of one risk check for one order, kept whether it passed or failed."""

    __tablename__ = "risk_checks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    sequence: Mapped[int] = mapped_column()
    check_name: Mapped[str] = mapped_column(String(100))
    passed: Mapped[bool] = mapped_column()
    message: Mapped[str] = mapped_column(Text)


class Execution(Base):
    """A simulated fill. At most one per order, so an order can never fill twice."""

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="execution_quantity_positive"),
        CheckConstraint("price > 0", name="execution_price_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="order_side"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    # Fill price including slippage.
    price: Mapped[Decimal] = mapped_column(Money)
    # Market price before slippage.
    market_price: Mapped[Decimal] = mapped_column(Money)
    # quantity * price, rounded to the cent.
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    commission: Mapped[Decimal] = mapped_column(Money)
    # clock_timestamp (not now) so fills within one transaction still order correctly.
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class AgentRun(Base):
    """One strategy evaluation, with everything needed to reconstruct why it decided what it did."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        # Lets a scheduler retry safely: the same run_key never runs twice for a portfolio.
        UniqueConstraint("portfolio_id", "run_key", name="uq_agent_runs_run_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    strategy_id: Mapped[str] = mapped_column(String(100))
    run_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[AgentRunStatus] = mapped_column(Enum(AgentRunStatus, name="agent_run_status"))
    model_id: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    # Holdings, cash, limits, and prices exactly as the strategy saw them.
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    # The full model conversation: every tool call, tool result, and reply.
    transcript: Mapped[list | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    decisions: Mapped[list["AgentDecision"]] = relationship(
        order_by="AgentDecision.sequence", lazy="selectin"
    )


class AgentDecision(Base):
    """One trade the strategy proposed, linked to the order it became."""

    __tablename__ = "agent_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), index=True)
    sequence: Mapped[int] = mapped_column()
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="order_side"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    rationale: Mapped[str] = mapped_column(Text)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))

    order: Mapped["Order | None"] = relationship(lazy="selectin")
