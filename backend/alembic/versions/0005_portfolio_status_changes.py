"""Audit trail of portfolio pauses and resumes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Created in 0001; reuse it.
portfolio_status = postgresql.ENUM(
    "ACTIVE", "PAUSED", "CLOSED", name="portfolio_status", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "portfolio_status_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("from_status", portfolio_status, nullable=False),
        sa.Column("to_status", portfolio_status, nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_portfolio_status_changes_portfolio_id", "portfolio_status_changes", ["portfolio_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_status_changes_portfolio_id", table_name="portfolio_status_changes")
    op.drop_table("portfolio_status_changes")
