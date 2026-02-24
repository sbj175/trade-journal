"""drop chain_merges table

Revision ID: drop_chain_merges_002
Revises: add_user_id_001
Create Date: 2026-02-23

Removes the chain_merges table, which was a short-lived mechanism for
tracking chain merges (Feb 16-17). Superseded by position_groups.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'drop_chain_merges_002'
down_revision: Union[str, Sequence[str], None] = 'add_user_id_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("chain_merges")


def downgrade() -> None:
    op.create_table(
        "chain_merges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("merged_chain_id", sa.String, nullable=False),
        sa.Column("source_chain_id", sa.String, nullable=False),
        sa.Column("underlying", sa.String, nullable=False),
        sa.Column("account_number", sa.String, nullable=False),
        sa.Column("merged_at", sa.String, server_default=sa.func.now()),
    )
