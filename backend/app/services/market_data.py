"""Market data with a Postgres-backed cache.

Latest prices are served from cache while younger than the TTL. When the
provider fails, callers get the last known data flagged as stale instead of an
error, so an outage degrades the app rather than breaking it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.market_data.provider import (
    MarketDataProvider,
    MarketDataUnavailableError,
    Timeframe,
)
from app.models import LatestPrice, PriceBar


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    price: Decimal
    price_time: datetime
    fetched_at: datetime
    source: str
    # True when the provider failed and this is older than the cache TTL.
    stale: bool


@dataclass(frozen=True)
class LatestPrices:
    prices: list[PriceSnapshot]
    # Requested symbols with no price available at all.
    missing: list[str] = field(default_factory=list)
    # Set when the provider failed during this request.
    provider_error: str | None = None


@dataclass(frozen=True)
class BarSeries:
    symbol: str
    timeframe: Timeframe
    bars: list[PriceBar]
    stale: bool = False
    provider_error: str | None = None


class MarketDataService:
    def __init__(
        self,
        session: Session,
        provider: MarketDataProvider | None,
        cache_ttl: timedelta = timedelta(seconds=60),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.session = session
        self.provider = provider
        self.cache_ttl = cache_ttl
        self.now = now

    def get_latest_prices(self, symbols: Sequence[str]) -> LatestPrices:
        symbols = list(dict.fromkeys(symbols))
        cached = self._load_latest(symbols)
        cutoff = self.now() - self.cache_ttl
        to_fetch = [s for s in symbols if s not in cached or cached[s].fetched_at < cutoff]

        provider_error = None
        if to_fetch:
            try:
                quotes = self._provider().get_latest_quotes(to_fetch)
            except MarketDataUnavailableError as exc:
                provider_error = str(exc)
            else:
                fetched_at = self.now()
                rows = [
                    {
                        "symbol": q.symbol,
                        "price": q.price,
                        "price_time": q.price_time,
                        "fetched_at": fetched_at,
                        "source": self.provider.source,
                    }
                    for q in quotes.values()
                ]
                if rows:
                    stmt = insert(LatestPrice).values(rows)
                    self.session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[LatestPrice.symbol],
                            set_={c: stmt.excluded[c] for c in rows[0] if c != "symbol"},
                        )
                    )
                    self.session.commit()
                cached = self._load_latest(symbols)

        prices = [
            PriceSnapshot(
                symbol=row.symbol,
                price=row.price,
                price_time=row.price_time,
                fetched_at=row.fetched_at,
                source=row.source,
                stale=row.fetched_at < cutoff,
            )
            for s in symbols
            if (row := cached.get(s)) is not None
        ]
        if provider_error and not prices:
            raise MarketDataUnavailableError(provider_error)
        return LatestPrices(
            prices=prices,
            missing=[s for s in symbols if s not in cached],
            provider_error=provider_error,
        )

    def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> BarSeries:
        provider_error = None
        try:
            bars = self._provider().get_bars(symbol, timeframe, start, end)
        except MarketDataUnavailableError as exc:
            provider_error = str(exc)
        else:
            fetched_at = self.now()
            rows = [
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "fetched_at": fetched_at,
                    "source": self.provider.source,
                }
                for bar in bars
            ]
            key = ("symbol", "timeframe", "timestamp")
            # Chunked to stay under Postgres's bind-parameter limit.
            for i in range(0, len(rows), 1000):
                stmt = insert(PriceBar).values(rows[i : i + 1000])
                self.session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=list(key),
                        set_={c: stmt.excluded[c] for c in rows[0] if c not in key},
                    )
                )
            self.session.commit()

        cached = list(
            self.session.scalars(
                select(PriceBar)
                .where(
                    PriceBar.symbol == symbol,
                    PriceBar.timeframe == timeframe,
                    PriceBar.timestamp >= start,
                    PriceBar.timestamp <= end,
                )
                .order_by(PriceBar.timestamp)
                .execution_options(populate_existing=True)
            )
        )
        if provider_error and not cached:
            raise MarketDataUnavailableError(provider_error)
        return BarSeries(
            symbol=symbol,
            timeframe=timeframe,
            bars=cached,
            stale=provider_error is not None,
            provider_error=provider_error,
        )

    def _load_latest(self, symbols: Sequence[str]) -> dict[str, LatestPrice]:
        # populate_existing refreshes rows already in the session after an upsert.
        rows = self.session.scalars(
            select(LatestPrice)
            .where(LatestPrice.symbol.in_(symbols))
            .execution_options(populate_existing=True)
        )
        return {row.symbol: row for row in rows}

    def _provider(self) -> MarketDataProvider:
        if self.provider is None:
            raise MarketDataUnavailableError(
                "Market data provider not configured: set ALPHALAB_ALPACA_API_KEY "
                "and ALPHALAB_ALPACA_SECRET_KEY"
            )
        return self.provider
