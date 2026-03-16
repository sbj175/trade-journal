"""Sync routes — unified sync, initial sync, migrate P&L, reconciliation."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger

from src.api.tastytrade_client import TastytradeClient
from src.database.db_manager import DatabaseManager
from src.models.lot_manager import LotManager
from src.dependencies import get_db, get_lot_manager, get_current_user_id, get_tastytrade_client
from src.services.sync_service import (
    enrich_and_save_positions, calculate_position_opening_dates,
    reconcile_positions_vs_chains,
)
from src.pipeline.orchestrator import reprocess

router = APIRouter()


@router.post("/api/sync")
async def sync_unified(tastytrade: TastytradeClient = Depends(get_tastytrade_client), db: DatabaseManager = Depends(get_db), lot_manager: LotManager = Depends(get_lot_manager), user_id: str = Depends(get_current_user_id)):
    """Unified sync endpoint with smart date range calculation"""
    try:

        logger.info("Sync requested")

        last_sync = db.get_last_sync_timestamp()

        if last_sync:
            days_back = (datetime.now() - last_sync).days + 1
            days_back = max(days_back, 1)
            days_back = min(days_back, 90)
            logger.info(f"Incremental sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
        else:
            days_back = 365
            logger.info(f"First sync detected, fetching {days_back} days")

        # Save all accounts to database
        logger.info("Saving account information...")
        accounts = tastytrade.get_all_accounts()
        for account in accounts:
            db.save_account(
                account['account_number'],
                account['account_name'],
                account['account_type']
            )
        logger.info(f"Saved {len(accounts)} accounts")

        # Get active account numbers for filtering
        active_accounts = {a['account_number'] for a in db.get_accounts()}
        logger.info(f"Active accounts for sync: {active_accounts}")

        # Fetch transactions from active accounts
        logger.info("Fetching transactions from active accounts...")
        transactions = await tastytrade.get_transactions(days_back=days_back)
        transactions = [t for t in transactions if t.get('account_number') in active_accounts]
        logger.info(f"Fetched {len(transactions)} transactions")

        logger.info("Saving raw transactions...")
        raw_saved, new_symbols = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")

        # Fetch account balances for active accounts
        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in [b for b in balances if b.get('account_number') in active_accounts]:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")

        db.update_last_sync_timestamp()
        logger.info("Updated last sync timestamp")

        # Reprocess pipeline BEFORE saving positions
        if raw_saved > 0:
            affected_underlyings = set()
            for txn in transactions:
                underlying = txn.get('underlying_symbol', '')
                if underlying:
                    underlying = underlying.split()[0] if ' ' in underlying else underlying
                    affected_underlyings.add(underlying)

            use_incremental = raw_saved < 50 and len(affected_underlyings) <= 10

            if use_incremental:
                logger.info(f"Incremental reprocessing for {len(affected_underlyings)} underlyings: {affected_underlyings}")
            else:
                logger.info(f"Full reprocessing (raw_saved={raw_saved}, underlyings={len(affected_underlyings)})")
                affected_underlyings = None

            try:
                raw_transactions = db.get_raw_transactions()
                result = reprocess(db, lot_manager,
                                   raw_transactions, affected_underlyings)
                logger.info(
                    f"Pipeline completed: {result.orders_assembled} orders, "
                    f"{result.groups_processed} groups"
                )
            except Exception as e:
                logger.error(f"Error during reprocessing: {str(e)}")

        # Fetch and save positions AFTER reprocessing (active accounts only)
        logger.info("Fetching current positions from active accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if account_number not in active_accounts:
                continue
            if positions:
                success = enrich_and_save_positions(positions, account_number, db=db)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        logger.info(f"Sync completed: {len(transactions)} transactions processed, {total_positions} positions updated")

        reconciliation = await reconcile_positions_vs_chains(db=db)

        return {
            "message": f"Sync completed: {raw_saved} new transactions processed",
            "transactions_processed": len(transactions),
            "new_transactions": raw_saved,
            "symbols": sorted(new_symbols),
            "positions_updated": total_positions,
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None,
            "reconciliation": reconciliation
        }
    except Exception as e:
        logger.error(f"Sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/reprocess")
async def reprocess_pipeline(
    db: DatabaseManager = Depends(get_db),
    lot_manager: LotManager = Depends(get_lot_manager),
    user_id: str = Depends(get_current_user_id),
):
    """Re-run the full processing pipeline on existing raw transactions.

    Does NOT fetch from Tastytrade — just reprocesses what's already in the DB.
    Useful for applying code changes to existing data.
    """
    try:
        raw_transactions = db.get_raw_transactions()
        if not raw_transactions:
            return {"message": "No raw transactions to process", "groups_processed": 0}

        logger.info(f"Reprocessing {len(raw_transactions)} raw transactions (full pipeline)")
        result = reprocess(db, lot_manager, raw_transactions)

        logger.info(
            f"Reprocess completed: {result.orders_assembled} orders, "
            f"{result.groups_processed} groups"
        )

        return {
            "message": "Reprocess completed",
            "orders_assembled": result.orders_assembled,
            "groups_processed": result.groups_processed,
            "equity_lots_netted": result.equity_lots_netted,
        }
    except Exception as e:
        logger.error(f"Error during reprocess: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sync/initial")
async def initial_sync(
    tastytrade: TastytradeClient = Depends(get_tastytrade_client),
    db: DatabaseManager = Depends(get_db),
    lot_manager: LotManager = Depends(get_lot_manager),
    user_id: str = Depends(get_current_user_id),
    start_date: Optional[str] = Body(None, embed=True),
):
    """Complete initial sync - clears database and rebuilds from scratch.

    Accepts an optional start_date (YYYY-MM-DD) to control how far back to
    import.  Capped at 730 days (2 years).  Defaults to 730 days if omitted.
    """
    from datetime import datetime as _dt

    MAX_DAYS_BACK = 730
    sync_start = None
    if start_date:
        try:
            parsed = date.fromisoformat(start_date)
            # Clamp: no earlier than MAX_DAYS_BACK ago, no later than today
            earliest = date.today() - timedelta(days=MAX_DAYS_BACK)
            if parsed < earliest:
                parsed = earliest
            if parsed > date.today():
                parsed = date.today()
            sync_start = _dt.combine(parsed, _dt.min.time())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_date format: {start_date}")

    days_label = (date.today() - sync_start.date()).days if sync_start else MAX_DAYS_BACK

    try:

        logger.info(f"Starting INITIAL SYNC - importing {days_label} days of history")

        db.reset_sync_metadata()
        logger.info("Skipping user data preservation (moving to order-based system)")

        logger.info("Clearing existing database and recreating tables...")
        from src.database.models import (
            Base, OrderChainCache,
            OrderChain as OrderChainModel, Position as PositionModel,
            AccountBalance, RawTransaction,
        )
        with db.get_session() as session:
            # Clear data scoped to current user (FK order: dependents first)
            for model in [OrderChainCache, OrderChainModel]:
                session.query(model).filter(model.user_id == user_id).delete()
            session.query(PositionModel).filter(PositionModel.user_id == user_id).delete()
            session.query(AccountBalance).filter(AccountBalance.user_id == user_id).delete()
            session.query(RawTransaction).filter(RawTransaction.user_id == user_id).delete()
            logger.info("Database cleared successfully (user-scoped)")

        db.initialize_database()

        logger.info("Saving account information...")
        accounts = tastytrade.get_all_accounts()
        for account in accounts:
            db.save_account(
                account['account_number'],
                account['account_name'],
                account['account_type']
            )
        logger.info(f"Saved {len(accounts)} accounts")

        # Get active account numbers for filtering
        active_accounts = {a['account_number'] for a in db.get_accounts()}
        logger.info(f"Active accounts for initial sync: {active_accounts}")

        logger.info(f"Fetching transactions (last {days_label} days) for active accounts...")
        transactions = await tastytrade.get_transactions(start_date=sync_start) if sync_start else await tastytrade.get_transactions(days_back=MAX_DAYS_BACK)
        transactions = [t for t in transactions if t.get('account_number') in active_accounts]
        logger.info(f"Fetched {len(transactions)} transactions (filtered to active accounts)")

        logger.info("Saving raw transactions...")
        raw_saved, _ = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")

        logger.info("Fetching current positions from active accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if account_number not in active_accounts:
                continue
            if positions:
                positions_with_dates = calculate_position_opening_dates(positions, account_number, db=db)
                success = db.save_positions(positions_with_dates, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in [b for b in balances if b.get('account_number') in active_accounts]:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")

        db.update_last_sync_timestamp()
        db.mark_initial_sync_completed()

        logger.info("Running full pipeline on initial sync data...")
        raw_transactions = db.get_raw_transactions()
        pipeline_result = reprocess(db, lot_manager, raw_transactions)
        logger.info(
            f"INITIAL SYNC completed: {pipeline_result.orders_assembled} orders, "
            f"{pipeline_result.groups_processed} groups, {total_positions} positions"
        )

        return {
            "message": "Initial sync completed successfully",
            "orders_assembled": pipeline_result.orders_assembled,
            "groups_processed": pipeline_result.groups_processed,
            "positions_updated": total_positions,
            "transactions_processed": len(transactions),
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
        }
    except Exception as e:
        logger.error(f"Initial sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sync/account/{account_number}")
async def sync_account(
    account_number: str,
    tastytrade: TastytradeClient = Depends(get_tastytrade_client),
    db: DatabaseManager = Depends(get_db),
    lot_manager: LotManager = Depends(get_lot_manager),
    user_id: str = Depends(get_current_user_id),
):
    """Import a single account's full transaction history without clearing other accounts.

    Used when enabling a previously disabled account — fetches its historical
    data and merges it into the existing dataset.
    """
    try:
        MAX_DAYS_BACK = 730

        logger.info(f"Account-scoped sync for {account_number} ({MAX_DAYS_BACK} days)")

        # Fetch transactions for this account only
        transactions = await tastytrade.get_transactions(
            days_back=MAX_DAYS_BACK, account_number=account_number,
        )
        logger.info(f"Fetched {len(transactions)} transactions for account {account_number}")

        raw_saved, new_symbols = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} new transactions")

        # Fetch balances for this account
        balances = await tastytrade.get_account_balances()
        for balance in (balances or []):
            if balance.get('account_number') == account_number:
                db.save_account_balance(balance)

        # Run account-scoped pipeline
        if raw_saved > 0:
            raw_transactions = db.get_raw_transactions()
            result = reprocess(db, lot_manager, raw_transactions, account_number=account_number)
            logger.info(
                f"Account pipeline completed: {result.orders_assembled} orders, "
                f"{result.groups_processed} groups"
            )
        else:
            result = None

        # Fetch and save positions for this account
        all_positions = await tastytrade.get_positions(account_number=account_number)
        total_positions = 0
        for acct, positions in all_positions.items():
            if positions:
                enrich_and_save_positions(positions, acct, db=db)
                total_positions += len(positions)

        return {
            "message": f"Imported {raw_saved} transactions for account {account_number}",
            "new_transactions": raw_saved,
            "symbols": sorted(new_symbols),
            "positions_updated": total_positions,
            "orders_assembled": result.orders_assembled if result else 0,
            "groups_processed": result.groups_processed if result else 0,
        }
    except Exception as e:
        logger.error(f"Account sync error for {account_number}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/reconcile")
async def get_reconciliation(db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Run position reconciliation and return results."""
    return await reconcile_positions_vs_chains(db=db)
