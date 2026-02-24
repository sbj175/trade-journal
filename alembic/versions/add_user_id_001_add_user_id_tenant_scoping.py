"""add user_id tenant scoping

Revision ID: add_user_id_001
Revises: 880552b12e57
Create Date: 2026-02-23 21:59:39.768147

Adds multi-tenant scoping:
1. Creates users table
2. Inserts default user
3. Adds user_id column (nullable) to all 19 data tables
4. Backfills existing rows with the default user_id
5. Creates indexes on user_id columns
6. Updates unique constraints on sync_metadata, strategy_targets, positions_inventory
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_user_id_001'
down_revision: Union[str, Sequence[str], None] = '880552b12e57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# Naming convention that matches how SQLAlchemy generates names for unnamed
# constraints reflected from SQLite.  Allows batch mode to find and drop them.
NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

# All tables that get user_id (in safe dependency order)
TENANT_TABLES = [
    "accounts",
    "account_balances",
    "positions",
    "orders",
    "order_positions",
    "order_chains",
    "order_chain_members",
    "order_chain_cache",
    "raw_transactions",
    "sync_metadata",
    "strategy_targets",
    "position_lots",
    "lot_closings",
    "chain_merges",
    "position_groups",
    "position_group_lots",
    "positions_inventory",
    "order_comments",
    "position_notes",
]


def _table_exists(table_name: str) -> bool:
    """Check if a table already exists (handles create_all() race)."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return table_name in insp.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists in a table."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add users table and user_id to all data tables."""
    # 1. Create users table (skip if create_all() already made it)
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String, unique=True, nullable=True),
            sa.Column("display_name", sa.String, nullable=True),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("1")),
            sa.Column("created_at", sa.String, server_default=sa.func.now()),
            sa.Column("updated_at", sa.String, server_default=sa.func.now()),
        )

    # 2. Insert default user (if not already present)
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM users WHERE id = :uid"),
        {"uid": DEFAULT_USER_ID},
    ).first()
    if row is None:
        users_table = sa.table(
            "users",
            sa.column("id", sa.String),
            sa.column("display_name", sa.String),
            sa.column("is_active", sa.Boolean),
        )
        op.bulk_insert(users_table, [
            {"id": DEFAULT_USER_ID, "display_name": "Default User", "is_active": True},
        ])

    # 3. Add user_id column to all 19 tables and backfill
    for table_name in TENANT_TABLES:
        if not _column_exists(table_name, "user_id"):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.add_column(
                    sa.Column("user_id", sa.String(36), nullable=True),
                )

        # Backfill existing rows
        op.execute(
            sa.text(f"UPDATE {table_name} SET user_id = :uid WHERE user_id IS NULL").bindparams(
                uid=DEFAULT_USER_ID
            )
        )

        # Create index (idempotent — batch mode recreates table on SQLite)
        op.create_index(
            f"ix_{table_name}_user_id", table_name, ["user_id"],
            if_not_exists=True,
        )

    # 4. Update unique constraints
    # In SQLite, inline `unique=True` creates unnamed constraints.  Alembic
    # batch mode needs a naming_convention to generate deterministic names so
    # it can find and drop them during the table rebuild.

    # sync_metadata: drop unique on (key), add composite (user_id, key)
    with op.batch_alter_table(
        "sync_metadata",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_sync_metadata_key", type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_sync_metadata_user_key", ["user_id", "key"],
        )

    # strategy_targets: drop unique on (strategy_name), add composite (user_id, strategy_name)
    with op.batch_alter_table(
        "strategy_targets",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_strategy_targets_strategy_name", type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_strategy_targets_user_name", ["user_id", "strategy_name"],
        )

    # positions_inventory: drop unique on (account_number, symbol), add (user_id, account_number, symbol)
    with op.batch_alter_table(
        "positions_inventory",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_positions_inventory_account_number_symbol", type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_positions_inventory_user_account_symbol",
            ["user_id", "account_number", "symbol"],
        )


def downgrade() -> None:
    """Remove user_id from all tables and drop users table."""
    # Restore original unique constraints
    with op.batch_alter_table("positions_inventory") as batch_op:
        batch_op.drop_constraint("uq_positions_inventory_user_account_symbol", type_="unique")
        batch_op.create_unique_constraint(
            "uq_positions_inventory_account_number_symbol",
            ["account_number", "symbol"],
        )

    with op.batch_alter_table("strategy_targets") as batch_op:
        batch_op.drop_constraint("uq_strategy_targets_user_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_strategy_targets_strategy_name", ["strategy_name"]
        )

    with op.batch_alter_table("sync_metadata") as batch_op:
        batch_op.drop_constraint("uq_sync_metadata_user_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_sync_metadata_key", ["key"]
        )

    # Drop user_id columns and indexes
    for table_name in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("user_id")

    # Drop users table
    op.drop_table("users")
