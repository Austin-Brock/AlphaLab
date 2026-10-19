"""Portfolio foundation: portfolios, cash ledger, positions.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

portfolio_status = sa.Enum("ACTIVE", "PAUSED", "CLOSED", name="portfolio_status")
ledger_entry_type = sa.Enum(
    "DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "FEE", "DIVIDEND", name="ledger_entry_type"
)


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("starting_capital", sa.Numeric(20, 4), nullable=False),
        sa.Column("strategy_id", sa.String(100), nullable=False),
        sa.Column("status", portfolio_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("starting_capital > 0", name="starting_capital_positive"),
    )

    op.create_table(
        "cash_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("entry_type", ledger_entry_type, nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("reference_id", sa.String(100)),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount <> 0", name="amount_nonzero"),
        sa.UniqueConstraint("portfolio_id", "idempotency_key", name="uq_cash_ledger_idempotency"),
    )
    op.create_index("ix_cash_ledger_portfolio_id", "cash_ledger", ["portfolio_id"])

    # Rule 3 (no direct balance mutations): ledger rows can be inserted, never changed.
    op.execute(
        """
        CREATE FUNCTION cash_ledger_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'cash_ledger is append-only; % is not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER cash_ledger_no_update_delete
        BEFORE UPDATE OR DELETE ON cash_ledger
        FOR EACH ROW EXECUTE FUNCTION cash_ledger_append_only();
        """
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_positions_portfolio_symbol"),
        sa.CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        sa.CheckConstraint("average_cost >= 0", name="average_cost_non_negative"),
    )
    op.create_index("ix_positions_portfolio_id", "positions", ["portfolio_id"])


def downgrade() -> None:
    op.drop_table("positions")
    op.execute("DROP TRIGGER cash_ledger_no_update_delete ON cash_ledger")
    op.execute("DROP FUNCTION cash_ledger_append_only()")
    op.drop_table("cash_ledger")
    op.drop_table("portfolios")
    ledger_entry_type.drop(op.get_bind())
    portfolio_status.drop(op.get_bind())
