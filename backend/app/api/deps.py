from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.market_data.alpaca import AlpacaMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.services.market_data import MarketDataService
from app.services.portfolio import PortfolioService


@lru_cache
def get_market_data_provider() -> MarketDataProvider | None:
    """The configured provider, or None when Alpaca keys aren't set."""
    settings = get_settings()
    if not (settings.alpaca_api_key and settings.alpaca_secret_key):
        return None
    return AlpacaMarketDataProvider(
        api_key=settings.alpaca_api_key.get_secret_value(),
        secret_key=settings.alpaca_secret_key.get_secret_value(),
        base_url=settings.alpaca_data_url,
        feed=settings.alpaca_feed,
    )


def get_portfolio_service(session: Annotated[Session, Depends(get_session)]) -> PortfolioService:
    return PortfolioService(session)


def get_market_data_service(
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[MarketDataProvider | None, Depends(get_market_data_provider)],
) -> MarketDataService:
    return MarketDataService(
        session, provider, cache_ttl=timedelta(seconds=get_settings().price_cache_ttl_seconds)
    )


PortfolioServiceDep = Annotated[PortfolioService, Depends(get_portfolio_service)]
MarketDataServiceDep = Annotated[MarketDataService, Depends(get_market_data_service)]
