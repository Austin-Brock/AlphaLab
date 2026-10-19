"""Market data cache: latest prices and price bars.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

bar_timeframe = sa.Enum("1Min", "5Min", "15Min", "1Hour", "1Day", name="bar_timeframe")


def upgrade() -> None:
    op.create_table(
        "latest_prices",
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("price", sa.Numeric(20, 4), nullable=False),
        sa.Column("price_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
    )

    op.create_table(
        "price_bars",
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("timeframe", bar_timeframe, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("open", sa.Numeric(20, 4), nullable=False),
        sa.Column("high", sa.Numeric(20, 4), nullable=False),
        sa.Column("low", sa.Numeric(20, 4), nullable=False),
        sa.Column("close", sa.Numeric(20, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("price_bars")
    op.drop_table("latest_prices")
    bar_timeframe.drop(op.get_bind())
