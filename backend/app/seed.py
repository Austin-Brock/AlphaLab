"""Create the default V1 portfolio if it doesn't exist yet.

Usage: uv run python -m app.seed
"""

from decimal import Decimal

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Portfolio
from app.services.portfolio import PortfolioService

DEFAULT_NAME = "AlphaLab AI Portfolio"
DEFAULT_CAPITAL = Decimal("1000000.00")
DEFAULT_STRATEGY = "ai-trading-v1"


def main() -> None:
    with get_sessionmaker()() as session:
        existing = session.scalar(select(Portfolio).where(Portfolio.name == DEFAULT_NAME))
        if existing:
            print(f"Portfolio already exists: {existing.id}")
            return
        portfolio = PortfolioService(session).create_portfolio(
            DEFAULT_NAME, DEFAULT_CAPITAL, DEFAULT_STRATEGY
        )
        print(f"Created portfolio {portfolio.id} with ${DEFAULT_CAPITAL:,}")


if __name__ == "__main__":
    main()
