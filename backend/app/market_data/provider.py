"""Provider-agnostic market data types.

Nothing outside `app.market_data.alpaca` should know Alpaca exists, so a
different data vendor (or a historical replay for backtesting) can be swapped in.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


class Timeframe(enum.StrEnum):
    MINUTE_1 = "1Min"
    MINUTE_5 = "5Min"
    MINUTE_15 = "15Min"
    HOUR_1 = "1Hour"
    DAY_1 = "1Day"


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    # When the trade happened at the exchange (not when we fetched it).
    price_time: datetime


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class MarketClock:
    is_open: bool
    next_open: datetime
    next_close: datetime


class MarketDataUnavailableError(Exception):
    """The provider could not be reached or returned an error."""


class MarketDataProvider(Protocol):
    source: str

    def get_latest_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """Latest trade price per symbol. Unknown symbols are omitted."""
        ...

    def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Historical candles in [start, end], oldest first."""
        ...

    def get_market_clock(self) -> MarketClock:
        """Whether the US stock market is open now (accounts for holidays and half-days)."""
        ...
