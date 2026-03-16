"""Account and balance routes."""

from typing import Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import Account, AccountBalance
from src.database.db_manager import DatabaseManager
from src.dependencies import get_db, get_current_user_id

router = APIRouter()


@router.get("/api/accounts")
async def get_accounts(db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Get all available accounts (active only)"""
    try:
        accounts = db.get_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/settings/accounts")
async def get_all_accounts(db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Get all accounts including inactive ones (for Settings page)."""
    with db.get_session() as session:
        rows = session.query(Account).order_by(Account.account_number).all()
        return {"accounts": [row.to_dict() for row in rows]}


@router.post("/api/settings/accounts")
async def update_account_active(
    updates: List[Dict] = Body(...),
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Toggle is_active for one or more accounts.

    Body: [{"account_number": "5WZ28644", "is_active": true}, ...]
    Requires at least one account to remain active.
    """
    with db.get_session() as session:
        all_accounts = session.query(Account).all()
        acct_map = {a.account_number: a for a in all_accounts}

        # Apply updates
        for u in updates:
            acct = acct_map.get(u.get("account_number"))
            if acct:
                acct.is_active = u.get("is_active", True)

        # Validate: at least one account must remain active
        if not any(a.is_active for a in all_accounts):
            session.rollback()
            raise HTTPException(status_code=400, detail="At least one account must remain active")

        session.commit()
        return {"accounts": [a.to_dict() for a in all_accounts]}


@router.delete("/api/settings/accounts/{account_number}/data")
async def delete_account_data(
    account_number: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Delete all local data for a specific account (transactions, lots, groups, positions).

    Does NOT delete the account record itself or affect the brokerage account.
    """
    from src.database.models import (
        RawTransaction, PositionLot, LotClosing, PositionGroup,
        PositionGroupLot, PositionGroupTag, PositionNote,
        Position, PnlEvent, RollChainSummary,
    )

    with db.get_session() as session:
        # Get lot IDs for this account to delete closings
        lot_ids = [
            r[0] for r in session.query(PositionLot.id).filter(
                PositionLot.account_number == account_number,
            ).all()
        ]

        # Get group IDs for this account
        group_ids = [
            r[0] for r in session.query(PositionGroup.group_id).filter(
                PositionGroup.account_number == account_number,
            ).all()
        ]

        # Delete in FK order
        if lot_ids:
            session.query(LotClosing).filter(LotClosing.lot_id.in_(lot_ids)).delete(synchronize_session=False)
        if group_ids:
            session.query(PnlEvent).filter(PnlEvent.group_id.in_(group_ids)).delete(synchronize_session=False)
            session.query(RollChainSummary).filter(RollChainSummary.current_group_id.in_(group_ids)).delete(synchronize_session=False)
            session.query(PositionGroupTag).filter(PositionGroupTag.group_id.in_(group_ids)).delete(synchronize_session=False)
            session.query(PositionNote).filter(
                PositionNote.note_key.in_([f"group_{gid}" for gid in group_ids]),
            ).delete(synchronize_session=False)
            session.query(PositionGroupLot).filter(PositionGroupLot.group_id.in_(group_ids)).delete(synchronize_session=False)
            session.query(PositionGroup).filter(PositionGroup.group_id.in_(group_ids)).delete(synchronize_session=False)

        session.query(PositionLot).filter(PositionLot.account_number == account_number).delete(synchronize_session=False)
        session.query(Position).filter(Position.account_number == account_number).delete(synchronize_session=False)
        session.query(RawTransaction).filter(RawTransaction.account_number == account_number).delete(synchronize_session=False)

        deleted_txns = session.query(RawTransaction).filter(RawTransaction.account_number == account_number).count()
        session.commit()

        logger.info(f"Deleted all data for account {account_number}: {len(lot_ids)} lots, {len(group_ids)} groups")
        return {"message": f"Data deleted for account {account_number}"}


@router.get("/api/account-balances")
async def get_account_balances(account_number: Optional[str] = None, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Get account balances for specified account or all accounts"""
    try:
        with db.get_session() as session:
            if account_number:
                rows = session.query(AccountBalance).filter(
                    AccountBalance.account_number == account_number,
                    AccountBalance.user_id == user_id,
                ).order_by(AccountBalance.timestamp.desc()).limit(1).all()
            else:
                # Subquery for latest timestamp per account.
                # Must explicitly filter by user_id — ORM tenant filter
                # does NOT apply inside .subquery().
                latest = session.query(
                    AccountBalance.account_number,
                    func.max(AccountBalance.timestamp).label("max_ts"),
                ).filter(
                    AccountBalance.user_id == user_id,
                ).group_by(AccountBalance.account_number).subquery()

                rows = session.query(AccountBalance).join(
                    latest,
                    (AccountBalance.account_number == latest.c.account_number)
                    & (AccountBalance.timestamp == latest.c.max_ts),
                ).order_by(AccountBalance.account_number).all()

            balances = [row.to_dict() for row in rows]
            return {"balances": balances}
    except Exception as e:
        logger.error(f"Error getting account balances: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
