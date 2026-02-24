"""
SQLAlchemy engine factory and session management for OptionLedger.

Provides a module-level engine and a get_session() context manager that
commits on success and rolls back on exception.  Supports both SQLite and
PostgreSQL — the dialect is selected at init time based on the URL prefix.
"""

import logging
import os
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base

logger = logging.getLogger(__name__)

# Module-level state
_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None
_dialect: Optional[str] = None  # "sqlite" or "postgresql"
_insert_func = None  # dialect-specific insert(), resolved once at init


def init_engine(db_url: str = None) -> Engine:
    """Create (or replace) the module-level SQLAlchemy engine.

    Args:
        db_url: Full SQLAlchemy database URL. If None, reads DATABASE_URL
                from environment. Falls back to sqlite:///trade_journal.db.

    Call once at startup — typically inside DatabaseManager.initialize_database().
    """
    global _engine, _SessionFactory, _dialect, _insert_func

    if db_url is None:
        db_url = os.environ.get("DATABASE_URL", "sqlite:///trade_journal.db")

    _dialect = "postgresql" if db_url.startswith("postgresql") else "sqlite"

    if _dialect == "sqlite":
        _engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},  # required for FastAPI
        )

        # Enable foreign keys for every connection (SQLite-specific)
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
        _insert_func = _sqlite_insert

    else:
        _engine = create_engine(
            db_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )

        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        _insert_func = _pg_insert

    _SessionFactory = sessionmaker(bind=_engine)

    # Register multi-tenant event listeners (must happen after SessionFactory)
    from src.database.tenant import register_tenant_events
    register_tenant_events()

    logger.info("SQLAlchemy engine initialized (%s): %s", _dialect, db_url.split("@")[-1] if "@" in db_url else db_url)
    return _engine


def get_engine() -> Engine:
    """Return the current engine (raises if init_engine hasn't been called)."""
    if _engine is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")
    return _engine


def get_dialect() -> str:
    """Return the current dialect name ('sqlite' or 'postgresql')."""
    if _dialect is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")
    return _dialect


def dialect_insert(model):
    """Return a dialect-specific insert() statement for the given model.

    Equivalent to sqlite.insert(Model) or postgresql.insert(Model), resolved
    once at engine init time so there's no per-call overhead.
    """
    if _insert_func is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")
    return _insert_func(model)


@contextmanager
def get_session(user_id: str = None, unscoped: bool = False):
    """Context manager yielding a SQLAlchemy Session.

    Commits on clean exit, rolls back on exception.

    Args:
        user_id: Tenant user ID for automatic query scoping.
                 Defaults to DEFAULT_USER_ID.  Pass explicitly to override.
        unscoped: If True, skip tenant filtering entirely.  Use only for
                  cross-tenant admin operations (e.g. data claim).
    """
    if _SessionFactory is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")

    session: Session = _SessionFactory()

    if unscoped:
        # Leave user_id out of session.info — tenant filter checks for None and skips
        pass
    else:
        from src.database.tenant import DEFAULT_USER_ID, get_current_user_id_from_context

        # Priority: explicit arg > contextvar > DEFAULT_USER_ID
        if user_id is None:
            user_id = get_current_user_id_from_context()
        if user_id is None:
            user_id = DEFAULT_USER_ID

        session.info["user_id"] = user_id
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
