"""Account and balance routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.dependencies import db, connection_manager

router = APIRouter()


@router.get("/api/accounts")
async def get_accounts():
    """Get all available accounts"""
    try:
        accounts = db.get_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/account-balances")
async def get_account_balances(account_number: Optional[str] = None):
    """Get account balances for specified account or all accounts"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            if account_number:
                query = """
                    SELECT * FROM account_balances
                    WHERE account_number = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """
                cursor.execute(query, (account_number,))
            else:
                query = """
                    SELECT * FROM account_balances
                    WHERE timestamp = (
                        SELECT MAX(timestamp)
                        FROM account_balances ab2
                        WHERE ab2.account_number = account_balances.account_number
                    )
                    ORDER BY account_number
                """
                cursor.execute(query)

            columns = [desc[0] for desc in cursor.description]
            balances = []
            for row in cursor.fetchall():
                balance = dict(zip(columns, row))
                balances.append(balance)

            return {"balances": balances}
    except Exception as e:
        logger.error(f"Error getting account balances: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/debug/balances")
async def debug_balances():
    """Debug endpoint to see all balance fields from Tastytrade API"""
    try:
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

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
