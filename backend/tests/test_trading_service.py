from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CashLedgerEntry,
    LedgerEntryType,
    OrderSide,
    OrderStatus,
    PortfolioStatus,
    Position,
)
from app.services.market_data import MarketDataService
from app.services.portfolio import PortfolioService
from app.trading.service import ExecutionSettings, TradingService, replay_positions
from tests.fakes import Clock, FakeMarketDataProvider

MILLION = Decimal("1000000")
BUY, SELL = OrderSide.BUY, OrderSide.SELL


@pytest.fixture
def provider() -> FakeMarketDataProvider:
    return FakeMarketDataProvider(
        {"AAPL": Decimal("100"), "NVDA": Decimal("217.09"), "MSFT": Decimal("400")}
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def market(session: Session, provider, clock) -> MarketDataService:
    return MarketDataService(session, provider, now=clock)


@pytest.fixture
def trading(session: Session, market) -> TradingService:
    return TradingService(session, market, ExecutionSettings())


@pytest.fixture
def portfolios(session: Session) -> PortfolioService:
    return PortfolioService(session)


@pytest.fixture
def portfolio(portfolios):
    return portfolios.create_portfolio("Test", MILLION, "manual")


def test_milestone_3_definition_of_done(trading, portfolios, portfolio):
    """Buy 100 shares, then verify the resulting cash balance and position quantity."""
    order = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100)).order

    assert order.status is OrderStatus.FILLED
    assert [c.passed for c in order.risk_checks] == [True] * 7
    # $100 market price + 0.05% slippage = $100.05/share.
    assert order.execution.price == Decimal("100.05")
    assert order.execution.market_price == Decimal("100")
    assert order.execution.gross_amount == Decimal("10005.00")

    assert portfolios.get_cash_balance(portfolio.id) == Decimal("989995.00")
    [position] = portfolios.get_positions(portfolio.id)
    assert (position.symbol, position.quantity) == ("AAPL", Decimal(100))
    assert position.average_cost == Decimal("100.05")


def test_buy_writes_a_linked_ledger_entry(trading, portfolios, portfolio):
    order = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100)).order
    entry = portfolios.get_ledger(portfolio.id)[-1]
    assert entry.entry_type is LedgerEntryType.BUY
    assert entry.amount == Decimal("-10005.00")
    assert entry.reference_id == str(order.execution.id)
    assert entry.description == "BUY 100 AAPL @ $100.0500"


def test_sell_adds_cash_and_keeps_cost_basis(trading, portfolios, portfolio, provider, clock):
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100))
    clock.advance(seconds=61)
    provider.prices["AAPL"] = Decimal("110")

    order = trading.submit_order(portfolio.id, "AAPL", SELL, Decimal(40)).order

    assert order.status is OrderStatus.FILLED
    assert order.execution.price == Decimal("109.945")  # 110 - 0.05%
    assert portfolios.get_cash_balance(portfolio.id) == Decimal("989995.00") + Decimal("4397.80")
    [position] = portfolios.get_positions(portfolio.id)
    assert position.quantity == Decimal(60)
    assert position.average_cost == Decimal("100.05")


def test_selling_everything_closes_the_position(trading, portfolios, portfolio):
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(10))
    trading.submit_order(portfolio.id, "AAPL", SELL, Decimal(10))
    assert portfolios.get_positions(portfolio.id) == []


def test_rejected_order_is_recorded_without_moving_money(trading, portfolios, portfolio):
    result = trading.submit_order(portfolio.id, "NVDA", BUY, Decimal(500))

    order = result.order
    assert result.created
    assert order.status is OrderStatus.REJECTED
    assert order.rejection_reason == "NVDA would be 10.9% of portfolio (limit 10.0%)"
    assert order.execution is None
    assert len(order.risk_checks) == 7
    assert portfolios.get_cash_balance(portfolio.id) == MILLION
    assert portfolios.get_positions(portfolio.id) == []
    assert trading.list_orders(portfolio.id) == [order]


def test_cannot_sell_shares_not_held(trading, portfolio):
    order = trading.submit_order(portfolio.id, "AAPL", SELL, Decimal(1)).order
    assert order.status is OrderStatus.REJECTED
    assert order.rejection_reason == "Cannot sell 1 AAPL: only 0 held"


def test_market_closed_rejects_unless_hours_not_enforced(session, market, portfolio, provider):
    provider.market_open = False
    enforced = TradingService(session, market, ExecutionSettings())
    assert enforced.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order.rejection_reason == (
        "Market is closed"
    )

    relaxed = TradingService(session, market, ExecutionSettings(enforce_market_hours=False))
    assert relaxed.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order.status is (
        OrderStatus.FILLED
    )


