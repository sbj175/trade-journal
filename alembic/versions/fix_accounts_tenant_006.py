"""Fix Account multi-tenant scoping (OPT-126).

Account PK was globally unique (account_number alone), so the upsert
overwrote user_id.  This migration:
  1. Drops the FK from positions → accounts.account_number
  2. Replaces the accounts PK with an autoincrement id
  3. Adds a UniqueConstraint(account_number, user_id)

Revision ID: fix_accounts_tenant_006
Revises: drop_positions_inventory_005
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fix_accounts_tenant_006"
down_revision: Union[str, Sequence[str], None] = "drop_positions_inventory_005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        _upgrade_sqlite(conn)
    else:
        _upgrade_postgresql()


def _upgrade_sqlite(conn) -> None:
    """SQLite requires table recreation for PK changes."""

    # Note: The FK on positions.account_number → accounts.account_number is
    # left in place.  SQLite does not enforce FKs unless PRAGMA foreign_keys
    # is ON (our env.py does not set it), so the orphaned reference is harmless.
    # The ORM model no longer declares the FK.

    # Recreate accounts table with new schema
    #    - Rename old table
    conn.execute(sa.text("ALTER TABLE accounts RENAME TO _accounts_old"))

    #    - Create new table
    conn.execute(sa.text("""
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_number VARCHAR NOT NULL,
            user_id VARCHAR(36) REFERENCES users(id),
            account_name VARCHAR,
            account_type VARCHAR,
            is_active BOOLEAN DEFAULT 1,
            created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
            updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE (account_number, user_id)
        )
    """))

    #    - Copy data
    conn.execute(sa.text("""
        INSERT INTO accounts (account_number, user_id, account_name, account_type, is_active, created_at, updated_at)
        SELECT account_number, user_id, account_name, account_type, is_active, created_at, updated_at
        FROM _accounts_old
    """))

    #    - Drop old table
    conn.execute(sa.text("DROP TABLE _accounts_old"))

    #    - Recreate indexes
    conn.execute(sa.text(
        "CREATE INDEX idx_accounts_active ON accounts (is_active)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX ix_accounts_user_id ON accounts (user_id)"
    ))


def _upgrade_postgresql() -> None:
    """PostgreSQL supports ALTER TABLE directly."""

    # 1. Drop FK from positions → accounts
    op.drop_constraint(
        "positions_account_number_fkey", "positions", type_="foreignkey"
    )

    # 2. Drop PK on accounts
    op.drop_constraint("accounts_pkey", "accounts", type_="primary")

    # 3. Add id column as new PK (create sequence first, then reference it)
    op.execute("CREATE SEQUENCE accounts_id_seq")
    op.add_column(
        "accounts",
        sa.Column("id", sa.Integer, nullable=False,
                  server_default=sa.text("nextval('accounts_id_seq')")),
    )
    op.execute("ALTER SEQUENCE accounts_id_seq OWNED BY accounts.id")
    op.execute("SELECT setval('accounts_id_seq', COALESCE((SELECT MAX(id) FROM accounts), 0) + 1)")
    op.create_primary_key("accounts_pkey", "accounts", ["id"])

    # 4. Add unique constraint
    op.create_unique_constraint(
        "uq_accounts_number_user", "accounts", ["account_number", "user_id"]
    )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        _downgrade_sqlite(conn)
    else:
        _downgrade_postgresql()


def _downgrade_sqlite(conn) -> None:
    # Recreate accounts with account_number as PK
    conn.execute(sa.text("ALTER TABLE accounts RENAME TO _accounts_old"))
    conn.execute(sa.text("""
        CREATE TABLE accounts (
            account_number VARCHAR PRIMARY KEY,
            user_id VARCHAR(36) REFERENCES users(id),
            account_name VARCHAR,
            account_type VARCHAR,
            is_active BOOLEAN DEFAULT 1,
            created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
            updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP)
        )
    """))
    conn.execute(sa.text("""
        INSERT OR IGNORE INTO accounts (account_number, user_id, account_name, account_type, is_active, created_at, updated_at)
        SELECT account_number, user_id, account_name, account_type, is_active, created_at, updated_at
        FROM _accounts_old
    """))
    conn.execute(sa.text("DROP TABLE _accounts_old"))
    conn.execute(sa.text(
        "CREATE INDEX idx_accounts_active ON accounts (is_active)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX ix_accounts_user_id ON accounts (user_id)"
    ))

    # Re-add FK on positions
    # SQLite can't add FK after the fact; would need batch recreation.
    # Skipping for downgrade — the column still exists, just without the FK.


def _downgrade_postgresql() -> None:
    op.drop_constraint("uq_accounts_number_user", "accounts", type_="unique")
    op.drop_constraint("accounts_pkey", "accounts", type_="primary")
    op.drop_column("accounts", "id")
    op.create_primary_key("accounts_pkey", "accounts", ["account_number"])
    op.create_foreign_key(
        "positions_account_number_fkey", "positions", "accounts",
        ["account_number"], ["account_number"],
    )
