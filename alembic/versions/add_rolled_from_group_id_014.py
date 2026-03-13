"""Add rolled_from_group_id to position_groups for roll chain tracking.

Revision ID: add_rolled_from_group_id_014
Revises: drop_dead_order_tables_013
"""

from alembic import op
import sqlalchemy as sa

revision: str = "add_rolled_from_group_id_014"
down_revision: str = "drop_dead_order_tables_013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "position_groups",
        sa.Column("rolled_from_group_id", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_position_groups_rolled_from",
        "position_groups",
        ["rolled_from_group_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_position_groups_rolled_from", table_name="position_groups")
    op.drop_column("position_groups", "rolled_from_group_id")