def test_paused_portfolio_cannot_trade(session, trading, portfolio):
    portfolio.status = PortfolioStatus.PAUSED
    session.commit()
    order = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order
    assert order.rejection_reason == "Portfolio is PAUSED"


def test_unknown_symbol_is_rejected(trading, portfolio):
    order = trading.submit_order(portfolio.id, "ZZZZ", BUY, Decimal(1)).order
    assert order.status is OrderStatus.REJECTED
    assert order.rejection_reason.startswith("No market price for ZZZZ")


def test_outage_rejects_rather_than_trading_on_unknown_prices(trading, portfolio, provider):
    provider.fail = True
    order = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order
    assert order.status is OrderStatus.REJECTED
    assert "Market data unavailable" in order.rejection_reason
    assert "Could not confirm the market is open" in order.rejection_reason


def test_stale_cached_price_is_rejected(trading, market, portfolio, provider, clock):
    market.get_latest_prices(["AAPL"])
    clock.advance(minutes=10)
    provider.fail = True
    provider.market_open = True
    relaxed = TradingService(trading.session, market, ExecutionSettings(enforce_market_hours=False))
    order = relaxed.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order
    assert order.status is OrderStatus.REJECTED
    assert order.rejection_reason.startswith("AAPL price is stale")


def test_resubmitting_same_client_order_id_trades_once(trading, portfolios, portfolio):
    first = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100), client_order_id="abc")
    second = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100), client_order_id="abc")

    assert first.created and not second.created
    assert second.order.id == first.order.id
    assert len(trading.list_executions(portfolio.id)) == 1
    assert portfolios.get_cash_balance(portfolio.id) == Decimal("989995.00")


def test_commission_is_charged_as_a_fee(session, market, portfolios, portfolio):
    trading = TradingService(session, market, ExecutionSettings(commission_per_order=Decimal("1")))
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(100))
    fees = [e for e in portfolios.get_ledger(portfolio.id) if e.entry_type is LedgerEntryType.FEE]
    assert [f.amount for f in fees] == [Decimal("-1")]
    assert portfolios.get_cash_balance(portfolio.id) == Decimal("989994.00")


def test_positions_always_match_a_replay_of_executions(
    session, trading, portfolios, portfolio, provider, clock
):
    trades = [
        ("AAPL", BUY, 100, "100"),
        ("MSFT", BUY, 50, "400"),
        ("AAPL", BUY, 50, "120"),
        ("AAPL", SELL, 30, "130"),
        ("MSFT", SELL, 50, "390"),
    ]
    for symbol, side, qty, price in trades:
        provider.prices[symbol] = Decimal(price)
        clock.advance(seconds=61)
        order = trading.submit_order(portfolio.id, symbol, side, Decimal(qty)).order
        assert order.status is OrderStatus.FILLED, order.rejection_reason

    replayed = replay_positions(trading.list_executions(portfolio.id))
    stored = {
        p.symbol: (p.quantity, p.average_cost) for p in portfolios.get_positions(portfolio.id)
    }
    assert stored == replayed
    assert set(stored) == {"AAPL"}

    # Cash also reconciles: starting capital plus every fill's signed amount.
    fills = sum(
        (-e.gross_amount if e.side is BUY else e.gross_amount)
        for e in trading.list_executions(portfolio.id)
    )
    assert portfolios.get_cash_balance(portfolio.id) == MILLION + fills


def test_valuation_uses_held_positions_market_prices(trading, portfolio, provider, clock):
    # 900 AAPL at $100 is 9%; after AAPL doubles, it's ~16.5%, so buying more is rejected.
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(900))
    provider.prices["AAPL"] = Decimal("200")
    clock.advance(seconds=61)
    order = trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(1)).order
    assert order.status is OrderStatus.REJECTED
    assert "AAPL would be 16.5% of portfolio" in order.rejection_reason


def test_one_ledger_entry_per_fill(session, trading, portfolio):
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(10))
    trading.submit_order(portfolio.id, "AAPL", BUY, Decimal(10))
    rows = session.scalars(
        select(CashLedgerEntry).where(
            CashLedgerEntry.portfolio_id == portfolio.id,
            CashLedgerEntry.entry_type == LedgerEntryType.BUY,
        )
    ).all()
    assert len(rows) == 2
    assert len({r.reference_id for r in rows}) == 2


def test_position_quantity_never_negative_in_db(session, portfolio):
    session.add(
        Position(
            portfolio_id=portfolio.id, symbol="X", quantity=Decimal(-1), average_cost=Decimal(1)
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
