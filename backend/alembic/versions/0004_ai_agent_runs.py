"""AI agent runs and decisions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_run_status = sa.Enum("RUNNING", "COMPLETED", "FAILED", "SKIPPED", name="agent_run_status")
# Created in 0003; reuse it.
order_side = postgresql.ENUM("BUY", "SELL", name="order_side", create_type=False)


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("strategy_id", sa.String(100), nullable=False),
        sa.Column("run_key", sa.String(200)),
        sa.Column("status", agent_run_status, nullable=False),
        sa.Column("model_id", sa.String(200)),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("transcript", postgresql.JSONB()),
        sa.Column("summary", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("portfolio_id", "run_key", name="uq_agent_runs_run_key"),
    )
    op.create_index("ix_agent_runs_portfolio_id", "agent_runs", ["portfolio_id"])

    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id")),
    )
    op.create_index("ix_agent_decisions_run_id", "agent_decisions", ["run_id"])
    op.create_index("ix_agent_decisions_portfolio_id", "agent_decisions", ["portfolio_id"])


def downgrade() -> None:
    op.drop_table("agent_decisions")
    op.drop_table("agent_runs")
    agent_run_status.drop(op.get_bind())
