"""Drop source_chain_id column from position_groups.

No longer populated — groups are created directly by GroupPersister,
not seeded from chain_id references.

Revision ID: drop_source_chain_id_015
Revises: add_rolled_from_group_id_014
"""

import sqlalchemy as sa
from alembic import op

revision: str = "drop_source_chain_id_015"
down_revision: str = "add_rolled_from_group_id_014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_position_groups_source_chain", table_name="position_groups")
    op.drop_column("position_groups", "source_chain_id")


def downgrade() -> None:
    op.add_column(
        "position_groups",
        sa.Column("source_chain_id", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_position_groups_source_chain",
        "position_groups",
        ["source_chain_id"],
    )
