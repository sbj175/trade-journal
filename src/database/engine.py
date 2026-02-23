"""
SQLAlchemy engine factory and session management for OptionLedger.

Provides a module-level engine and a get_session() context manager that
commits on success and rolls back on exception.  Designed for SQLite now;
switching to PostgreSQL later means changing the URL and removing the
SQLite-specific PRAGMA listener.
"""

import logging
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


def init_engine(db_path: str) -> Engine:
    """Create (or replace) the module-level SQLAlchemy engine.

    Call once at startup — typically inside DatabaseManager.initialize_database().
    """
    global _engine, _SessionFactory

    url = f"sqlite:///{db_path}"
    _engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},  # required for FastAPI
    )

    # Enable foreign keys for every connection (SQLite-specific)
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _SessionFactory = sessionmaker(bind=_engine)
    logger.info("SQLAlchemy engine initialized for %s", db_path)
    return _engine


def get_engine() -> Engine:
    """Return the current engine (raises if init_engine hasn't been called)."""
    if _engine is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")
    return _engine


@contextmanager
def get_session():
    """Context manager yielding a SQLAlchemy Session.

    Commits on clean exit, rolls back on exception.
    """
    if _SessionFactory is None:
        raise RuntimeError("SQLAlchemy engine not initialized — call init_engine() first")

    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
