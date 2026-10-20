import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.api.deps import (
    get_execution_settings,
    get_market_data_provider,
    get_strategy_resolver,
)
from app.config import DEFAULT_WATCHLIST
from app.db import get_session
from app.main import app
from app.strategies.ai import AITradingStrategy
from app.trading.service import ExecutionSettings
from tests.fakes import FakeLLM, FakeMarketDataProvider

TEST_DATABASE_URL = os.environ.get(
    "ALPHALAB_TEST_DATABASE_URL",
    "postgresql+psycopg://alphalab:alphalab@localhost:5432/alphalab_test",
)
BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Build the schema with the real migrations, so tests also cover them."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose commits become savepoints inside a transaction rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session
        transaction.rollback()


@pytest.fixture
def fake_market() -> FakeMarketDataProvider:
    """Prices for the whole default watchlist: $100, $101, ..."""
    return FakeMarketDataProvider(
        {symbol: Decimal(100 + i) for i, symbol in enumerate(DEFAULT_WATCHLIST)}
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    """Scripted model for API tests; set `fake_llm.turns` before triggering a run."""
    return FakeLLM()


@pytest.fixture
def client(
    session: Session, fake_market: FakeMarketDataProvider, fake_llm: FakeLLM
) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    # Always override so tests never call the real Alpaca API, even with keys configured.
    app.dependency_overrides[get_market_data_provider] = lambda: fake_market
    # Default trading settings, regardless of what the local .env sets.
    app.dependency_overrides[get_execution_settings] = ExecutionSettings
    # Never call AWS from tests.
    app.dependency_overrides[get_strategy_resolver] = lambda: (
        lambda sid: AITradingStrategy(fake_llm) if sid == "ai-trading-v1" else None
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
