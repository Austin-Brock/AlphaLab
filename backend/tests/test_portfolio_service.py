import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models import CashLedgerEntry, LedgerEntryType, PortfolioStatus, Position
from app.services.portfolio import PortfolioNotFoundError, PortfolioService

MILLION = Decimal("1000000.00")


@pytest.fixture
def service(session: Session) -> PortfolioService:
    return PortfolioService(session)


@pytest.fixture
def portfolio(service: PortfolioService):
    return service.create_portfolio("AlphaLab AI Portfolio", MILLION, "ai-trading-v1")


def test_new_portfolio_has_starting_capital_in_cash_and_no_positions(service, portfolio):
    assert portfolio.status is PortfolioStatus.ACTIVE
    assert portfolio.starting_capital == MILLION
    assert service.get_cash_balance(portfolio.id) == MILLION
    assert service.get_positions(portfolio.id) == []

    valuation = service.calculate_portfolio_value(portfolio.id)
    assert valuation.cash == MILLION
    assert valuation.positions_value == 0
    assert valuation.total_value == MILLION


def test_starting_capital_is_recorded_as_a_single_deposit(service, portfolio):
    [entry] = service.get_ledger(portfolio.id)
    assert entry.entry_type is LedgerEntryType.DEPOSIT
    assert entry.amount == MILLION


def test_cash_balance_is_the_sum_of_ledger_entries(session, service, portfolio):
    session.add(
        CashLedgerEntry(
            portfolio_id=portfolio.id,
            entry_type=LedgerEntryType.FEE,
            amount=Decimal("-12.3456"),
            description="test fee",
        )
    )
    session.flush()
    assert service.get_cash_balance(portfolio.id) == Decimal("999987.6544")


def test_portfolios_are_isolated(service, portfolio):
    other = service.create_portfolio("Other", Decimal("50000"), "buy-and-hold")
    assert service.get_cash_balance(portfolio.id) == MILLION
    assert service.get_cash_balance(other.id) == Decimal("50000")


def test_rejects_non_positive_starting_capital(service):
    with pytest.raises(ValueError):
        service.create_portfolio("Broke", Decimal("0"), "ai-trading-v1")


def test_unknown_portfolio_raises(service):
    missing = uuid.uuid4()
    with pytest.raises(PortfolioNotFoundError):
        service.get_cash_balance(missing)


@pytest.mark.parametrize(
    "statement",
    [
        lambda pid: (
            update(CashLedgerEntry)
            .where(CashLedgerEntry.portfolio_id == pid)
            .values(amount=Decimal("5000000"))
        ),
        lambda pid: delete(CashLedgerEntry).where(CashLedgerEntry.portfolio_id == pid),
    ],
    ids=["update", "delete"],
)
def test_ledger_is_append_only(session, portfolio, statement):
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(statement(portfolio.id))
    session.rollback()


def test_ledger_idempotency_key_prevents_double_posting(session, portfolio):
    session.add(
        CashLedgerEntry(
            portfolio_id=portfolio.id,
            entry_type=LedgerEntryType.DEPOSIT,
            amount=MILLION,
            description="duplicate",
            idempotency_key="starting-capital",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_valuation_uses_supplied_prices_and_falls_back_to_cost(session, service, portfolio):
    session.add_all(
        [
            Position(
                portfolio_id=portfolio.id,
                symbol="AAPL",
                quantity=Decimal("100"),
                average_cost=Decimal("200"),
            ),
            Position(
                portfolio_id=portfolio.id,
                symbol="MSFT",
                quantity=Decimal("10"),
                average_cost=Decimal("400"),
            ),
        ]
    )
    session.flush()

    valuation = service.calculate_portfolio_value(portfolio.id, prices={"AAPL": Decimal("210")})
    aapl, msft = valuation.positions
    assert (aapl.price, aapl.priced_at_cost) == (Decimal("210"), False)
    assert (msft.price, msft.priced_at_cost) == (Decimal("400"), True)
    assert valuation.positions_value == Decimal("25000")
    assert valuation.total_value == MILLION + Decimal("25000")
