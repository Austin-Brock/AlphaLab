import uuid
from decimal import Decimal

from fastapi import APIRouter, status

from app.api.deps import MarketDataServiceDep, PortfolioServiceDep
from app.market_data.provider import MarketDataUnavailableError
from app.schemas import (
    CashBalanceOut,
    LedgerEntryOut,
    PortfolioCreate,
    PortfolioOut,
    PortfolioSummary,
    PortfolioValueOut,
    PositionOut,
)
from app.services.portfolio import PortfolioService, PortfolioValuation

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def value_portfolio(
    portfolio_id: uuid.UUID, service: PortfolioService, market: MarketDataServiceDep
) -> PortfolioValuation:
    """Value positions at latest market prices, falling back to cost if unavailable."""
    symbols = [p.symbol for p in service.get_positions(portfolio_id)]
    prices: dict[str, Decimal] = {}
    if symbols:
        try:
            prices = {p.symbol: p.price for p in market.get_latest_prices(symbols).prices}
        except MarketDataUnavailableError:
            pass
    return service.calculate_portfolio_value(portfolio_id, prices)


@router.post("", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def create_portfolio(body: PortfolioCreate, service: PortfolioServiceDep):
    return service.create_portfolio(
        body.name,
        body.starting_capital,
        body.strategy_id,
        max_position_pct=body.max_position_pct,
        min_cash_pct=body.min_cash_pct,
    )


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(service: PortfolioServiceDep):
    return service.list_portfolios()


@router.get("/{portfolio_id}", response_model=PortfolioSummary)
def get_portfolio(
    portfolio_id: uuid.UUID, service: PortfolioServiceDep, market: MarketDataServiceDep
):
    portfolio = service.get_portfolio(portfolio_id)
    valuation = value_portfolio(portfolio_id, service, market)
    return PortfolioSummary(
        **PortfolioOut.model_validate(portfolio).model_dump(),
        cash=valuation.cash,
        positions_value=valuation.positions_value,
        total_value=valuation.total_value,
    )


@router.get("/{portfolio_id}/positions", response_model=list[PositionOut])
def get_positions(portfolio_id: uuid.UUID, service: PortfolioServiceDep):
    return service.get_positions(portfolio_id)


@router.get("/{portfolio_id}/cash", response_model=CashBalanceOut)
def get_cash(portfolio_id: uuid.UUID, service: PortfolioServiceDep):
    return CashBalanceOut(portfolio_id=portfolio_id, cash=service.get_cash_balance(portfolio_id))


@router.get("/{portfolio_id}/ledger", response_model=list[LedgerEntryOut])
def get_ledger(portfolio_id: uuid.UUID, service: PortfolioServiceDep):
    return service.get_ledger(portfolio_id)


@router.get("/{portfolio_id}/value", response_model=PortfolioValueOut)
def get_value(portfolio_id: uuid.UUID, service: PortfolioServiceDep, market: MarketDataServiceDep):
    return value_portfolio(portfolio_id, service, market)
