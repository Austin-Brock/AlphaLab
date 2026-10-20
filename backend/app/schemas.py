"""API request/response models. Decimals serialize as JSON strings to avoid float rounding."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.market_data.provider import Timeframe
from app.models import AgentRunStatus, LedgerEntryType, OrderSide, OrderStatus, PortfolioStatus


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    starting_capital: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    strategy_id: str = Field(min_length=1, max_length=100)
    max_position_pct: Decimal = Field(default=Decimal("0.10"), gt=0, le=1, decimal_places=4)
    min_cash_pct: Decimal = Field(default=Decimal("0.05"), ge=0, lt=1, decimal_places=4)


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starting_capital: Decimal
    strategy_id: str
    status: PortfolioStatus
    max_position_pct: Decimal
    min_cash_pct: Decimal
    created_at: datetime


class PortfolioSummary(PortfolioOut):
    cash: Decimal
    positions_value: Decimal
    total_value: Decimal


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    quantity: Decimal
    average_cost: Decimal


class CashBalanceOut(BaseModel):
    portfolio_id: uuid.UUID
    cash: Decimal


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_type: LedgerEntryType
    amount: Decimal
    description: str
    reference_id: str | None
    created_at: datetime


class PositionValuationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    quantity: Decimal
    average_cost: Decimal
    price: Decimal
    priced_at_cost: bool
    market_value: Decimal


class PortfolioValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: uuid.UUID
    cash: Decimal
    positions_value: Decimal
    total_value: Decimal
    positions: list[PositionValuationOut]


class PriceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    price: Decimal
    price_time: datetime
    fetched_at: datetime
    source: str
    stale: bool


class LatestPricesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prices: list[PriceSnapshotOut]
    missing: list[str]
    provider_error: str | None


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class BarSeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timeframe: Timeframe
    bars: list[BarOut]
    stale: bool
    provider_error: str | None


class OrderCreate(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z][A-Za-z.]{0,9}$")
    side: OrderSide
    # Whole shares only in V1.
    quantity: int = Field(gt=0, le=1_000_000)
    # Optional; resubmitting the same id returns the original order instead of trading twice.
    client_order_id: str | None = Field(default=None, min_length=1, max_length=100)


class RiskCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_name: str
    passed: bool
    message: str


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    market_price: Decimal
    gross_amount: Decimal
    commission: Decimal
    executed_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    status: OrderStatus
    source: str
    reference_price: Decimal | None
    rejection_reason: str | None
    created_at: datetime
    risk_checks: list[RiskCheckOut]
    execution: ExecutionOut | None


class AgentRunCreate(BaseModel):
    # Optional; a run with the same key for this portfolio is returned instead of re-run.
    run_key: str | None = Field(default=None, min_length=1, max_length=200)


class AgentDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    symbol: str
    side: OrderSide
    quantity: Decimal
    rationale: str
    order: OrderOut | None


class AgentRunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    strategy_id: str
    run_key: str | None
    status: AgentRunStatus
    model_id: str | None
    prompt_version: str | None
    summary: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    started_at: datetime
    finished_at: datetime | None
    decisions: list[AgentDecisionOut]


class AgentRunOut(AgentRunSummaryOut):
    input_snapshot: dict
    transcript: list | None
