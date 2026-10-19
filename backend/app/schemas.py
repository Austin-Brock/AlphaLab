"""API request/response models. Decimals serialize as JSON strings to avoid float rounding."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.market_data.provider import Timeframe
from app.models import LedgerEntryType, PortfolioStatus


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    starting_capital: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    strategy_id: str = Field(min_length=1, max_length=100)


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starting_capital: Decimal
    strategy_id: str
    status: PortfolioStatus
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
