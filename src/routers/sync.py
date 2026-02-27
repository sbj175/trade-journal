"""Sync routes — unified sync, initial sync, reprocess chains, migrate P&L."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger

from src.database.models import OrderChain
from src.api.tastytrade_client import TastytradeClient
from src.database.db_manager import DatabaseManager
from src.models.order_models import OrderManager
from src.models.lot_manager import LotManager
from src.dependencies import get_db, get_order_manager, get_lot_manager, get_current_user_id, get_tastytrade_client
from src.services.sync_service import (
    enrich_and_save_positions, calculate_position_opening_dates,
    reconcile_positions_vs_chains,
)
from src.services.chain_service import update_chain_cache
from src.pipeline.orchestrator import reprocess

router = APIRouter()


@router.post("/api/sync")
async def sync_unified(tastytrade: TastytradeClient = Depends(get_tastytrade_client), db: DatabaseManager = Depends(get_db), order_manager: OrderManager = Depends(get_order_manager), lot_manager: LotManager = Depends(get_lot_manager), user_id: str = Depends(get_current_user_id)):
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

        # Fetch transactions from all accounts
        logger.info("Fetching transactions from all accounts...")
        transactions = await tastytrade.get_transactions(days_back=days_back)
        logger.info(f"Fetched {len(transactions)} transactions")

        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")

        saved_count = len(transactions)

        # Fetch account balances for all accounts
        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")

        db.update_last_sync_timestamp()
        logger.info("Updated last sync timestamp")

        # Reprocess chains BEFORE saving positions
        if raw_saved > 0:
            affected_underlyings = set()
            for txn in transactions:
                underlying = txn.get('underlying_symbol', '')
                if underlying:
                    underlying = underlying.split()[0] if ' ' in underlying else underlying
                    affected_underlyings.add(underlying)

            use_incremental = raw_saved < 50 and len(affected_underlyings) <= 10

            if use_incremental:
                logger.info(f"Incremental chain reprocessing for {len(affected_underlyings)} underlyings: {affected_underlyings}")
            else:
                logger.info(f"Full chain reprocessing (raw_saved={raw_saved}, underlyings={len(affected_underlyings)})")
                affected_underlyings = None

            try:
                raw_transactions = db.get_raw_transactions()
                result = reprocess(db, lot_manager,
                                   raw_transactions, affected_underlyings)
                if result.chains:
                    await update_chain_cache(result.chains, affected_underlyings)
                    logger.info("Strategy detection and cache update completed")
                else:
                    logger.warning("No chains created during reprocessing")
            except Exception as e:
                logger.error(f"Error during chain reprocessing: {str(e)}")

        # Fetch and save positions AFTER chain reprocessing
        logger.info("Fetching current positions from all accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if positions:
                success = enrich_and_save_positions(positions, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        logger.info(f"Sync completed: {saved_count} transactions processed, {total_positions} positions updated")

        reconciliation = await reconcile_positions_vs_chains()

        return {
            "message": f"Sync completed: {saved_count} new transactions processed",
            "transactions_processed": saved_count,
            "positions_updated": total_positions,
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None,
            "reconciliation": reconciliation
        }
    except Exception as e:
        logger.error(f"Sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/migrate-realized-pnl")
async def migrate_realized_pnl(db: DatabaseManager = Depends(get_db), order_manager: OrderManager = Depends(get_order_manager), user_id: str = Depends(get_current_user_id)):
    """One-time migration to populate realized_pnl for existing chains"""
    try:
        logger.info("Starting realized P&L migration...")

        with db.get_session() as session:
            chain_ids = [row[0] for row in session.query(OrderChain.chain_id).all()]

        updated_count = 0
        for chain_id in chain_ids:
            try:
                order_manager.update_chain_pnl(chain_id)
                updated_count += 1
            except Exception as e:
                logger.error(f"Error updating chain {chain_id}: {e}")

        logger.info(f"Realized P&L migration completed: {updated_count} chains updated")

        return {
            "message": f"Migration completed successfully",
            "chains_updated": updated_count,
            "total_chains": len(chain_ids)
        }
    except Exception as e:
        logger.error(f"Error during realized P&L migration: {str(e)}")
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
            Base, OrderChainMember, OrderChainCache,
            OrderPosition, OrderChain as OrderChainModel, Position as PositionModel,
            AccountBalance, RawTransaction,
        )
        from src.database.models import Order as OrderModel
        with db.get_session() as session:
            # Clear data scoped to current user (FK order: dependents first)
            for model in [OrderChainMember, OrderChainCache, OrderChainModel, OrderPosition, OrderModel]:
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

        logger.info(f"Fetching ALL transactions (last {days_label} days)...")
        transactions = await tastytrade.get_transactions(start_date=sync_start) if sync_start else await tastytrade.get_transactions(days_back=MAX_DAYS_BACK)
        logger.info(f"Fetched {len(transactions)} transactions")

        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")

        logger.info("Fetching current positions from all accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if positions:
                positions_with_dates = calculate_position_opening_dates(positions, account_number)
                success = db.save_positions(positions_with_dates, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in balances:
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
        if pipeline_result.chains:
            await update_chain_cache(pipeline_result.chains)
        logger.info(
            f"INITIAL SYNC completed: {pipeline_result.orders_assembled} orders, "
            f"{pipeline_result.chains_derived} chains, {total_positions} positions"
        )

        return {
            "message": "Initial sync completed successfully",
            "orders_assembled": pipeline_result.orders_assembled,
            "chains_derived": pipeline_result.chains_derived,
            "groups_processed": pipeline_result.groups_processed,
            "positions_updated": total_positions,
            "transactions_processed": len(transactions),
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
        }
    except Exception as e:
        logger.error(f"Initial sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/reprocess-chains")
async def reprocess_chains(db: DatabaseManager = Depends(get_db), lot_manager: LotManager = Depends(get_lot_manager), user_id: str = Depends(get_current_user_id)):
    """Reprocess orders and chains from existing raw transactions"""
    try:
        logger.info("Starting chain reprocessing from database")

        raw_transactions = db.get_raw_transactions()
        logger.info(f"Loaded {len(raw_transactions)} raw transactions from database")

        result = reprocess(db, lot_manager, raw_transactions)

        if result.chains:
            await update_chain_cache(result.chains)
        logger.info("Reprocessing completed")

        return {
            "message": "Reprocessing completed successfully",
            "orders_processed": len(raw_transactions),
            "orders_saved": len(raw_transactions),
            "chains_created": result.chains_derived,
            "chains_saved": result.chains_derived,
        }

    except Exception as e:
        logger.error(f"Error during reprocessing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
