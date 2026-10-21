"""Runs a portfolio's strategy and routes its proposals through the trading engine.

Engineering rule: no AI-controlled execution. The strategy only returns
proposals; each becomes an ordinary order that the risk engine fills or rejects.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import LLMUnavailableError
from app.market_data.provider import MarketDataUnavailableError, Timeframe
from app.models import (
    AgentDecision,
    AgentRun,
    AgentRunStatus,
    Execution,
    Order,
    OrderSide,
    OrderStatus,
    PortfolioStatus,
)
from app.services.market_data import MarketDataService
from app.services.performance import PerformanceService, eastern_date
from app.services.portfolio import PortfolioService
from app.strategies.base import (
    HoldingSnapshot,
    PortfolioSnapshot,
    StrategyContext,
    StrategyError,
    StrategyResult,
    TradingStrategy,
)
from app.trading.service import TradingService

WEIGHT_PLACES = Decimal("0.0001")
# Market overview: about three months of daily closes, summarized per symbol.
OVERVIEW_DAYS = 100
OVERVIEW_WINDOWS = [("5d", 5), ("1m", 21), ("3m", 63)]
# Closes change once a day; reuse bars fetched in the last hour.
OVERVIEW_MAX_AGE = timedelta(hours=1)
# Memory: how many earlier runs a strategy is shown, and how much of each text.
MEMORY_RUNS = 5
MEMORY_TEXT_CHARS = 600


def _clip(text: str | None, limit: int = MEMORY_TEXT_CHARS) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _outcome(order: Order | None) -> str:
    if order is None:
        return "not submitted"
    if order.status is OrderStatus.FILLED and order.execution:
        return f"filled at {order.execution.price:.2f}"
    if order.status is OrderStatus.REJECTED:
        return f"rejected: {order.rejection_reason}"
    return order.status.value.lower()


def _change(closes: list[Decimal], sessions: int) -> float | None:
    """Percent change over the last `sessions` trading days, if there's enough history."""
    if len(closes) <= sessions:
        return None
    then = closes[-1 - sessions]
    return round(float((closes[-1] - then) / then * 100), 2)


class UnknownStrategyError(Exception):
    def __init__(self, strategy_id: str):
        super().__init__(f"No strategy registered for '{strategy_id}'")
        self.strategy_id = strategy_id


class MarketResearchTools:
    """Read-only market data for strategies, limited to the watchlist."""

    def __init__(self, session: Session, market: MarketDataService, watchlist: Sequence[str]):
        self.session = session
        self.market = market
        self.watchlist = set(watchlist)
        self.watchlist_order = list(watchlist)

    def latest_prices(self, symbols: Sequence[str]) -> dict[str, Any]:
        self._check(symbols)
        try:
            result = self.market.get_latest_prices(symbols)
        finally:
            self._end_read()
        return {
            "prices": {
                p.symbol: {
                    "price": float(p.price),
                    "price_time": p.price_time.isoformat(),
                    "stale": p.stale,
                }
                for p in result.prices
            },
            "missing": result.missing,
        }

    def price_history(self, symbol: str, days: int) -> dict[str, Any]:
        self._check([symbol])
        end = self.market.now()
        try:
            series = self.market.get_bars(symbol, Timeframe.DAY_1, end - timedelta(days=days), end)
        finally:
            self._end_read()
        bars = series.bars
        if not bars:
            return {"symbol": symbol, "days": days, "bars": []}
        first, last = bars[0].close, bars[-1].close
        return {
            "symbol": symbol,
            "days": days,
            "trading_days": len(bars),
            "first_close": float(first),
            "last_close": float(last),
            "change_pct": round(float((last - first) / first * 100), 2),
            "high": float(max(b.high for b in bars)),
            "low": float(min(b.low for b in bars)),
            "avg_volume": round(sum(b.volume for b in bars) / len(bars)),
            "closes": [
                {"date": b.timestamp.date().isoformat(), "close": float(b.close)} for b in bars
            ],
            "stale": series.stale,
        }

    def market_overview(self) -> dict[str, Any]:
        """Recent performance of every watchlist symbol in one call, for screening.

        Lets the model pick a few symbols to research in depth instead of pulling
        the full history of each one, which keeps runs small as the watchlist grows.
        """
        end = self.market.now()
        start = end - timedelta(days=OVERVIEW_DAYS)
        rows, missing = {}, []
        try:
            for symbol in self.watchlist_order:
                try:
                    bars = self.market.get_bars(
                        symbol, Timeframe.DAY_1, start, end, max_age=OVERVIEW_MAX_AGE
                    ).bars
                except MarketDataUnavailableError:
                    bars = []
                if not bars:
                    missing.append(symbol)
                    continue
                closes = [b.close for b in bars]
                rows[symbol] = {
                    "last_close": float(closes[-1]),
                    **{
                        f"change_{label}_pct": _change(closes, sessions)
                        for label, sessions in OVERVIEW_WINDOWS
                    },
                }
        finally:
            self._end_read()
        return {"symbols": rows, "missing": missing}

    def _check(self, symbols: Sequence[str]) -> None:
        outside = [s for s in symbols if s not in self.watchlist]
        if outside:
            raise ValueError(f"Not in the watchlist: {outside}")

    def _end_read(self) -> None:
        # Don't hold a database transaction open while the model is thinking.
        self.session.commit()


