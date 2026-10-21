from collections.abc import Callable
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agent.service import AgentRunService
from app.config import get_settings
from app.db import get_session
from app.llm.bedrock import BedrockLLMClient
from app.llm.client import LLMClient
from app.market_data.alpaca import AlpacaMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.services.market_data import MarketDataService
from app.services.performance import PerformanceService
from app.services.portfolio import PortfolioService
from app.strategies.ai import AITradingStrategy
from app.strategies.base import TradingStrategy
from app.trading.service import ExecutionSettings, TradingService


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
        trading_url=settings.alpaca_trading_url,
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


def get_performance_service(
    session: Annotated[Session, Depends(get_session)],
    market: Annotated[MarketDataService, Depends(get_market_data_service)],
) -> PerformanceService:
    return PerformanceService(session, market, benchmark=get_settings().benchmark_symbol)


def get_execution_settings() -> ExecutionSettings:
    settings = get_settings()
    return ExecutionSettings(
        slippage_bps=settings.slippage_bps,
        commission_per_order=settings.commission_per_order,
        max_price_age=timedelta(seconds=settings.max_price_age_seconds),
        enforce_market_hours=settings.enforce_market_hours,
    )


def get_trading_service(
    session: Annotated[Session, Depends(get_session)],
    market: Annotated[MarketDataService, Depends(get_market_data_service)],
    settings: Annotated[ExecutionSettings, Depends(get_execution_settings)],
) -> TradingService:
    return TradingService(session, market, settings)


@lru_cache
def get_llm_client() -> LLMClient:
    """Bedrock client; verifies it is running as the restricted AlphaLab role."""
    settings = get_settings()
    return BedrockLLMClient.from_profile(
        model_id=settings.bedrock_model_id,
        profile=settings.aws_profile,
        region=settings.aws_region,
        expected_role=settings.aws_expected_role,
    )


StrategyResolver = Callable[[str], TradingStrategy | None]


def get_strategy_resolver() -> StrategyResolver:
    """Maps a portfolio's strategy_id to a strategy. Built lazily: AWS is only touched on a run."""
    settings = get_settings()

    def strategy_for(strategy_id: str) -> TradingStrategy | None:
        if strategy_id == AITradingStrategy.strategy_id:
            return AITradingStrategy(
                get_llm_client(),
                max_turns=settings.agent_max_turns,
                max_tokens=settings.agent_max_tokens,
            )
        return None

    return strategy_for


def get_agent_service(
    session: Annotated[Session, Depends(get_session)],
    market: Annotated[MarketDataService, Depends(get_market_data_service)],
    trading: Annotated[TradingService, Depends(get_trading_service)],
    strategy_for: Annotated[StrategyResolver, Depends(get_strategy_resolver)],
    execution: Annotated[ExecutionSettings, Depends(get_execution_settings)],
) -> AgentRunService:
    settings = get_settings()
    return AgentRunService(
        session,
        market,
        trading,
        strategy_for,
        watchlist=settings.watchlist,
        max_proposals=settings.agent_max_proposals,
        require_market_open=execution.enforce_market_hours,
        benchmark=settings.benchmark_symbol,
    )


PortfolioServiceDep = Annotated[PortfolioService, Depends(get_portfolio_service)]
MarketDataServiceDep = Annotated[MarketDataService, Depends(get_market_data_service)]
PerformanceServiceDep = Annotated[PerformanceService, Depends(get_performance_service)]
TradingServiceDep = Annotated[TradingService, Depends(get_trading_service)]
AgentRunServiceDep = Annotated[AgentRunService, Depends(get_agent_service)]
