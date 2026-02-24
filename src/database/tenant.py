"""
Multi-tenant scoping for OptionLedger.

Provides automatic user_id filtering on all ORM queries and auto-assignment
of user_id on new ORM objects via SQLAlchemy session events.

Usage:
    call register_tenant_events() once after creating the SessionFactory
    (typically inside init_engine()).  Then every get_session(user_id=...)
    stores the user_id in session.info['user_id'], and the event listeners
    transparently scope all ORM operations to that user.

dialect_insert() calls bypass ORM events — those call sites must include
user_id in their .values() explicitly.
"""

import logging
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Well-known UUID for the default user (used when auth is disabled).
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# ContextVar for per-request user_id (set by auth middleware/dependency).
_current_user_id: ContextVar[str | None] = ContextVar("_current_user_id", default=None)


def set_current_user_id(uid: str) -> None:
    """Set the user_id for the current async/thread context."""
    _current_user_id.set(uid)


def get_current_user_id_from_context() -> str | None:
    """Get the user_id from the current context, or None if not set."""
    return _current_user_id.get()

# Models that are global (not tenant-scoped).  These are checked by table name
# so we don't need to import the model classes here.
_GLOBAL_TABLES = frozenset({"quote_cache", "users"})


def _is_tenant_scoped(mapper):
    """Return True if the mapped class has a user_id column."""
    return (
        mapper is not None
        and hasattr(mapper.columns, "user_id")
        and mapper.persist_selectable.name not in _GLOBAL_TABLES
    )


def register_tenant_events():
    """Attach do_orm_execute and before_flush listeners to the Session class."""

    @event.listens_for(Session, "do_orm_execute")
    def _inject_tenant_filter(orm_execute_state):
        """For SELECT statements on tenant-scoped models, append WHERE user_id = ?."""
        if not orm_execute_state.is_select:
            return

        user_id = orm_execute_state.session.info.get("user_id")
        if user_id is None:
            return  # unscoped session (migrations, admin scripts)

        # Build filter options for each mapped entity in the statement
        # Using the "with_loader_criteria" approach for tenant filtering
        for mapper in orm_execute_state.all_mappers:
            if _is_tenant_scoped(mapper):
                entity = mapper.entity
                orm_execute_state.statement = orm_execute_state.statement.filter(
                    entity.user_id == user_id
                )

    @event.listens_for(Session, "before_flush")
    def _auto_set_user_id(session, flush_context, instances):
        """Auto-set user_id on new objects that have the column but it's None."""
        user_id = session.info.get("user_id")
        if user_id is None:
            return

        for obj in session.new:
            if hasattr(obj, "user_id") and obj.user_id is None:
                obj.user_id = user_id

    logger.debug("Tenant scoping event listeners registered")
