"""Sync service — position enrichment, background sync, reconciliation."""

from datetime import datetime, date as _date
from typing import Dict, List, Any, Optional

from loguru import logger
from sqlalchemy import func

from src.database.models import (
    RawTransaction, OrderChain, OrderChainCache,
    PositionLot as PositionLotModel, PositionGroupLot, PositionGroup,
)
from src.dependencies import db, connection_manager, lot_manager, order_manager, AUTH_ENABLED
from src.services import chain_service, ledger_service


def calculate_position_opening_dates(positions: List[Dict[str, Any]], account_number: str) -> List[Dict[str, Any]]:
    """Calculate opening dates for positions based on transaction history - HIGHLY OPTIMIZED"""

    if not positions:
        return positions

    # Single optimized query to get all opening dates for this account's symbols
    position_symbols = [pos['symbol'] for pos in positions]
    opening_dates = {}

    if position_symbols:
        with db.get_session() as session:
            rows = session.query(
                RawTransaction.symbol,
                func.min(RawTransaction.executed_at).label('earliest_date'),
            ).filter(
                RawTransaction.account_number == account_number,
                RawTransaction.symbol.in_(position_symbols),
                RawTransaction.action.in_([
                    'OrderAction.BUY_TO_OPEN', 'OrderAction.SELL_TO_OPEN',
                ]),
            ).group_by(RawTransaction.symbol).all()

            for row in rows:
                opening_dates[row[0]] = row[1]

    # Apply opening dates to positions
    for position in positions:
        symbol = position.get('symbol')
        position['opened_at'] = opening_dates.get(symbol)

    return positions


def enrich_and_save_positions(positions: List[Dict[str, Any]], account_number: str) -> bool:
    """Enrich positions with chain metadata and save to database.

    This runs at sync-time so chain_id and strategy_type are persisted,
    eliminating the need for runtime enrichment on every API call.
    """
    if not positions:
        return True

    # Calculate opening dates
    positions_with_dates = calculate_position_opening_dates(positions, account_number)

    # Get open chains for this account
    open_chains = []
    try:
        with db.get_session() as session:
            rows = session.query(OrderChain).filter(
                OrderChain.chain_status == 'OPEN',
                OrderChain.account_number == account_number,
            ).all()
            for row in rows:
                open_chains.append({
                    'chain_id': row.chain_id,
                    'underlying': row.underlying,
                    'account_number': row.account_number,
                    'strategy_type': row.strategy_type,
                    'chain_status': row.chain_status,
                })
    except Exception as e:
        logger.warning(f"Could not fetch chains for position enrichment: {e}")

    # Build symbol → chain lookup from order_chain_cache (the authoritative source)
    symbol_to_chain = {}
    if open_chains:
        try:
            import json as _json
            chain_ids = [c['chain_id'] for c in open_chains]
            chain_map = {c['chain_id']: c for c in open_chains}
            with db.get_session() as session:
                rows = session.query(
                    OrderChainCache.chain_id, OrderChainCache.order_data,
                ).filter(
                    OrderChainCache.chain_id.in_(chain_ids),
                ).all()
                for row in rows:
                    cid = row[0]
                    try:
                        order_data = _json.loads(row[1])
                        for pos in order_data.get('positions', []):
                            sym = pos.get('symbol', '').strip()
                            if sym and sym not in symbol_to_chain:
                                chain_info = chain_map.get(cid, {})
                                symbol_to_chain[sym] = {
                                    'chain_id': cid,
                                    'strategy_type': chain_info.get('strategy_type', 'Unknown')
                                }
                    except Exception:
                        pass
                # Also add underlying-level fallback entries
                for chain in open_chains:
                    underlying = chain.get('underlying', '').strip()
                    if underlying and underlying not in symbol_to_chain:
                        symbol_to_chain[underlying] = {
                            'chain_id': chain['chain_id'],
                            'strategy_type': chain.get('strategy_type', 'Unknown')
                        }
            logger.info(f"Built symbol lookup with {len(symbol_to_chain)} entries from {len(open_chains)} open chains")
        except Exception as e:
            logger.warning(f"Could not build symbol lookup for enrichment: {e}")

    # Enrich each position with chain metadata
    enriched_count = 0
    for pos in positions_with_dates:
        symbol = pos.get('symbol', '').strip()
        underlying = pos.get('underlying_symbol', '') or pos.get('underlying', '')
        underlying = underlying.strip() if underlying else ''

        match = symbol_to_chain.get(symbol) or symbol_to_chain.get(underlying)
        if match:
            pos['chain_id'] = match['chain_id']
            pos['strategy_type'] = match['strategy_type']
            enriched_count += 1

    logger.info(f"Enriched {enriched_count}/{len(positions_with_dates)} positions with chain_id for account {account_number}")

    # One-time note key migration: move pos_* notes to chain_* keys
    try:
        all_notes = db.get_all_position_notes()
        pos_notes = {k: v for k, v in all_notes.items() if k.startswith('pos_')}
        if pos_notes:
            for pos in positions_with_dates:
                chain_id = pos.get('chain_id')
                if not chain_id:
                    continue
                chain_key = f"chain_{chain_id}"
                if chain_key in all_notes:
                    continue  # chain note already exists
                underlying = pos.get('underlying_symbol', '')
                account = account_number
                # Search for matching pos_* note
                for pk, pv in pos_notes.items():
                    if pk.startswith(f'pos_{underlying}_') and pk.endswith(f'_{account}'):
                        db.save_position_note(chain_key, pv)
                        db.save_position_note(pk, '')  # delete old key
                        logger.info(f"Migrated note '{pk}' -> '{chain_key}'")
                        break
    except Exception as e:
        logger.warning(f"Note migration error (non-fatal): {e}")

    return db.save_positions(positions_with_dates, account_number)


