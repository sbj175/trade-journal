"""
Admin API endpoints — all require X-Admin-Secret header (enforced by middleware).

Every query uses get_session(unscoped=True) to bypass tenant filtering.
"""

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from src.database.engine import get_session
from src.database.models import (
    Account,
    AccountBalance,
    LotClosing,
    Order,
    OrderChain,
    OrderChainCache,
    OrderChainMember,
    OrderComment,
    OrderPosition,
    Position,
    PositionGroup,
    PositionGroupLot,
    PositionLot,
    PositionNote,
    RawTransaction,
    StrategyTarget,
    SyncMetadata,
    User,
    UserCredential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/stats")
async def stats():
    """Summary metrics for the dashboard cards."""
    with get_session(unscoped=True) as session:
        total_users = session.query(func.count(User.id)).scalar()
        active_users = (
            session.query(func.count(User.id))
            .filter(User.is_active == True)
            .scalar()
        )
        tt_connected = (
            session.query(func.count(UserCredential.id))
            .filter(UserCredential.is_active == True)
            .scalar()
        )
        total_accounts = session.query(func.count(Account.id)).scalar()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "tt_connected": tt_connected,
        "total_accounts": total_accounts,
    }


@router.get("/users")
async def list_users():
    """Detailed per-user table data."""
    with get_session(unscoped=True) as session:
        users = session.query(User).order_by(User.created_at.desc()).all()
        result = []

        for user in users:
            uid = user.id

            # Account count
            account_count = (
                session.query(func.count(Account.id))
                .filter(Account.user_id == uid)
                .scalar()
            )

            # TT connected?
            cred = (
                session.query(UserCredential)
                .filter(
                    UserCredential.user_id == uid,
                    UserCredential.is_active == True,
                )
                .first()
            )
            tt_connected = cred is not None

            # Transaction count
            txn_count = (
                session.query(func.count(RawTransaction.row_id))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )

            # Days of history: difference between earliest and latest transaction
            earliest = (
                session.query(func.min(RawTransaction.executed_at))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )
            latest = (
                session.query(func.max(RawTransaction.executed_at))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )
            if earliest and latest:
                from datetime import datetime

                try:
                    fmt = "%Y-%m-%dT%H:%M:%S" if "T" in earliest else "%Y-%m-%d %H:%M:%S"
                    d1 = datetime.strptime(earliest[:19], fmt)
                    d2 = datetime.strptime(latest[:19], fmt)
                    days_of_history = (d2 - d1).days
                except (ValueError, TypeError):
                    days_of_history = None
            else:
                days_of_history = None

            # Last sync
            last_sync_row = (
                session.query(SyncMetadata)
                .filter(
                    SyncMetadata.user_id == uid,
                    SyncMetadata.key == "last_sync_timestamp",
                )
                .first()
            )
            last_sync = last_sync_row.value if last_sync_row else None

            # Position count
            position_count = (
                session.query(func.count(Position.id))
                .filter(Position.user_id == uid)
                .scalar()
            )

            result.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "last_login_at": user.updated_at,
                    "accounts": account_count,
                    "tt_connected": tt_connected,
                    "txn_count": txn_count,
                    "days_of_history": days_of_history,
                    "last_sync": last_sync,
                    "positions": position_count,
                }
            )

        return result


@router.post("/users/{user_id}/reset-sync")
async def reset_sync(user_id: str):
    """Delete all SyncMetadata rows for a user, forcing a full re-sync."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        deleted = (
            session.query(SyncMetadata)
            .filter(SyncMetadata.user_id == user_id)
            .delete()
        )
        logger.info("Reset sync for user %s: deleted %d metadata rows", user_id, deleted)

    return {"status": "ok", "deleted_rows": deleted}


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str):
    """Set User.is_active=False and UserCredential.is_active=False."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_active = False

        session.query(UserCredential).filter(
            UserCredential.user_id == user_id
        ).update({"is_active": False})

        logger.info("Deactivated user %s (%s)", user_id, user.email)

    return {"status": "ok"}


@router.post("/users/{user_id}/activate")
async def activate_user(user_id: str):
    """Set User.is_active=True."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_active = True
        logger.info("Activated user %s (%s)", user_id, user.email)

    return {"status": "ok"}


# Tables containing user trading data (order matters for FK constraints)
_USER_DATA_TABLES = [
    LotClosing,
    PositionGroupLot,
    PositionGroup,
    PositionLot,
    OrderChainCache,
    OrderChainMember,
    OrderChain,
    OrderPosition,
    OrderComment,
    Order,
    PositionNote,
    Position,
    AccountBalance,
    RawTransaction,
    SyncMetadata,
    StrategyTarget,
    Account,
    UserCredential,
]


@router.delete("/users/{user_id}/data")
async def delete_user_data(user_id: str):
    """Hard-delete all trading data for a user (keeps the User row)."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        totals = {}
        for model in _USER_DATA_TABLES:
            count = (
                session.query(model)
                .filter(model.user_id == user_id)
                .delete()
            )
            if count > 0:
                totals[model.__tablename__] = count

        logger.info(
            "Deleted all data for user %s (%s): %s",
            user_id,
            user.email,
            totals,
        )

    return {"status": "ok", "deleted": totals}
