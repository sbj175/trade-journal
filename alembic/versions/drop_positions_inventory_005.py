"""Drop positions_inventory table (OPT-124).

Lots are the sole source of truth for position tracking since OPT-121.
The positions_inventory table and PositionInventoryManager are no longer used.

Revision ID: drop_positions_inventory_005
Revises: add_user_credentials_004
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "drop_positions_inventory_005"
down_revision: Union[str, Sequence[str], None] = "add_user_credentials_004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Guard: skip if table doesn't exist
    if dialect == "sqlite":
        result = conn.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='positions_inventory'"
        ))
        if result.fetchone() is None:
            return
    else:
        result = conn.execute(sa.text(
            "SELECT to_regclass('public.positions_inventory')"
        ))
        if result.scalar() is None:
            return

    op.drop_table("positions_inventory")


def downgrade() -> None:
    op.create_table(
        "positions_inventory",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("account_number", sa.String, nullable=False),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("underlying", sa.String, nullable=False),
        sa.Column("option_type", sa.String),
        sa.Column("strike", sa.Float),
        sa.Column("expiration", sa.String),
        sa.Column("current_quantity", sa.Integer, nullable=False),
        sa.Column("cost_basis", sa.Float, nullable=False),
        sa.Column("last_updated", sa.String, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_positions_inventory_user_account_symbol",
        "positions_inventory",
        ["user_id", "account_number", "symbol"],
    )
    op.create_index(
        "idx_positions_account_underlying",
        "positions_inventory",
        ["account_number", "underlying"],
    )
    op.create_index(
        "idx_positions_inv_symbol",
        "positions_inventory",
        ["symbol"],
    )
