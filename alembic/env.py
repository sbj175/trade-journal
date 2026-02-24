"""
Alembic environment configuration for OptionLedger.

Key settings:
- render_as_batch=True for SQLite (critical for ALTER TABLE support)
- render_as_batch=False for PostgreSQL (not needed, avoids overhead)
- Reads DATABASE_URL from environment, falls back to SQLite
- Imports models so autogenerate can detect schema changes
"""

import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.types import Float, String, Integer, Boolean, Text

from alembic import context

from src.database.models import Base

# Alembic Config object
config = context.config

# Set up Python logging from ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at our declarative metadata for autogenerate support
target_metadata = Base.metadata

# Determine database URL and dialect
_db_url = os.environ.get("DATABASE_URL", "sqlite:///trade_journal.db")
_is_sqlite = _db_url.startswith("sqlite")


# SQLite stores all text as TEXT and numbers as REAL regardless of declared type.
# Suppress cosmetic type differences so autogenerate only flags real changes.
_SQLITE_EQUIVALENT_TYPES = {
    ("TEXT", String),
    ("REAL", Float),
    ("TIMESTAMP", String),
    ("DATE", String),
    ("BOOLEAN", Boolean),
    ("INTEGER", Integer),
}


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Return False to suppress a detected type change (no-op for SQLite)."""
    for sqlite_name, sa_type in _SQLITE_EQUIVALENT_TYPES:
        if type(inspected_type).__name__.upper() == sqlite_name and isinstance(metadata_type, sa_type):
            return False
    return None  # let Alembic decide


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script output)."""
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite,
        compare_type=_compare_type if _is_sqlite else None,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live connection."""
    connect_args = {}
    if _is_sqlite:
        connect_args["check_same_thread"] = False

    connectable = create_engine(_db_url, poolclass=pool.NullPool,
                                connect_args=connect_args)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite,
            compare_type=_compare_type if _is_sqlite else None,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
