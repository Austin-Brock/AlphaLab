"""Run the AI for every portfolio that has auto-trade switched on.

Run by the GitHub Actions workflow on trading-day mornings, or by hand:

    uv run python -m app.daily_run                    # scheduled mode
    uv run python -m app.daily_run --manual           # now, regardless of the time
    uv run python -m app.daily_run --manual --portfolio <id>
    uv run python -m app.daily_run --check            # test connections, trade nothing

Scheduled runs wait until `daily_run_after` (US Eastern) and use the run key
`daily:<date>`, so however often the job fires, each portfolio runs at most once
per day. A scheduled run also skips a portfolio that already completed a manual
run that day. Market hours and pause/resume are still enforced by the agent runner.
Exits non-zero if any run failed, so the failure shows up in GitHub.
"""

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.service import AgentRunService
from app.api import deps
from app.config import get_settings
from app.db import get_sessionmaker
from app.llm.client import LLMUnavailableError
from app.models import AgentRun, AgentRunStatus
from app.services.portfolio import PortfolioService

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DailyRunResult:
    runs: list[AgentRun]
    # Portfolios whose run raised instead of recording a result.
    errors: list[str] = field(default_factory=list)
    # Set when the run was skipped before looking at any portfolio.
    not_yet: str | None = None
    # Portfolios skipped because they already completed a run today.
    already_ran: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.errors) or any(r.status is AgentRunStatus.FAILED for r in self.runs)


def run_daily(
    session: Session,
    agent: AgentRunService,
    now: datetime,
    run_after: time,
    manual: bool = False,
    portfolio_id: uuid.UUID | None = None,
    manual_key: str | None = None,
) -> DailyRunResult:
    local = now.astimezone(EASTERN)
    if not manual and local.time() < run_after:
        return DailyRunResult([], not_yet=f"Too early: {local:%H:%M} ET, runs after {run_after}")

    portfolios = PortfolioService(session)
    targets = (
        [portfolios.get_portfolio(portfolio_id)]
        if portfolio_id
        else portfolios.list_auto_trade_portfolios()
    )
    run_key = f"manual:{manual_key or uuid.uuid4()}" if manual else f"daily:{local.date()}"
    result = DailyRunResult([])
    for portfolio in targets:
        if not manual and (earlier := _completed_today(session, portfolio.id, local, run_key)):
            result.already_ran.append(f"{portfolio.id}: already ran today ({earlier.run_key})")
            continue
        # One portfolio's failure shouldn't stop the others.
        try:
            result.runs.append(agent.run(portfolio.id, run_key=run_key))
        except Exception as exc:
            session.rollback()
            result.errors.append(f"{portfolio.id}: {exc}")
    return result


def _completed_today(
    session: Session, portfolio_id: uuid.UUID, local: datetime, run_key: str
) -> AgentRun | None:
    """Another completed run on this portfolio today (US Eastern), e.g. one started by hand."""
    start = datetime.combine(local.date(), time(0), EASTERN)
    return session.scalar(
        select(AgentRun).where(
            AgentRun.portfolio_id == portfolio_id,
            AgentRun.status == AgentRunStatus.COMPLETED,
            AgentRun.run_key != run_key,
            AgentRun.started_at >= start,
            AgentRun.started_at < start + timedelta(days=1),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manual", action="store_true", help="run now, ignoring the time")
    parser.add_argument("--portfolio", type=uuid.UUID, help="run only this portfolio")
    parser.add_argument(
        "--check", action="store_true", help="check database, market data and AWS; trade nothing"
    )
    args = parser.parse_args(argv)
    if args.portfolio and not args.manual:
        parser.error("--portfolio requires --manual")
    if args.check:
        return check()

    settings = get_settings()
    with get_sessionmaker()() as session:
        market = deps.get_market_data_service(session, deps.get_market_data_provider())
        execution = deps.get_execution_settings()
        agent = deps.get_agent_service(
            session,
            market,
            deps.get_trading_service(session, market, execution),
            deps.get_strategy_resolver(),
            execution,
        )
        result = run_daily(
            session,
            agent,
            now=datetime.now(EASTERN),
            run_after=time.fromisoformat(settings.daily_run_after),
            manual=args.manual,
            portfolio_id=args.portfolio,
            # GitHub's run ID, so re-running the same job doesn't trade twice.
            manual_key=os.environ.get("GITHUB_RUN_ID"),
        )

    if result.not_yet:
        print(result.not_yet)
    elif not result.runs and not result.already_ran:
        print("No portfolios have auto-trade switched on.")
    for skipped in result.already_ran:
        print(f"SKIPPED {skipped}")
    for error in result.errors:
        print(f"ERROR {error}")
    for run in result.runs:
        filled = sum(1 for d in run.decisions if d.order and d.order.status.value == "FILLED")
        print(
            f"{run.portfolio_id} {run.status.value}: "
            f"{len(run.decisions)} proposals, {filled} filled. {run.summary or run.error or ''}"
        )
    return 1 if result.failed else 0


def check() -> int:
    """Verify every connection the daily run needs, without calling the model or trading."""
    with get_sessionmaker()() as session:
        auto = PortfolioService(session).list_auto_trade_portfolios()
        print(f"Database: OK ({len(auto)} portfolio(s) with auto-trade on)")
        market = deps.get_market_data_service(session, deps.get_market_data_provider())
        print(
            f"Market data: OK (market {'open' if market.get_market_clock().is_open else 'closed'})"
        )
    # Verifies the AWS identity is the restricted AlphaLab role; makes no model call.
    try:
        deps.get_llm_client()
    except LLMUnavailableError as exc:
        print(f"AWS: FAILED. {exc}")
        return 1
    print("AWS: OK (restricted AlphaLab role)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
