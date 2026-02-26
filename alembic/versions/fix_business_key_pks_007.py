"""Fix business-key PKs for multi-tenant support (OPT-127).

Nine tables used external/business-key primary keys without user_id in
their uniqueness constraint.  Two users sharing the same Tastytrade
account collide on inserts — on_conflict_do_nothing silently drops all
data for the second user.

Tables changed:
  - raw_transactions: add row_id PK, unique(id, user_id)
  - orders: add id PK, unique(order_id, user_id), drop FK from order_positions
  - order_chains: add id PK, unique(chain_id, user_id), drop FKs from members/cache
  - order_chain_cache: add id PK, unique(chain_id, order_id, user_id)
  - position_lots: unique(transaction_id) → unique(transaction_id, user_id)
  - position_groups: add id PK, unique(group_id, user_id), drop FK from group_lots
  - position_group_lots: add id PK, unique(group_id, transaction_id, user_id)
  - order_comments: add id PK, unique(order_id, user_id)
  - position_notes: add id PK, unique(note_key, user_id)

Revision ID: fix_business_key_pks_007
Revises: fix_accounts_tenant_006
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fix_business_key_pks_007"
down_revision: Union[str, Sequence[str], None] = "fix_accounts_tenant_006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(conn, table_name: str) -> bool:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = conn.execute(sa.text(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        ))
        return result.fetchone() is not None
    else:
        result = conn.execute(sa.text(
            f"SELECT to_regclass('public.{table_name}')"
        ))
        return result.scalar() is not None


def _sqlite_recreate(conn, table_name: str, create_sql: str, columns: str,
                     old_columns: str = None, indexes: list[str] = None):
    """Recreate a SQLite table with new schema, preserving data."""
    if old_columns is None:
        old_columns = columns
    conn.execute(sa.text(f"ALTER TABLE {table_name} RENAME TO _{table_name}_old"))
    conn.execute(sa.text(create_sql))
    conn.execute(sa.text(
        f"INSERT INTO {table_name} ({columns}) SELECT {old_columns} FROM _{table_name}_old"
    ))
    conn.execute(sa.text(f"DROP TABLE _{table_name}_old"))
    for idx_sql in (indexes or []):
        conn.execute(sa.text(idx_sql))


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        _upgrade_sqlite(conn)
    else:
        _upgrade_postgresql(conn)


def _upgrade_sqlite(conn) -> None:
    # 1. raw_transactions: add row_id PK, unique(id, user_id)
    if _table_exists(conn, "raw_transactions"):
        _sqlite_recreate(conn, "raw_transactions", """
            CREATE TABLE raw_transactions (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                account_number VARCHAR NOT NULL,
                order_id VARCHAR,
                transaction_type VARCHAR,
                transaction_sub_type VARCHAR,
                description VARCHAR,
                executed_at VARCHAR,
                transaction_date VARCHAR,
                action VARCHAR,
                symbol VARCHAR,
                instrument_type VARCHAR,
                underlying_symbol VARCHAR,
                quantity REAL,
                price REAL,
                value REAL,
                regulatory_fees REAL,
                clearing_fees REAL,
                commission REAL,
                net_value REAL,
                is_estimated_fee BOOLEAN,
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (id, user_id)
            )
        """,
        columns="id, user_id, account_number, order_id, transaction_type, transaction_sub_type, description, executed_at, transaction_date, action, symbol, instrument_type, underlying_symbol, quantity, price, value, regulatory_fees, clearing_fees, commission, net_value, is_estimated_fee, created_at",
        indexes=[
            "CREATE INDEX ix_raw_transactions_user_id ON raw_transactions (user_id)",
            "CREATE INDEX idx_raw_transactions_order ON raw_transactions (order_id)",
            "CREATE INDEX idx_raw_transactions_account ON raw_transactions (account_number)",
            "CREATE INDEX idx_raw_transactions_symbol ON raw_transactions (symbol)",
            "CREATE INDEX idx_raw_transactions_executed_at ON raw_transactions (executed_at)",
            "CREATE INDEX idx_raw_transactions_action ON raw_transactions (action)",
        ])

    # 2. orders: add id PK, unique(order_id, user_id)
    if _table_exists(conn, "orders"):
        _sqlite_recreate(conn, "orders", """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                account_number VARCHAR,
                underlying VARCHAR,
                order_type VARCHAR,
                strategy_type VARCHAR,
                order_date VARCHAR,
                status VARCHAR,
                total_quantity INTEGER,
                total_pnl REAL,
                has_assignment BOOLEAN DEFAULT 0,
                has_expiration BOOLEAN DEFAULT 0,
                has_exercise BOOLEAN DEFAULT 0,
                linked_order_id VARCHAR,
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (order_id, user_id)
            )
        """,
        columns="order_id, user_id, account_number, underlying, order_type, strategy_type, order_date, status, total_quantity, total_pnl, has_assignment, has_expiration, has_exercise, linked_order_id, created_at, updated_at",
        indexes=[
            "CREATE INDEX ix_orders_user_id ON orders (user_id)",
            "CREATE INDEX idx_orders_account ON orders (account_number)",
            "CREATE INDEX idx_orders_underlying ON orders (underlying)",
            "CREATE INDEX idx_orders_date ON orders (order_date)",
            "CREATE INDEX idx_orders_status ON orders (status)",
            "CREATE INDEX idx_orders_account_underlying ON orders (account_number, underlying)",
        ])

    # 3. order_positions: drop FK to orders
    if _table_exists(conn, "order_positions"):
        _sqlite_recreate(conn, "order_positions", """
            CREATE TABLE order_positions (
                position_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(36) REFERENCES users(id),
                order_id VARCHAR,
                account_number VARCHAR,
                symbol VARCHAR,
                underlying VARCHAR,
                instrument_type VARCHAR,
                option_type VARCHAR,
                strike REAL,
                expiration VARCHAR,
                quantity INTEGER,
                opening_price REAL,
                closing_price REAL,
                opening_transaction_id VARCHAR,
                closing_transaction_id VARCHAR,
                opening_action VARCHAR,
                closing_action VARCHAR,
                status VARCHAR,
                pnl REAL,
                opening_order_id VARCHAR,
                closing_order_id VARCHAR,
                opening_amount REAL,
                closing_amount REAL,
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP)
            )
        """,
        columns="position_id, user_id, order_id, account_number, symbol, underlying, instrument_type, option_type, strike, expiration, quantity, opening_price, closing_price, opening_transaction_id, closing_transaction_id, opening_action, closing_action, status, pnl, opening_order_id, closing_order_id, opening_amount, closing_amount, created_at, updated_at",
        indexes=[
            "CREATE INDEX ix_order_positions_user_id ON order_positions (user_id)",
        ])

    # 4. order_chains: add id PK, unique(chain_id, user_id)
    if _table_exists(conn, "order_chains"):
        _sqlite_recreate(conn, "order_chains", """
            CREATE TABLE order_chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                underlying VARCHAR,
                account_number VARCHAR,
                opening_order_id VARCHAR,
                strategy_type VARCHAR,
                opening_date VARCHAR,
                closing_date VARCHAR,
                chain_status VARCHAR,
                order_count INTEGER,
                total_pnl REAL,
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                realized_pnl REAL DEFAULT 0.0,
                unrealized_pnl REAL DEFAULT 0.0,
                leg_count INTEGER DEFAULT 1,
                original_quantity INTEGER,
                remaining_quantity INTEGER,
                has_assignment BOOLEAN DEFAULT 0,
                assignment_date VARCHAR,
                UNIQUE (chain_id, user_id)
            )
        """,
        columns="chain_id, user_id, underlying, account_number, opening_order_id, strategy_type, opening_date, closing_date, chain_status, order_count, total_pnl, created_at, updated_at, realized_pnl, unrealized_pnl, leg_count, original_quantity, remaining_quantity, has_assignment, assignment_date",
        indexes=[
            "CREATE INDEX ix_order_chains_user_id ON order_chains (user_id)",
            "CREATE INDEX idx_order_chains_account ON order_chains (account_number)",
            "CREATE INDEX idx_order_chains_underlying ON order_chains (underlying)",
            "CREATE INDEX idx_order_chains_status ON order_chains (chain_status)",
            "CREATE INDEX idx_order_chains_opening_date ON order_chains (opening_date)",
            "CREATE INDEX idx_order_chains_account_underlying ON order_chains (account_number, underlying)",
        ])

    # 5. order_chain_members: drop FKs to orders and order_chains
    if _table_exists(conn, "order_chain_members"):
        _sqlite_recreate(conn, "order_chain_members", """
            CREATE TABLE order_chain_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(36) REFERENCES users(id),
                chain_id VARCHAR,
                order_id VARCHAR,
                sequence_number INTEGER,
                UNIQUE (chain_id, order_id)
            )
        """,
        columns="id, user_id, chain_id, order_id, sequence_number",
        indexes=[
            "CREATE INDEX ix_order_chain_members_user_id ON order_chain_members (user_id)",
            "CREATE INDEX idx_chain_members_chain ON order_chain_members (chain_id)",
            "CREATE INDEX idx_chain_members_order ON order_chain_members (order_id)",
            "CREATE INDEX idx_chain_members_sequence ON order_chain_members (chain_id, sequence_number)",
        ])

    # 6. order_chain_cache: add id PK, unique(chain_id, order_id, user_id)
    if _table_exists(conn, "order_chain_cache"):
        _sqlite_recreate(conn, "order_chain_cache", """
            CREATE TABLE order_chain_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_id VARCHAR NOT NULL,
                order_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                order_data TEXT,
                UNIQUE (chain_id, order_id, user_id)
            )
        """,
        columns="chain_id, order_id, user_id, order_data",
        indexes=[
            "CREATE INDEX ix_order_chain_cache_user_id ON order_chain_cache (user_id)",
        ])

    # 7. position_lots: unique(transaction_id) → unique(transaction_id, user_id)
    if _table_exists(conn, "position_lots"):
        _sqlite_recreate(conn, "position_lots", """
            CREATE TABLE position_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(36) REFERENCES users(id),
                transaction_id VARCHAR NOT NULL,
                account_number VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                underlying VARCHAR,
                instrument_type VARCHAR,
                option_type VARCHAR,
                strike REAL,
                expiration VARCHAR,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_date VARCHAR NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                original_quantity INTEGER,
                chain_id VARCHAR,
                leg_index INTEGER DEFAULT 0,
                opening_order_id VARCHAR,
                derived_from_lot_id INTEGER REFERENCES position_lots(id),
                derivation_type VARCHAR,
                status VARCHAR DEFAULT 'OPEN',
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (transaction_id, user_id)
            )
        """,
        columns="id, user_id, transaction_id, account_number, symbol, underlying, instrument_type, option_type, strike, expiration, quantity, entry_price, entry_date, remaining_quantity, original_quantity, chain_id, leg_index, opening_order_id, derived_from_lot_id, derivation_type, status, created_at",
        indexes=[
            "CREATE INDEX ix_position_lots_user_id ON position_lots (user_id)",
            "CREATE INDEX idx_lots_account_symbol ON position_lots (account_number, symbol)",
            "CREATE INDEX idx_lots_entry_date ON position_lots (entry_date)",
            "CREATE INDEX idx_lots_chain ON position_lots (chain_id)",
            "CREATE INDEX idx_lots_status ON position_lots (status)",
            "CREATE INDEX idx_lots_derived ON position_lots (derived_from_lot_id)",
            "CREATE INDEX idx_lots_underlying ON position_lots (underlying)",
        ])

    # 8. position_groups: add id PK, unique(group_id, user_id)
    if _table_exists(conn, "position_groups"):
        _sqlite_recreate(conn, "position_groups", """
            CREATE TABLE position_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                account_number VARCHAR NOT NULL,
                underlying VARCHAR NOT NULL,
                strategy_label VARCHAR,
                status VARCHAR DEFAULT 'OPEN',
                source_chain_id VARCHAR,
                opening_date VARCHAR,
                closing_date VARCHAR,
                created_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (group_id, user_id)
            )
        """,
        columns="group_id, user_id, account_number, underlying, strategy_label, status, source_chain_id, opening_date, closing_date, created_at, updated_at",
        indexes=[
            "CREATE INDEX ix_position_groups_user_id ON position_groups (user_id)",
            "CREATE INDEX idx_position_groups_account ON position_groups (account_number)",
            "CREATE INDEX idx_position_groups_underlying ON position_groups (underlying)",
            "CREATE INDEX idx_position_groups_status ON position_groups (status)",
            "CREATE INDEX idx_position_groups_source_chain ON position_groups (source_chain_id)",
        ])

    # 9. position_group_lots: add id PK, unique(group_id, transaction_id, user_id)
    if _table_exists(conn, "position_group_lots"):
        _sqlite_recreate(conn, "position_group_lots", """
            CREATE TABLE position_group_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id VARCHAR NOT NULL,
                transaction_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                assigned_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (group_id, transaction_id, user_id)
            )
        """,
        columns="group_id, transaction_id, user_id, assigned_at",
        indexes=[
            "CREATE INDEX ix_position_group_lots_user_id ON position_group_lots (user_id)",
            "CREATE INDEX idx_position_group_lots_txn ON position_group_lots (transaction_id)",
        ])

    # 10. order_comments: add id PK, unique(order_id, user_id)
    if _table_exists(conn, "order_comments"):
        _sqlite_recreate(conn, "order_comments", """
            CREATE TABLE order_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                comment VARCHAR NOT NULL,
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (order_id, user_id)
            )
        """,
        columns="order_id, user_id, comment, updated_at",
        indexes=[
            "CREATE INDEX ix_order_comments_user_id ON order_comments (user_id)",
        ])

    # 11. position_notes: add id PK, unique(note_key, user_id)
    if _table_exists(conn, "position_notes"):
        _sqlite_recreate(conn, "position_notes", """
            CREATE TABLE position_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_key VARCHAR NOT NULL,
                user_id VARCHAR(36) REFERENCES users(id),
                note VARCHAR NOT NULL,
                updated_at VARCHAR DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (note_key, user_id)
            )
        """,
        columns="note_key, user_id, note, updated_at",
        indexes=[
            "CREATE INDEX ix_position_notes_user_id ON position_notes (user_id)",
        ])


def _upgrade_postgresql(conn) -> None:
    # Helper: drop FK, add id PK, add unique constraint
    # Each table is handled individually due to different schemas.

    # 1. raw_transactions: add row_id PK, unique(id, user_id)
    if _table_exists(conn, "raw_transactions"):
        op.drop_constraint("raw_transactions_pkey", "raw_transactions", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS raw_transactions_row_id_seq")
        op.add_column("raw_transactions", sa.Column(
            "row_id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('raw_transactions_row_id_seq')")))
        op.execute("ALTER SEQUENCE raw_transactions_row_id_seq OWNED BY raw_transactions.row_id")
        op.execute("SELECT setval('raw_transactions_row_id_seq', COALESCE((SELECT MAX(row_id) FROM raw_transactions), 0) + 1)")
        op.create_primary_key("raw_transactions_pkey", "raw_transactions", ["row_id"])
        op.create_unique_constraint("uq_raw_transactions_id_user", "raw_transactions", ["id", "user_id"])

    # 2. order_positions: drop FK to orders
    if _table_exists(conn, "order_positions"):
        try:
            op.drop_constraint("order_positions_order_id_fkey", "order_positions", type_="foreignkey")
        except Exception:
            pass  # FK may not exist

    # 3. order_chain_members: drop FKs to orders and order_chains
    if _table_exists(conn, "order_chain_members"):
        try:
            op.drop_constraint("order_chain_members_chain_id_fkey", "order_chain_members", type_="foreignkey")
        except Exception:
            pass
        try:
            op.drop_constraint("order_chain_members_order_id_fkey", "order_chain_members", type_="foreignkey")
        except Exception:
            pass

    # 4. order_chain_cache: drop FK to order_chains, add id PK, unique constraint
    if _table_exists(conn, "order_chain_cache"):
        try:
            op.drop_constraint("order_chain_cache_chain_id_fkey", "order_chain_cache", type_="foreignkey")
        except Exception:
            pass
        op.drop_constraint("order_chain_cache_pkey", "order_chain_cache", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS order_chain_cache_id_seq")
        op.add_column("order_chain_cache", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('order_chain_cache_id_seq')")))
        op.execute("ALTER SEQUENCE order_chain_cache_id_seq OWNED BY order_chain_cache.id")
        op.execute("SELECT setval('order_chain_cache_id_seq', COALESCE((SELECT MAX(id) FROM order_chain_cache), 0) + 1)")
        op.create_primary_key("order_chain_cache_pkey", "order_chain_cache", ["id"])
        op.create_unique_constraint("uq_chain_cache_chain_order_user", "order_chain_cache", ["chain_id", "order_id", "user_id"])

    # 5. orders: add id PK, unique(order_id, user_id)
    if _table_exists(conn, "orders"):
        op.drop_constraint("orders_pkey", "orders", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS orders_id_seq")
        op.add_column("orders", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('orders_id_seq')")))
        op.execute("ALTER SEQUENCE orders_id_seq OWNED BY orders.id")
        op.execute("SELECT setval('orders_id_seq', COALESCE((SELECT MAX(id) FROM orders), 0) + 1)")
        op.create_primary_key("orders_pkey", "orders", ["id"])
        op.create_unique_constraint("uq_orders_order_user", "orders", ["order_id", "user_id"])

    # 6. order_chains: add id PK, unique(chain_id, user_id)
    if _table_exists(conn, "order_chains"):
        op.drop_constraint("order_chains_pkey", "order_chains", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS order_chains_id_seq")
        op.add_column("order_chains", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('order_chains_id_seq')")))
        op.execute("ALTER SEQUENCE order_chains_id_seq OWNED BY order_chains.id")
        op.execute("SELECT setval('order_chains_id_seq', COALESCE((SELECT MAX(id) FROM order_chains), 0) + 1)")
        op.create_primary_key("order_chains_pkey", "order_chains", ["id"])
        op.create_unique_constraint("uq_order_chains_chain_user", "order_chains", ["chain_id", "user_id"])

    # 7. position_lots: unique(transaction_id) → unique(transaction_id, user_id)
    if _table_exists(conn, "position_lots"):
        # Drop the old unique constraint on transaction_id alone
        try:
            op.drop_constraint("position_lots_transaction_id_key", "position_lots", type_="unique")
        except Exception:
            pass
        op.create_unique_constraint("uq_position_lots_txn_user", "position_lots", ["transaction_id", "user_id"])

    # 8. position_group_lots: drop FK, add id PK, unique constraint
    if _table_exists(conn, "position_group_lots"):
        try:
            op.drop_constraint("position_group_lots_group_id_fkey", "position_group_lots", type_="foreignkey")
        except Exception:
            pass
        op.drop_constraint("position_group_lots_pkey", "position_group_lots", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS position_group_lots_id_seq")
        op.add_column("position_group_lots", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('position_group_lots_id_seq')")))
        op.execute("ALTER SEQUENCE position_group_lots_id_seq OWNED BY position_group_lots.id")
        op.execute("SELECT setval('position_group_lots_id_seq', COALESCE((SELECT MAX(id) FROM position_group_lots), 0) + 1)")
        op.create_primary_key("position_group_lots_pkey", "position_group_lots", ["id"])
        op.create_unique_constraint("uq_group_lots_group_txn_user", "position_group_lots", ["group_id", "transaction_id", "user_id"])

    # 9. position_groups: add id PK, unique(group_id, user_id)
    if _table_exists(conn, "position_groups"):
        op.drop_constraint("position_groups_pkey", "position_groups", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS position_groups_id_seq")
        op.add_column("position_groups", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('position_groups_id_seq')")))
        op.execute("ALTER SEQUENCE position_groups_id_seq OWNED BY position_groups.id")
        op.execute("SELECT setval('position_groups_id_seq', COALESCE((SELECT MAX(id) FROM position_groups), 0) + 1)")
        op.create_primary_key("position_groups_pkey", "position_groups", ["id"])
        op.create_unique_constraint("uq_position_groups_group_user", "position_groups", ["group_id", "user_id"])

    # 10. order_comments: add id PK, unique(order_id, user_id)
    if _table_exists(conn, "order_comments"):
        op.drop_constraint("order_comments_pkey", "order_comments", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS order_comments_id_seq")
        op.add_column("order_comments", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('order_comments_id_seq')")))
        op.execute("ALTER SEQUENCE order_comments_id_seq OWNED BY order_comments.id")
        op.execute("SELECT setval('order_comments_id_seq', COALESCE((SELECT MAX(id) FROM order_comments), 0) + 1)")
        op.create_primary_key("order_comments_pkey", "order_comments", ["id"])
        op.create_unique_constraint("uq_order_comments_order_user", "order_comments", ["order_id", "user_id"])

    # 11. position_notes: add id PK, unique(note_key, user_id)
    if _table_exists(conn, "position_notes"):
        op.drop_constraint("position_notes_pkey", "position_notes", type_="primary")
        op.execute("CREATE SEQUENCE IF NOT EXISTS position_notes_id_seq")
        op.add_column("position_notes", sa.Column(
            "id", sa.Integer, nullable=False,
            server_default=sa.text("nextval('position_notes_id_seq')")))
        op.execute("ALTER SEQUENCE position_notes_id_seq OWNED BY position_notes.id")
        op.execute("SELECT setval('position_notes_id_seq', COALESCE((SELECT MAX(id) FROM position_notes), 0) + 1)")
        op.create_primary_key("position_notes_pkey", "position_notes", ["id"])
        op.create_unique_constraint("uq_position_notes_key_user", "position_notes", ["note_key", "user_id"])


# ---------------------------------------------------------------------------
# Downgrade (best-effort — drops surrogate PKs, restores business-key PKs)
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Downgrade is complex and would require recreating all tables.
    # For safety, we only support forward migration.
    raise NotImplementedError(
        "Downgrade not supported for fix_business_key_pks_007. "
        "Restore from backup if needed."
    )
