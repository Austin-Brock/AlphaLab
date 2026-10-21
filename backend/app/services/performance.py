"""Portfolio value over time, compared with simply holding a benchmark (SPY).

The comparison starts when the portfolio first trades, not when it was created,
so days spent waiting in cash before the first trade don't count against it.

The history is rebuilt from the recorded ledger and fills plus daily closing
prices, so nothing extra is stored and it is complete back to the first day.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.provider import MarketDataUnavailableError, Timeframe
from app.models import CashLedgerEntry, Execution, OrderSide
from app.services.market_data import MarketDataService
from app.services.portfolio import MONEY_PLACES, PortfolioService

EASTERN = ZoneInfo("America/New_York")
# Daily closes change at most once a day, so the public dashboard's polling
# shouldn't call the provider on every refresh.
BAR_MAX_AGE = timedelta(minutes=15)


@dataclass(frozen=True)
class ValuePoint:
    date: date
    value: Decimal
    # What the starting capital would be worth if it had all bought the benchmark
    # at the first point. None when no benchmark price is available.
    benchmark_value: Decimal | None


@dataclass(frozen=True)
class Fill:
    date: date
    symbol: str
    # Positive for buys, negative for sells.
    quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class ValueHistory:
    portfolio_id: uuid.UUID
    benchmark: str
    points: list[ValuePoint]
    # True when the provider failed and some prices came from older cached data.
    stale: bool


def eastern_date(moment: datetime) -> date:
    return moment.astimezone(EASTERN).date()


def build_history(
    starting_capital: Decimal,
    started: date,
    cash_flows: Sequence[tuple[date, Decimal]],
    fills: Sequence[Fill],
    closes: Mapping[str, Mapping[date, Decimal]],
    benchmark: str,
    live: tuple[date, Mapping[str, Decimal]] | None = None,
) -> list[ValuePoint]:
    """One point per trading day's close from `started` (the first day it traded).

    The first point is the close before that, when it was all cash: that is where
    the benchmark is bought. `live` adds (or replaces) the latest day using
    current prices, so the last point matches the value shown on the dashboard.
    """
    days = sorted(closes.get(benchmark) or {d for c in closes.values() for d in c})
    earlier = [d for d in days if d < started]
    base = earlier[-1] if earlier else None
    dates = [d for d in days if d >= started]
    live_prices: Mapping[str, Decimal] = {}
    if live and live[0] >= max(dates, default=started):
        live_prices = live[1]
        if not dates or live[0] > dates[-1]:
            dates.append(live[0])
    if not dates and base is None:
        dates = [started]

    def price(symbol: str, day: date) -> Decimal | None:
        if live_prices and day == dates[-1] and symbol in live_prices:
            return live_prices[symbol]
        known = [d for d in closes.get(symbol, {}) if d <= day]
        if known:
            return closes[symbol][max(known)]
        # No close yet (e.g. bought today): fall back to the last fill price.
        paid = [f.price for f in fills if f.symbol == symbol and f.date <= day]
        return paid[-1] if paid else None

    benchmark_start = price(benchmark, base or dates[0])
    points = []
    if base is not None:
        start_value = starting_capital.quantize(MONEY_PLACES)
        points.append(ValuePoint(base, start_value, start_value if benchmark_start else None))
    for day in dates:
        cash = sum((a for d, a in cash_flows if d <= day), Decimal("0"))
        held: dict[str, Decimal] = {}
        for f in fills:
            if f.date <= day:
                held[f.symbol] = held.get(f.symbol, Decimal("0")) + f.quantity
        value = cash + sum(
            (q * (price(s, day) or Decimal("0")) for s, q in held.items() if q),
            Decimal("0"),
        )
        benchmark_price = price(benchmark, day)
        benchmark_value = (
            starting_capital * benchmark_price / benchmark_start
            if benchmark_start and benchmark_price
            else None
        )
        points.append(
            ValuePoint(
                date=day,
                value=value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP),
                benchmark_value=benchmark_value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
                if benchmark_value is not None
                else None,
            )
        )
    return points


class PerformanceService:
    def __init__(self, session: Session, market: MarketDataService, benchmark: str = "SPY"):
        self.session = session
        self.market = market
        self.benchmark = benchmark
        self.portfolios = PortfolioService(session)

    def value_history(self, portfolio_id: uuid.UUID) -> ValueHistory:
        portfolio = self.portfolios.get_portfolio(portfolio_id)
        cash_flows = [
            (eastern_date(created_at), amount)
            for created_at, amount in self.session.execute(
                select(CashLedgerEntry.created_at, CashLedgerEntry.amount).where(
                    CashLedgerEntry.portfolio_id == portfolio_id
                )
            )
        ]
        fills = [
            Fill(
                date=eastern_date(e.executed_at),
                symbol=e.symbol,
                quantity=e.quantity if e.side is OrderSide.BUY else -e.quantity,
                price=e.price,
            )
            for e in self.session.scalars(
                select(Execution)
                .where(Execution.portfolio_id == portfolio_id)
                .order_by(Execution.executed_at)
            )
        ]

        # A few days of lead-in, so there's a close on or before the start date.
        start, end = portfolio.created_at - timedelta(days=10), self.market.now()
        closes: dict[str, dict[date, Decimal]] = {}
        stale = False
        for symbol in dict.fromkeys([self.benchmark, *(f.symbol for f in fills)]):
            try:
                series = self.market.get_bars(
                    symbol, Timeframe.DAY_1, start, end, max_age=BAR_MAX_AGE
                )
            except MarketDataUnavailableError:
                stale = True
                continue
            stale = stale or series.stale
            closes[symbol] = {eastern_date(b.timestamp): b.close for b in series.bars}

        held = {p.symbol for p in self.portfolios.get_positions(portfolio_id)}
        # Before the first trade, only the starting point (the latest close) is shown.
        started = fills[0].date if fills else eastern_date(end) + timedelta(days=1)
        points = build_history(
            portfolio.starting_capital,
            started,
            cash_flows,
            fills,
            closes,
            self.benchmark,
            live=self._live([self.benchmark, *sorted(held)]),
        )
        return ValueHistory(portfolio_id, self.benchmark, points, stale)

    def _live(self, symbols: list[str]) -> tuple[date, dict[str, Decimal]] | None:
        try:
            latest = self.market.get_latest_prices(symbols)
        except MarketDataUnavailableError:
            return None
        if not latest.prices:
            return None
        # Date the live point by the benchmark's last trade, so on a weekend it
        # updates Friday instead of adding a Saturday.
        anchor = next((p for p in latest.prices if p.symbol == self.benchmark), latest.prices[0])
        return eastern_date(anchor.price_time), {p.symbol: p.price for p in latest.prices}
