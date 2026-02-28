"""Account and balance routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import AccountBalance
from src.api.tastytrade_client import TastytradeClient
from src.database.db_manager import DatabaseManager
from src.dependencies import get_db, get_current_user_id, get_tastytrade_client

router = APIRouter()


@router.get("/api/accounts")
async def get_accounts(db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Get all available accounts"""
    try:
        accounts = db.get_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/api/debug/balances")
async def debug_balances(tastytrade: TastytradeClient = Depends(get_tastytrade_client), user_id: str = Depends(get_current_user_id)):
    """Debug endpoint to see all balance fields from Tastytrade API"""
    try:

        all_balances = []
        for account in tastytrade.accounts:
            balance = await account.get_balances(tastytrade.session)

            balance_data = {
                'account_number': account.account_number,
            }
            for field in dir(balance):
                if not field.startswith('_'):
                    try:
                        value = getattr(balance, field)
                        if not callable(value) and value is not None:
                            if hasattr(value, '__float__'):
                                balance_data[field] = float(value)
                            else:
                                balance_data[field] = str(value)
                    except:
                        pass
            all_balances.append(balance_data)

        return {"balances": all_balances}
    except Exception as e:
        logger.error(f"Debug balance error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
