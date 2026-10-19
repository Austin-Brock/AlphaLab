import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    CashBalanceOut,
    LedgerEntryOut,
    PortfolioCreate,
    PortfolioOut,
    PortfolioSummary,
    PortfolioValueOut,
    PositionOut,
)
from app.services.portfolio import PortfolioService

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def get_portfolio_service(session: Annotated[Session, Depends(get_session)]) -> PortfolioService:
    return PortfolioService(session)


Service = Annotated[PortfolioService, Depends(get_portfolio_service)]


@router.post("", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def create_portfolio(body: PortfolioCreate, service: Service):
    return service.create_portfolio(body.name, body.starting_capital, body.strategy_id)


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(service: Service):
    return service.list_portfolios()


@router.get("/{portfolio_id}", response_model=PortfolioSummary)
def get_portfolio(portfolio_id: uuid.UUID, service: Service):
    portfolio = service.get_portfolio(portfolio_id)
    valuation = service.calculate_portfolio_value(portfolio_id)
    return PortfolioSummary(
        **PortfolioOut.model_validate(portfolio).model_dump(),
        cash=valuation.cash,
        positions_value=valuation.positions_value,
        total_value=valuation.total_value,
    )


@router.get("/{portfolio_id}/positions", response_model=list[PositionOut])
def get_positions(portfolio_id: uuid.UUID, service: Service):
    return service.get_positions(portfolio_id)


@router.get("/{portfolio_id}/cash", response_model=CashBalanceOut)
def get_cash(portfolio_id: uuid.UUID, service: Service):
    return CashBalanceOut(portfolio_id=portfolio_id, cash=service.get_cash_balance(portfolio_id))


@router.get("/{portfolio_id}/ledger", response_model=list[LedgerEntryOut])
def get_ledger(portfolio_id: uuid.UUID, service: Service):
    return service.get_ledger(portfolio_id)


@router.get("/{portfolio_id}/value", response_model=PortfolioValueOut)
def get_value(portfolio_id: uuid.UUID, service: Service):
    return service.calculate_portfolio_value(portfolio_id)
