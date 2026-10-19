"""Concurrent orders against one portfolio, using real commits on separate connections.

Rows written here are not rolled back (the ledger is append-only); the test
database is rebuilt from migrations at the start of every test run. A symbol
no other test uses keeps the committed price cache from leaking into them.
"""

import threading
from decimal import Decimal

from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.models import LatestPrice, OrderSide, OrderStatus
from app.services.market_data import MarketDataService
from app.services.portfolio import PortfolioService
from app.trading.service import ExecutionSettings, TradingService
from tests.fakes import FakeMarketDataProvider

SYMBOL = "CNCY"


def test_concurrent_buys_cannot_overspend(engine: Engine):
    provider = FakeMarketDataProvider({SYMBOL: Decimal("100")})
    with Session(engine, expire_on_commit=False) as session:
        # $100K with limits relaxed so only the cash check matters.
        portfolio_id = (
            PortfolioService(session)
            .create_portfolio(
                "Concurrency",
                Decimal("100000"),
                "manual",
                max_position_pct=Decimal("1"),
                min_cash_pct=Decimal("0"),
            )
            .id
        )

    barrier = threading.Barrier(2)
    statuses: list[OrderStatus] = []
    errors: list[BaseException] = []

    def buy_600_shares() -> None:  # ~$60K each; only one can fit in $100K
        try:
            with Session(engine, expire_on_commit=False) as session:
                trading = TradingService(
                    session, MarketDataService(session, provider), ExecutionSettings()
                )
                barrier.wait()
                order = trading.submit_order(portfolio_id, SYMBOL, OrderSide.BUY, Decimal(600))
                statuses.append(order.order.status)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=buy_600_shares) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert sorted(statuses) == [OrderStatus.FILLED, OrderStatus.REJECTED]
    with Session(engine) as session:
        assert PortfolioService(session).get_cash_balance(portfolio_id) == Decimal("39970.00")
        session.execute(delete(LatestPrice).where(LatestPrice.symbol == SYMBOL))
        session.commit()