async def sync_unified_internal(user_id: str = None):
    """Internal sync function that can be called without HTTP context.

    When *user_id* is provided and AUTH_ENABLED, uses the per-user client.
    Otherwise falls back to the global singleton.
    """
    if AUTH_ENABLED and user_id:
        tastytrade = await connection_manager.get_user_client(user_id)
    else:
        tastytrade = connection_manager.get_client()
    if not tastytrade:
        logger.error("Auto-sync: Not connected to Tastytrade")
        return

    # Check last sync timestamp to determine date range
    last_sync = db.get_last_sync_timestamp()

    if last_sync:
        # Calculate days back from last sync + 1 day buffer
        days_back = (datetime.now() - last_sync).days + 1
        days_back = max(days_back, 1)  # Minimum 1 day
        days_back = min(days_back, 90)  # Maximum 90 days for safety
        logger.info(f"Auto-sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
    else:
        # No previous sync, fetch last 365 days for auto-sync
        days_back = 365
        logger.info(f"Auto-sync: first sync detected, fetching {days_back} days")

    # Save all accounts to database
    logger.info("Auto-sync: Saving account information...")
    accounts = tastytrade.get_all_accounts()
    for account in accounts:
        db.save_account(
            account['account_number'],
            account['account_name'],
            account['account_type']
        )
    logger.info(f"Auto-sync: Saved {len(accounts)} accounts")

    # Fetch and save current positions for all accounts (with chain enrichment)
    logger.info("Auto-sync: Fetching current positions from all accounts...")
    all_positions = await tastytrade.get_positions()
    total_positions = 0

    for account_number, positions in all_positions.items():
        if positions:
            success = enrich_and_save_positions(positions, account_number)
            if success:
                logger.info(f"Auto-sync: Successfully saved {len(positions)} positions for account {account_number}")
                total_positions += len(positions)
            else:
                logger.error(f"Auto-sync: Failed to save positions for account {account_number}")

    # Update last sync timestamp
    db.update_last_sync_timestamp()
    logger.info(f"Auto-sync completed: {total_positions} positions updated")


async def background_auto_sync():
    """Background task for automatic sync"""
    try:
        logger.info("Starting background auto-sync...")
        await sync_unified_internal()
        logger.info("Background auto-sync completed successfully")
    except Exception as e:
        logger.error(f"Background auto-sync failed: {e}")


async def background_incremental_sync(user_id: str = None):
    """Background task to perform incremental sync when unmatched positions are detected."""
    try:
        logger.info("Starting background incremental sync...")

        last_sync = db.get_last_sync_timestamp()

        if last_sync:
            days_back = (datetime.now() - last_sync).days + 1
            days_back = max(days_back, 1)
            days_back = min(days_back, 90)
            logger.info(f"Background sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
        else:
            days_back = 365
            logger.info(f"Background sync: no previous sync, fetching {days_back} days")

        if AUTH_ENABLED and user_id:
            tastytrade = await connection_manager.get_user_client(user_id)
        else:
            tastytrade = connection_manager.get_client()
        if not tastytrade:
            logger.warning("Background sync: not connected to Tastytrade, skipping")
            return

        try:
            transactions = await tastytrade.get_transactions(days_back=days_back)
            logger.info(f"Background sync: fetched {len(transactions)} transactions")

            raw_saved = db.save_raw_transactions(transactions)
            logger.info(f"Background sync: saved {raw_saved} raw transactions")

            all_positions = await tastytrade.get_positions()
            total_positions = 0

            for account_number, positions in all_positions.items():
                if positions:
                    success = enrich_and_save_positions(positions, account_number)
                    if success:
                        total_positions += len(positions)

            logger.info(f"Background sync: saved {total_positions} positions")

            from src.pipeline.orchestrator import reprocess
            raw_transactions = db.get_raw_transactions()
            result = reprocess(db, lot_manager, raw_transactions)
            logger.info(f"Background sync: reprocessed {result.chains_derived} chains")

            db.update_last_sync_timestamp()
            logger.info("Background sync: completed successfully")

        except Exception as e:
            logger.error(f"Background sync: error during processing: {e}")
            return

    except Exception as e:
        logger.error(f"Background incremental sync failed: {e}")


async def reconcile_positions_vs_chains():
    """Compare TT API positions against position_lots-derived open legs.

    Returns a summary with categories:
    - MATCHED: symbol+account+quantity agree
    - QUANTITY_MISMATCH: same symbol but different quantity
    - UNLINKED: TT has position, lots don't
    - STALE: lots say open but TT doesn't have it (auto-closes stale lots and groups)
    """
    try:
        # 1. Get TT API positions (from positions table)
        tt_positions = db.get_open_positions()
        tt_by_key = {}
        for pos in tt_positions:
            key = (pos.get('account_number', ''), (pos.get('symbol') or '').strip())
            tt_by_key[key] = pos

        # 2. Get open legs from position_lots — options and equity (single query)
        lot_legs_by_key = {}
        with db.get_session() as session:
            rows = session.query(
                PositionLotModel.account_number,
                PositionLotModel.symbol,
                func.max(PositionLotModel.underlying).label('underlying'),
                func.sum(PositionLotModel.remaining_quantity).label('net_qty'),
                func.max(PositionGroupLot.group_id).label('group_id'),
            ).outerjoin(
                PositionGroupLot,
                PositionLotModel.transaction_id == PositionGroupLot.transaction_id,
            ).filter(
                PositionLotModel.remaining_quantity != 0,
                PositionLotModel.status != 'CLOSED',
                PositionLotModel.instrument_type.in_(['EQUITY_OPTION', 'EQUITY']),
            ).group_by(
                PositionLotModel.account_number,
                PositionLotModel.symbol,
            ).all()
            for row in rows:
                acct = row[0]
                symbol = (row[1] or '').strip()
                net_qty = row[3]
                if net_qty != 0:
                    key = (acct, symbol)
                    lot_legs_by_key[key] = {
                        'quantity': net_qty,
                        'group_id': row[4],
                        'underlying': row[2],
                    }

        # 3. Reconcile
        matched = 0
        quantity_mismatch = []
        unlinked = []
        stale = []
        today = _date.today()

        all_lot_keys = set(lot_legs_by_key.keys())
        all_tt_keys = set(tt_by_key.keys())

        for key in all_tt_keys:
            acct, symbol = key
            tt_pos = tt_by_key[key]
            instrument = tt_pos.get('instrument_type', '').upper()
            if 'OPTION' not in instrument and 'EQUITY' not in instrument:
                continue

            tt_qty = tt_pos.get('quantity', 0)
            if tt_pos.get('quantity_direction') == 'Short':
                tt_signed = -abs(tt_qty)
            else:
                tt_signed = abs(tt_qty)

            if key in lot_legs_by_key:
                lot_data = lot_legs_by_key[key]
                if lot_data['quantity'] == tt_signed:
                    matched += 1
                else:
                    quantity_mismatch.append({
                        'symbol': symbol,
                        'account': acct,
                        'tt_quantity': tt_signed,
                        'chain_quantity': lot_data['quantity'],
                        'chain_id': lot_data.get('group_id', ''),
                    })
            else:
                unlinked.append({
                    'symbol': symbol,
                    'account': acct,
                    'quantity': tt_signed,
                    'instrument_type': tt_pos.get('instrument_type', ''),
                    'underlying': tt_pos.get('underlying', ''),
                })

        # Check lot legs that TT doesn't have (stale)
        for key in all_lot_keys - all_tt_keys:
            acct, symbol = key
            lot_data = lot_legs_by_key.get(key, {})
            stale.append({
                'symbol': symbol,
                'account': acct,
                'chain_quantity': lot_data.get('quantity', 0),
                'chain_id': lot_data.get('group_id', ''),
            })

        # Auto-close stale lots: close position_lots and refresh affected groups
        auto_closed = []
        if stale:
            matched_group_ids = set()
            for key in all_lot_keys & all_tt_keys:
                ld = lot_legs_by_key.get(key, {})
                if ld.get('group_id'):
                    matched_group_ids.add(ld['group_id'])

            stale_group_ids = set(s['chain_id'] for s in stale if s.get('chain_id'))
            affected_groups = set()

            for group_id in stale_group_ids - matched_group_ids:
                try:
                    with db.get_session() as session:
                        # Find transaction_ids to close
                        txn_rows = session.query(
                            PositionGroupLot.transaction_id,
                        ).join(
                            PositionLotModel,
                            PositionGroupLot.transaction_id == PositionLotModel.transaction_id,
                        ).filter(
                            PositionGroupLot.group_id == group_id,
                            PositionLotModel.remaining_quantity != 0,
                            PositionLotModel.status != 'CLOSED',
                            PositionLotModel.instrument_type.in_(['EQUITY_OPTION', 'EQUITY']),
                        ).all()
                        if txn_rows:
                            txn_ids = [r[0] for r in txn_rows]
                            session.query(PositionLotModel).filter(
                                PositionLotModel.transaction_id.in_(txn_ids),
                            ).update({
                                PositionLotModel.remaining_quantity: 0,
                                PositionLotModel.status: 'CLOSED',
                            }, synchronize_session='fetch')
                            auto_closed.append(group_id)
                            affected_groups.add(group_id)
                            logger.info(f"Auto-closed stale lots in group {group_id}")
                except Exception as e:
                    logger.error(f"Failed to auto-close lots in group {group_id}: {e}")

            if affected_groups:
                for gid in affected_groups:
                    ledger_service._refresh_group_status(gid)

        # Pass 2: Ghost groups — OPEN with no remaining lots and no TT positions
        tt_underlyings_by_acct = {}
        for pos in tt_positions:
            acct = pos.get('account_number', '')
            und = (pos.get('underlying') or pos.get('symbol', '')).strip()
            tt_underlyings_by_acct.setdefault(acct, set()).add(und)

        with db.get_session() as session:
            open_groups = session.query(
                PositionGroup.group_id,
                PositionGroup.account_number,
                PositionGroup.underlying,
            ).filter(
                PositionGroup.status.in_(['OPEN', 'ASSIGNED']),
            ).all()

            # Batch query: count open lots per group
            group_ids_to_check = [r[0] for r in open_groups if r[0] not in set(auto_closed)]
            open_lot_counts = {}
            if group_ids_to_check:
                count_rows = session.query(
                    PositionGroupLot.group_id,
                    func.count(),
                ).join(
                    PositionLotModel,
                    PositionGroupLot.transaction_id == PositionLotModel.transaction_id,
                ).filter(
                    PositionGroupLot.group_id.in_(group_ids_to_check),
                    PositionLotModel.remaining_quantity != 0,
                    PositionLotModel.status != 'CLOSED',
                    PositionLotModel.instrument_type.in_(['EQUITY_OPTION', 'EQUITY']),
                ).group_by(PositionGroupLot.group_id).all()
                open_lot_counts = dict(count_rows)

        groups_to_close = []
        for row in open_groups:
            group_id, acct, underlying = row[0], row[1], row[2]
            if group_id in set(auto_closed):
                continue
            has_open_lots = open_lot_counts.get(group_id, 0) > 0
            if not has_open_lots:
                tt_has_underlying = underlying in tt_underlyings_by_acct.get(acct, set())
                if not tt_has_underlying:
                    groups_to_close.append((group_id, underlying, acct))

        if groups_to_close:
            for gid, underlying, acct in groups_to_close:
                ledger_service._refresh_group_status(gid)
                auto_closed.append(gid)
                logger.info(f"Auto-closed ghost group {gid} ({underlying}/{acct})")

        if auto_closed:
            stale = [s for s in stale if s.get('chain_id') not in auto_closed]

        total = matched + len(quantity_mismatch) + len(unlinked) + len(stale)
        summary = {
            'total': total,
            'matched': matched,
            'quantity_mismatch': quantity_mismatch,
            'unlinked': unlinked,
            'stale': stale,
            'auto_closed': auto_closed,
        }
        logger.info(f"Reconciliation: {matched}/{total} matched, {len(quantity_mismatch)} qty mismatch, {len(unlinked)} unlinked, {len(stale)} stale, {len(auto_closed)} auto-closed")
        return summary

    except Exception as e:
        logger.error(f"Reconciliation error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'total': 0, 'matched': 0, 'quantity_mismatch': [], 'unlinked': [], 'stale': [], 'error': str(e)}
