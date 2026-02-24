"""Auth routes — config endpoint, data claim, connection status."""

import os
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update

from src.database.models import (
    Account, AccountBalance, Position, Order, OrderPosition,
    OrderChain, OrderChainMember, OrderChainCache,
    RawTransaction, SyncMetadata, StrategyTarget,
    PositionLot, LotClosing, PositionGroup, PositionGroupLot,
    PositionsInventory, OrderComment, PositionNote,
)
from src.database.tenant import DEFAULT_USER_ID
from src.dependencies import db, get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()

# All 18 tenant-scoped tables
_TENANT_TABLES = [
    Account, AccountBalance, Position, Order, OrderPosition,
    OrderChain, OrderChainMember, OrderChainCache,
    RawTransaction, SyncMetadata, StrategyTarget,
    PositionLot, LotClosing, PositionGroup, PositionGroupLot,
    PositionsInventory, OrderComment, PositionNote,
]


@router.get("/api/auth/config")
async def get_auth_config():
    """Return public Supabase config for the frontend (no secrets).

    This endpoint is public — no auth required.
    """
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    auth_enabled = bool(supabase_url or os.getenv("SUPABASE_JWT_SECRET"))

    return {
        "auth_enabled": auth_enabled,
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_anon_key,
    }


@router.post("/api/auth/claim-data")
async def claim_data(user_id: str = Depends(get_current_user_id)):
    """Migrate DEFAULT_USER_ID data to the authenticated user.

    This is a one-time operation for the first real user who logs in.
    Only works if no other real user has already claimed the data.
    """
    if user_id == DEFAULT_USER_ID:
        raise HTTPException(400, "Cannot claim data as default user")

    from src.database.engine import get_session

    with get_session(user_id=None) as session:
        # Check if any real user (not default) already has data
        existing = session.query(Account.account_number).filter(
            Account.user_id != DEFAULT_USER_ID,
            Account.user_id.isnot(None),
        ).first()
        if existing:
            raise HTTPException(409, "Data has already been claimed by another user")

        # Check there's actually data to claim
        default_data = session.query(Account.account_number).filter(
            Account.user_id == DEFAULT_USER_ID,
        ).first()
        if not default_data:
            raise HTTPException(404, "No data to claim")

        # Update all 18 tenant-scoped tables
        claimed_count = 0
        for model in _TENANT_TABLES:
            result = session.execute(
                update(model)
                .where(model.user_id == DEFAULT_USER_ID)
                .values(user_id=user_id)
            )
            claimed_count += result.rowcount

        logger.info(
            "User %s claimed %d rows from DEFAULT_USER_ID",
            user_id, claimed_count,
        )

    return {
        "message": f"Successfully claimed {claimed_count} data rows",
        "rows_claimed": claimed_count,
    }


@router.get("/api/auth/check-claimable")
async def check_claimable_data(user_id: str = Depends(get_current_user_id)):
    """Check if there's DEFAULT_USER_ID data that can be claimed."""
    if user_id == DEFAULT_USER_ID:
        return {"claimable": False}

    from src.database.engine import get_session

    with get_session(user_id=None) as session:
        # Check user has no accounts of their own
        user_accounts = session.query(Account.account_number).filter(
            Account.user_id == user_id,
        ).first()
        if user_accounts:
            return {"claimable": False}

        # Check if any other real user already claimed
        other_claimed = session.query(Account.account_number).filter(
            Account.user_id != DEFAULT_USER_ID,
            Account.user_id.isnot(None),
        ).first()
        if other_claimed:
            return {"claimable": False}

        # Check if default user has data
        default_data = session.query(Account.account_number).filter(
            Account.user_id == DEFAULT_USER_ID,
        ).first()

        return {"claimable": default_data is not None}
