"""Sync routes — unified sync, initial sync, reprocess chains, migrate P&L."""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.database.models import OrderChain
from src.dependencies import db, connection_manager, order_processor, order_manager, position_manager, lot_manager
from src.services.sync_service import (
    enrich_and_save_positions, calculate_position_opening_dates,
    reconcile_positions_vs_chains,
)
from src.services.chain_service import update_chain_cache
from src.services.ledger_service import (
    process_equity_transactions, seed_new_lots_into_groups, _reconcile_stale_groups,
)

router = APIRouter()


@router.post("/api/sync")
async def sync_unified():
    """Unified sync endpoint with smart date range calculation"""
    try:
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

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
                position_manager.clear_all_positions()
                if use_incremental and affected_underlyings:
                    lot_manager.clear_all_lots(underlyings=affected_underlyings)
                    logger.info(f"Cleared position inventory and lots for {len(affected_underlyings)} affected underlyings")
                else:
                    lot_manager.clear_all_lots()
                    logger.info("Cleared position inventory and lots for full reprocessing")

                if use_incremental and affected_underlyings:
                    all_chains = []
                    for underlying in affected_underlyings:
                        underlying_txs = db.get_raw_transactions(underlying=underlying)
                        if underlying_txs:
                            chains_by_account = order_processor.process_transactions(underlying_txs)
                            for account, chains in chains_by_account.items():
                                all_chains.extend(chains)
                    logger.info(f"Incremental reprocessing created {len(all_chains)} chains for affected underlyings")
                else:
                    raw_transactions = db.get_raw_transactions()
                    chains_by_account = order_processor.process_transactions(raw_transactions)
                    all_chains = []
                    for account, chains in chains_by_account.items():
                        all_chains.extend(chains)
                    logger.info(f"Full reprocessing created {len(all_chains)} chains")

                if all_chains:
                    logger.info("Running strategy detection on chains...")
                    try:
                        await update_chain_cache(all_chains, affected_underlyings)
                        process_equity_transactions()
                        seed_new_lots_into_groups()
                        _reconcile_stale_groups()
                        logger.info("Strategy detection and cache update completed")
                    except Exception as e:
                        logger.error(f"Error during strategy detection after sync: {str(e)}", exc_info=True)
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
async def migrate_realized_pnl():
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
async def initial_sync():
    """Complete initial sync - clears database and rebuilds from scratch"""
    try:
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        logger.info("Starting INITIAL SYNC - this will rebuild the entire database")

        db.reset_sync_metadata()
        logger.info("Skipping user data preservation (moving to order-based system)")

        logger.info("Clearing existing database and recreating tables...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS order_chain_members")
            cursor.execute("DROP TABLE IF EXISTS order_chains")
            cursor.execute("DROP TABLE IF EXISTS positions_new")
            cursor.execute("DROP TABLE IF EXISTS orders")
            cursor.execute("DELETE FROM positions")
            cursor.execute("DELETE FROM account_balances")
            cursor.execute("DELETE FROM raw_transactions")
            logger.info("Database cleared successfully")

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

        logger.info("Fetching ALL transactions (last 730 days)...")
        transactions = await tastytrade.get_transactions(days_back=730)
        logger.info(f"Fetched {len(transactions)} transactions")

        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")

        logger.info("Processing transactions into orders and chains...")

        trading_transactions = [
            tx for tx in transactions
            if tx.get('instrument_type') is not None and tx.get('symbol') is not None
        ]

        logger.info(f"Processing {len(trading_transactions)} trading transactions (filtered from {len(transactions)} total)")

        result = order_manager.process_transactions_to_orders_and_chains(trading_transactions)

        logger.info(f"Processed {result['orders_processed']} orders, saved {result['orders_saved']}, created {result['chains_created']} chains, saved {result['chains_saved']}")

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

        logger.info(f"INITIAL SYNC completed: {result['orders_saved']} orders saved, {result['chains_saved']} chains created, {total_positions} positions updated")

        db.update_last_sync_timestamp()
        db.mark_initial_sync_completed()

        logger.info("Reprocessing chains with strategy detection after initial sync...")
        try:
            raw_transactions = db.get_raw_transactions()
            position_manager.clear_all_positions()
            lot_manager.clear_all_lots()
            chains_by_account = order_processor.process_transactions(raw_transactions)
            all_chains = []
            for account, chains in chains_by_account.items():
                all_chains.extend(chains)
            await update_chain_cache(all_chains)
            process_equity_transactions()
            seed_new_lots_into_groups()
            _reconcile_stale_groups()
            logger.info(f"Chain reprocessing completed: {len(all_chains)} chains with strategy detection")
        except Exception as e:
            logger.error(f"Error during chain reprocessing: {str(e)}", exc_info=True)

        return {
            "message": f"Initial sync completed successfully",
            "orders_processed": result['orders_processed'],
            "orders_saved": result['orders_saved'],
            "chains_created": result['chains_created'],
            "chains_saved": result['chains_saved'],
            "positions_updated": total_positions,
            "transactions_processed": len(transactions),
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
        }
    except Exception as e:
        logger.error(f"Initial sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/reprocess-chains")
async def reprocess_chains():
    """Reprocess orders and chains from existing raw transactions"""
    try:
        logger.info("Starting chain reprocessing from database")

        raw_transactions = db.get_raw_transactions()
        logger.info(f"Loaded {len(raw_transactions)} raw transactions from database")

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        logger.info("Cleared position inventory and lots for reprocessing")

        chains_by_account = order_processor.process_transactions(raw_transactions)

        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)

        logger.info(f"About to update cache with {len(all_chains)} chains...")
        await update_chain_cache(all_chains)
        process_equity_transactions()
        logger.info("Cache update completed")

        seed_new_lots_into_groups()
        _reconcile_stale_groups()

        return {
            "message": "Reprocessing completed successfully",
            "orders_processed": len(raw_transactions),
            "orders_saved": len(raw_transactions),
            "chains_created": len(all_chains),
            "chains_saved": len(all_chains),
        }

    except Exception as e:
        logger.error(f"Error during reprocessing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
