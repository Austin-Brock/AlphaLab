"""Trading engine: risk limits, orders, risk checks, executions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

order_side = sa.Enum("BUY", "SELL", name="order_side")
order_status = sa.Enum("PENDING", "REJECTED", "APPROVED", "FILLED", name="order_status")


def upgrade() -> None:
    # Ledger entries written in one transaction get distinct, ordered timestamps.
    op.alter_column("cash_ledger", "created_at", server_default=sa.func.clock_timestamp())

    # Existing portfolios get the default limits: max 10% per position, min 5% cash.
    op.add_column(
        "portfolios",
        sa.Column("max_position_pct", sa.Numeric(5, 4), server_default="0.10", nullable=False),
    )
    op.add_column(
        "portfolios",
        sa.Column("min_cash_pct", sa.Numeric(5, 4), server_default="0.05", nullable=False),
    )
    op.alter_column("portfolios", "max_position_pct", server_default=None)
    op.alter_column("portfolios", "min_cash_pct", server_default=None)
    op.create_check_constraint(
        "max_position_pct_range", "portfolios", "max_position_pct > 0 AND max_position_pct <= 1"
    )
    op.create_check_constraint(
        "min_cash_pct_range", "portfolios", "min_cash_pct >= 0 AND min_cash_pct < 1"
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("client_order_id", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("status", order_status, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 4)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="order_quantity_positive"),
        sa.UniqueConstraint("portfolio_id", "client_order_id", name="uq_orders_client_order_id"),
    )
    op.create_index("ix_orders_portfolio_id", "orders", ["portfolio_id"])

    op.create_table(
        "risk_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("check_name", sa.String(100), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_risk_checks_order_id", "risk_checks", ["order_id"])

    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(20, 4), nullable=False),
        sa.Column("market_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("gross_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("commission", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="execution_quantity_positive"),
        sa.CheckConstraint("price > 0", name="execution_price_positive"),
    )
    op.create_index("ix_executions_portfolio_id", "executions", ["portfolio_id"])


def downgrade() -> None:
    op.drop_table("executions")
    op.drop_table("risk_checks")
    op.drop_table("orders")
    order_status.drop(op.get_bind())
    order_side.drop(op.get_bind())
    op.drop_constraint("min_cash_pct_range", "portfolios")
    op.drop_constraint("max_position_pct_range", "portfolios")
    op.drop_column("portfolios", "min_cash_pct")
    op.drop_column("portfolios", "max_position_pct")
    op.alter_column("cash_ledger", "created_at", server_default=sa.func.now())
