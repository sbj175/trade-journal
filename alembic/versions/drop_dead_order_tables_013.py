"""Drop dead orders, order_positions, order_chain_members tables.

These tables were written to but never read. All functionality now uses
order_chains + order_chain_cache + position_lots.

Revision ID: drop_dead_order_tables_013
Revises: add_pnl_events_012
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "drop_dead_order_tables_013"
down_revision: Union[str, Sequence[str], None] = "add_pnl_events_012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FK dependents first
    op.drop_table("order_chain_members")
    op.drop_table("order_positions")
    op.drop_table("orders")


def downgrade() -> None:
    # Recreate tables in dependency order (orders first, then dependents)
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("account_number", sa.String, nullable=False),
        sa.Column("time_in_force", sa.String),
        sa.Column("order_type", sa.String),
        sa.Column("status", sa.String),
        sa.Column("price", sa.Float),
        sa.Column("price_effect", sa.String),
        sa.Column("received_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
        sa.Column("cancelled_at", sa.DateTime),
        sa.Column("user_id", sa.String, nullable=False),
    )
    op.create_table(
        "order_positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("instrument_type", sa.String),
        sa.Column("action", sa.String),
        sa.Column("quantity", sa.Float),
        sa.Column("fill_price", sa.Float),
        sa.Column("user_id", sa.String, nullable=False),
    )
    op.create_table(
        "order_chain_members",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String, nullable=False),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("user_id", sa.String, nullable=False),
    )
