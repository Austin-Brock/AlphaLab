import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.auth import IsAdmin
from app.api.deps import MarketDataServiceDep
from app.config import get_settings
from app.market_data.provider import Timeframe
from app.schemas import BarSeriesOut, LatestPricesOut, MarketClockOut

router = APIRouter(prefix="/market", tags=["market data"])

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z.]{0,9}$")
MAX_SYMBOLS = 100
# Every bars request is fetched from Alpaca and cached in Postgres, so cap its size
# (each limit is a few thousand bars at most).
MAX_BAR_RANGE = {
    Timeframe.MINUTE_1: timedelta(days=7),
    Timeframe.MINUTE_5: timedelta(days=30),
    Timeframe.MINUTE_15: timedelta(days=60),
    Timeframe.HOUR_1: timedelta(days=365),
    Timeframe.DAY_1: timedelta(days=5 * 366),
}


def parse_symbols(raw: str) -> list[str]:
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    invalid = [s for s in symbols if not SYMBOL_PATTERN.match(s)]
    if invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid symbols: {invalid}")
    if not symbols or len(symbols) > MAX_SYMBOLS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Provide 1-{MAX_SYMBOLS} symbols"
        )
    return symbols


def check_visible(symbols: list[str], admin: bool) -> None:
    """Visitors may look up watchlist symbols only, so they can't fill the cache."""
    outside = [s for s in symbols if s not in get_settings().watchlist]
    if outside and not admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Only watchlist symbols are available: {outside}"
        )


@router.get("/watchlist", response_model=list[str])
def get_watchlist():
    return get_settings().watchlist


@router.get("/clock", response_model=MarketClockOut)
def get_clock(market: MarketDataServiceDep):
    return market.get_market_clock()


@router.get("/prices", response_model=LatestPricesOut)
def get_prices(
    market: MarketDataServiceDep,
    admin: IsAdmin,
    symbols: Annotated[
        str | None, Query(description="Comma-separated; defaults to the watchlist")
    ] = None,
):
    requested = parse_symbols(symbols) if symbols else get_settings().watchlist
    check_visible(requested, admin)
    return market.get_latest_prices(requested)


@router.get("/bars/{symbol}", response_model=BarSeriesOut)
def get_bars(
    symbol: str,
    market: MarketDataServiceDep,
    admin: IsAdmin,
    timeframe: Timeframe = Timeframe.DAY_1,
    start: datetime | None = None,
    end: datetime | None = None,
):
    symbol = symbol.upper()
    if not SYMBOL_PATTERN.match(symbol):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid symbol: {symbol}")
    check_visible([symbol], admin)
    end = _as_utc(end) if end else datetime.now(UTC)
    start = _as_utc(start) if start else end - timedelta(days=30)
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be before end")
    if end - start > MAX_BAR_RANGE[timeframe]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{timeframe.value} bars are limited to {MAX_BAR_RANGE[timeframe].days} days",
        )
    return market.get_bars(symbol, timeframe, start, end)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