class AgentRunService:
    def __init__(
        self,
        session: Session,
        market: MarketDataService,
        trading: TradingService,
        strategy_for: Callable[[str], TradingStrategy | None],
        watchlist: Sequence[str],
        max_proposals: int = 5,
        require_market_open: bool = True,
        benchmark: str = "SPY",
    ):
        self.session = session
        self.market = market
        self.trading = trading
        self.strategy_for = strategy_for
        self.watchlist = list(watchlist)
        self.max_proposals = max_proposals
        self.require_market_open = require_market_open
        self.benchmark = benchmark
        self.portfolios = PortfolioService(session)

    def run(self, portfolio_id: uuid.UUID, run_key: str | None = None) -> AgentRun:
        portfolio = self.portfolios.get_portfolio(portfolio_id)
        if run_key and (existing := self._find_run(portfolio_id, run_key)):
            return existing
        strategy = self.strategy_for(portfolio.strategy_id)
        if strategy is None:
            raise UnknownStrategyError(portfolio.strategy_id)

        snapshot = self._snapshot(portfolio_id)
        run = AgentRun(
            portfolio_id=portfolio_id,
            strategy_id=portfolio.strategy_id,
            run_key=run_key,
            status=AgentRunStatus.RUNNING,
            input_snapshot=snapshot.to_dict(),
        )
        self.session.add(run)
        self.session.commit()

        if portfolio.status is not PortfolioStatus.ACTIVE:
            # Paused or closed: the risk engine would reject every order anyway.
            return self._finish(
                run,
                AgentRunStatus.SKIPPED,
                summary=f"Portfolio is {portfolio.status.value.lower()}",
            )
        if self.require_market_open and snapshot.market_open is not True:
            # Don't pay for a model run whose orders would all be rejected.
            reason = (
                "Market is closed"
                if snapshot.market_open is False
                else ("Could not confirm the market is open")
            )
            return self._finish(run, AgentRunStatus.SKIPPED, summary=reason)

        memory = self._memory(portfolio_id, run.id, snapshot)
        # Stored with the snapshot, so the run still shows everything the strategy knew.
        run.input_snapshot = {**run.input_snapshot, "memory": memory}
        self.session.commit()
        context = StrategyContext(
            snapshot=snapshot,
            watchlist=self.watchlist,
            max_proposals=self.max_proposals,
            research=MarketResearchTools(self.session, self.market, self.watchlist),
            memory=memory,
        )
        try:
            result = strategy.generate_proposals(context)
        except StrategyError as exc:
            self._record_result(run, exc.partial)
            return self._finish(run, AgentRunStatus.FAILED, error=str(exc))
        except LLMUnavailableError as exc:
            return self._finish(run, AgentRunStatus.FAILED, error=str(exc))

        self._record_result(run, result)
        self.session.commit()
        try:
            self._submit(run, portfolio_id, result)
        except Exception as exc:
            self.session.rollback()
            self._finish(run, AgentRunStatus.FAILED, error=f"Order submission failed: {exc}")
            raise
        return self._finish(run, AgentRunStatus.COMPLETED, summary=result.summary)

    def list_runs(self, portfolio_id: uuid.UUID) -> list[AgentRun]:
        self.portfolios.get_portfolio(portfolio_id)
        return list(
            self.session.scalars(
                select(AgentRun)
                .where(AgentRun.portfolio_id == portfolio_id)
                .order_by(AgentRun.started_at.desc())
            )
        )

    def get_run(self, portfolio_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun | None:
        self.portfolios.get_portfolio(portfolio_id)
        return self.session.scalar(
            select(AgentRun).where(AgentRun.portfolio_id == portfolio_id, AgentRun.id == run_id)
        )

    def _submit(self, run: AgentRun, portfolio_id: uuid.UUID, result: StrategyResult) -> None:
        # Sells first, so the cash they free up is available to the buys.
        ordered = sorted(result.proposals, key=lambda p: p.side is not OrderSide.SELL)
        for sequence, proposal in enumerate(ordered):
            decision = AgentDecision(
                run_id=run.id,
                portfolio_id=portfolio_id,
                sequence=sequence,
                symbol=proposal.symbol,
                side=proposal.side,
                quantity=proposal.quantity,
                rationale=proposal.rationale,
            )
            self.session.add(decision)
            self.session.commit()
            submitted = self.trading.submit_order(
                portfolio_id,
                proposal.symbol,
                proposal.side,
                proposal.quantity,
                # Deterministic, so re-submitting a run's proposal can never trade twice.
                client_order_id=f"agent-run:{run.id}:{sequence}",
                source=run.strategy_id,
            )
            decision.order_id = submitted.order.id
            self.session.commit()

    def _snapshot(self, portfolio_id: uuid.UUID) -> PortfolioSnapshot:
        portfolio = self.portfolios.get_portfolio(portfolio_id)
        positions = self.portfolios.get_positions(portfolio_id)
        symbols = list(dict.fromkeys([*self.watchlist, *(p.symbol for p in positions)]))
        try:
            prices = {p.symbol: p.price for p in self.market.get_latest_prices(symbols).prices}
        except MarketDataUnavailableError:
            prices = {}
        try:
            market_open: bool | None = self.market.get_market_clock().is_open
        except MarketDataUnavailableError:
            market_open = None

        valuation = self.portfolios.calculate_portfolio_value(portfolio_id, prices)
        total = valuation.total_value
        holdings = [
            HoldingSnapshot(
                symbol=v.symbol,
                quantity=v.quantity,
                average_cost=v.average_cost,
                price=v.price,
                market_value=v.market_value,
                weight=(v.market_value / total).quantize(WEIGHT_PLACES, rounding=ROUND_HALF_UP)
                if total > 0
                else Decimal("0"),
            )
            for v in valuation.positions
        ]
        return PortfolioSnapshot(
            portfolio_id=portfolio_id,
            as_of=self.market.now(),
            cash=valuation.cash,
            total_value=total,
            holdings=holdings,
            max_position_pct=portfolio.max_position_pct.quantize(WEIGHT_PLACES),
            min_cash_pct=portfolio.min_cash_pct.quantize(WEIGHT_PLACES),
            market_open=market_open,
            prices={s: prices[s] for s in self.watchlist if s in prices},
        )

    def _memory(
        self, portfolio_id: uuid.UUID, current_run_id: uuid.UUID, snapshot: PortfolioSnapshot
    ) -> dict[str, Any]:
        """What the strategy should know from earlier runs: recent decisions and how
        they turned out, why it holds what it holds, how it's doing against the
        benchmark, and the notes the last run left. Empty parts are left out."""
        runs = list(
            self.session.scalars(
                select(AgentRun)
                .where(
                    AgentRun.portfolio_id == portfolio_id,
                    AgentRun.id != current_run_id,
                    AgentRun.status == AgentRunStatus.COMPLETED,
                )
                .order_by(AgentRun.started_at.desc())
                .limit(MEMORY_RUNS)
            )
        )
        recent_runs = [
            {
                "date": eastern_date(r.started_at).isoformat(),
                "summary": _clip(r.summary),
                "trades": [
                    {
                        "symbol": d.symbol,
                        "side": d.side.value,
                        "quantity": float(d.quantity),
                        "result": _outcome(d.order),
                    }
                    for d in r.decisions
                ],
            }
            for r in runs
        ]
        noted = next((r for r in runs if r.notes), None)
        memory: dict[str, Any] = {
            "notes_from_last_session": {
                "date": eastern_date(noted.started_at).isoformat(),
                "notes": noted.notes,
            }
            if noted
            else None,
            "recent_sessions": recent_runs,
            "holdings": self._holding_context(portfolio_id, snapshot),
            "performance": self._performance(portfolio_id),
        }
        return {k: v for k, v in memory.items() if v}

    def _holding_context(
        self, portfolio_id: uuid.UUID, snapshot: PortfolioSnapshot
    ) -> list[dict[str, Any]]:
        """When each current position was opened, its gain, and the last reason given to buy."""
        if not snapshot.holdings:
            return []
        opened: dict[str, datetime] = {}
        held: dict[str, Decimal] = {}
        for e in self.session.scalars(
            select(Execution)
            .where(Execution.portfolio_id == portfolio_id)
            .order_by(Execution.executed_at)
        ):
            before = held.get(e.symbol, Decimal("0"))
            held[e.symbol] = before + (e.quantity if e.side is OrderSide.BUY else -e.quantity)
            if before <= 0 < held[e.symbol]:
                opened[e.symbol] = e.executed_at

        reasons: dict[str, AgentDecision] = {}
        for d in self.session.scalars(
            select(AgentDecision)
            .join(Order, AgentDecision.order_id == Order.id)
            .where(
                AgentDecision.portfolio_id == portfolio_id,
                AgentDecision.side == OrderSide.BUY,
                Order.status == OrderStatus.FILLED,
            )
            .order_by(Order.created_at.desc())
        ):
            reasons.setdefault(d.symbol, d)

        today = eastern_date(snapshot.as_of)
        rows = []
        for h in snapshot.holdings:
            row: dict[str, Any] = {
                "symbol": h.symbol,
                "gain_pct": round(float((h.price / h.average_cost - 1) * 100), 2)
                if h.average_cost
                else None,
            }
            if h.symbol in opened:
                since = eastern_date(opened[h.symbol])
                row |= {"held_since": since.isoformat(), "days_held": (today - since).days}
            if decision := reasons.get(h.symbol):
                row |= {
                    "last_buy_date": eastern_date(decision.order.created_at).isoformat(),
                    "last_buy_reason": _clip(decision.rationale),
                }
            rows.append(row)
        return rows

    def _performance(self, portfolio_id: uuid.UUID) -> dict[str, Any] | None:
        """Return since the first trade, next to the benchmark over the same days."""
        points = (
            PerformanceService(self.session, self.market, self.benchmark)
            .value_history(portfolio_id)
            .points
        )
        if len(points) < 2:
            return None
        first, last = points[0], points[-1]
        result: dict[str, Any] = {
            "since": first.date.isoformat(),
            "return_pct": round(float((last.value / first.value - 1) * 100), 2),
        }
        if first.benchmark_value and last.benchmark_value:
            result[f"{self.benchmark}_return_pct"] = round(
                float((last.benchmark_value / first.benchmark_value - 1) * 100), 2
            )
        return result

    def _record_result(self, run: AgentRun, result: StrategyResult | None) -> None:
        if result is None:
            return
        run.model_id = result.model_id
        run.prompt_version = result.prompt_version
        run.transcript = result.transcript
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.notes = result.notes

    def _finish(
        self,
        run: AgentRun,
        status: AgentRunStatus,
        summary: str | None = None,
        error: str | None = None,
    ) -> AgentRun:
        run.status = status
        run.summary = summary
        run.error = error
        run.finished_at = datetime.now(UTC)
        self.session.commit()
        return run

    def _find_run(self, portfolio_id: uuid.UUID, run_key: str) -> AgentRun | None:
        return self.session.scalar(
            select(AgentRun).where(
                AgentRun.portfolio_id == portfolio_id, AgentRun.run_key == run_key
            )
        )
