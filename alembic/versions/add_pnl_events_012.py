"""Add pnl_events table and last_activity_date to position_groups.

Revision ID: add_pnl_events_012
Revises: add_strategy_override_011
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_pnl_events_012"
down_revision: Union[str, Sequence[str], None] = "add_strategy_override_011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_activity_date to position_groups
    op.add_column(
        "position_groups",
        sa.Column("last_activity_date", sa.String(), nullable=True),
    )

    # Create pnl_events table (unique constraint inline for SQLite compat)
    op.create_table(
        "pnl_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closing_id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("account_number", sa.String(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("expiration", sa.String(), nullable=True),
        sa.Column("entry_date", sa.String(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("closing_date", sa.String(), nullable=False),
        sa.Column("closing_price", sa.Float(), nullable=False),
        sa.Column("closing_type", sa.String(), nullable=False),
        sa.Column("quantity_closed", sa.Integer(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("is_roll", sa.Boolean(), server_default=sa.false()),
        sa.UniqueConstraint("closing_id", "user_id", name="uq_pnl_events_closing_user"),
    )

    op.create_index("idx_pnl_events_user_id", "pnl_events", ["user_id"])
    op.create_index("idx_pnl_events_closing_date", "pnl_events", ["closing_date", "user_id"])
    op.create_index("idx_pnl_events_account_date", "pnl_events", ["account_number", "closing_date"])
    op.create_index("idx_pnl_events_group", "pnl_events", ["group_id"])
    op.create_index("idx_pnl_events_underlying", "pnl_events", ["underlying"])


def downgrade() -> None:
    op.drop_table("pnl_events")
    op.drop_column("position_groups", "last_activity_date")
