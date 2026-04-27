"""Add parent_lot_id to position_lots for lot-level roll lineage (OPT-284 Phase 1).

Revision ID: add_parent_lot_id_019
Revises: 9264427376c0

The parent_lot_id column is the foundation of the lot-level chain model:
each new lot points at the closing lot it continued from (or NULL if no
prior lot — a fresh open). This phase is additive and reversible: the
column is nullable, populated only by a backfill stage, and not yet
authoritative for detection. Group-level rolled_from_group_id remains
the source of truth until OPT-284 Phase 2.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "add_parent_lot_id_019"
down_revision: str = "9264427376c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "position_lots",
        sa.Column("parent_lot_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_position_lots_parent",
        "position_lots", "position_lots",
        ["parent_lot_id"], ["id"],
    )
    op.create_index(
        "idx_lots_parent", "position_lots", ["parent_lot_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_lots_parent", table_name="position_lots")
    op.drop_constraint("fk_position_lots_parent", "position_lots", type_="foreignkey")
    op.drop_column("position_lots", "parent_lot_id")
