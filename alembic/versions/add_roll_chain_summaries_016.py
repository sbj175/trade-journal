"""Add roll_chain_summaries table.

Materialized roll chain statistics for fast lookup on the Positions page.

Revision ID: add_roll_chain_summaries_016
Revises: drop_source_chain_id_015
"""

import sqlalchemy as sa
from alembic import op

revision: str = "add_roll_chain_summaries_016"
down_revision: str = "drop_source_chain_id_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roll_chain_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("root_group_id", sa.String(), nullable=False),
        sa.Column("current_group_id", sa.String(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("account_number", sa.String(), nullable=False),
        sa.Column("chain_length", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("roll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_opened", sa.String(), nullable=True),
        sa.Column("last_rolled", sa.String(), nullable=True),
        sa.Column("cumulative_premium", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cumulative_realized_pnl", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint(
        "uq_roll_chain_current_group_user",
        "roll_chain_summaries",
        ["current_group_id", "user_id"],
    )
    op.create_index(
        "idx_roll_chain_underlying",
        "roll_chain_summaries",
        ["underlying", "account_number"],
    )
    op.create_index(
        "idx_roll_chain_root",
        "roll_chain_summaries",
        ["root_group_id"],
    )


def downgrade() -> None:
    op.drop_table("roll_chain_summaries")
