"""Ledger service — position group seeding, equity lot processing, group status management."""

import uuid as _uuid
from datetime import datetime
from typing import Dict, Optional

from loguru import logger
from sqlalchemy import func
from src.database.engine import dialect_insert
from src.database.tenant import DEFAULT_USER_ID

from src.database.models import (
    OrderChain, PositionLot as PositionLotModel, LotClosing as LotClosingModel,
    PositionGroup, PositionGroupLot, RawTransaction,
)
from src.dependencies import db, lot_manager


def seed_position_groups():
    """Seed position_groups from existing chains. Idempotent — skips chains already seeded."""
    groups_created = 0

    with db.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        # Get all distinct chain_ids from position_lots
        chain_rows = session.query(
            PositionLotModel.chain_id,
            PositionLotModel.account_number,
            PositionLotModel.underlying,
        ).filter(
            PositionLotModel.chain_id.isnot(None),
        ).distinct().all()

        for chain_id, account_number, underlying in chain_rows:
            if not chain_id:
                continue

            # Check if group already exists for this chain
            exists = session.query(PositionGroup.group_id).filter(
                PositionGroup.source_chain_id == chain_id,
            ).first()
            if exists:
                continue

            # Get chain metadata
            chain_info = session.query(
                OrderChain.strategy_type,
                OrderChain.opening_date,
                OrderChain.closing_date,
                OrderChain.chain_status,
            ).filter(OrderChain.chain_id == chain_id).first()

            strategy_label = chain_info[0] if chain_info else None
            opening_date = chain_info[1] if chain_info else None
            closing_date = chain_info[2] if chain_info else None

            # Check actual lot statuses to determine group status
            open_count = session.query(func.count()).select_from(
                PositionLotModel,
            ).filter(
                PositionLotModel.chain_id == chain_id,
                PositionLotModel.remaining_quantity != 0,
                PositionLotModel.status != 'CLOSED',
            ).scalar()
            status = 'OPEN' if open_count > 0 else 'CLOSED'

            # Compute opening/closing dates from lots if not available
            if not opening_date:
                opening_date = session.query(
                    func.min(PositionLotModel.entry_date),
                ).filter(PositionLotModel.chain_id == chain_id).scalar()

            if status == 'CLOSED' and not closing_date:
                closing_date = session.query(
                    func.max(LotClosingModel.closing_date),
                ).join(
                    PositionLotModel, LotClosingModel.lot_id == PositionLotModel.id,
                ).filter(PositionLotModel.chain_id == chain_id).scalar()

            group_id = str(_uuid.uuid4())
            session.add(PositionGroup(
                group_id=group_id,
                account_number=account_number,
                underlying=underlying or '',
                strategy_label=strategy_label,
                status=status,
                source_chain_id=chain_id,
                opening_date=opening_date,
                closing_date=closing_date,
            ))

            # Link lots to group via transaction_id
            txn_ids = [r[0] for r in session.query(
                PositionLotModel.transaction_id,
            ).filter(PositionLotModel.chain_id == chain_id).all()]

            for txn_id in txn_ids:
                stmt = dialect_insert(PositionGroupLot).values(
                    group_id=group_id, transaction_id=txn_id, user_id=user_id,
                )
                session.execute(stmt.on_conflict_do_nothing())

            groups_created += 1

        # Handle lots with no chain_id — create "Ungrouped" groups per underlying/account
        ungrouped = session.query(
            PositionLotModel.transaction_id,
            PositionLotModel.account_number,
            PositionLotModel.underlying,
        ).outerjoin(
            PositionGroupLot,
            PositionLotModel.transaction_id == PositionGroupLot.transaction_id,
        ).filter(
            PositionGroupLot.transaction_id.is_(None),
            PositionLotModel.chain_id.is_(None),
        ).all()

        if ungrouped:
            # Group by account+underlying
            buckets: Dict[str, list] = {}
            for txn_id, acct, und in ungrouped:
                key = f"{acct}|{und or ''}"
                buckets.setdefault(key, []).append(txn_id)

            for key, txn_ids in buckets.items():
                acct, und = key.split('|', 1)
                # Check for any existing OPEN group for this account+underlying
                existing = session.query(PositionGroup.group_id).filter(
                    PositionGroup.account_number == acct,
                    PositionGroup.underlying == und,
                    PositionGroup.status == 'OPEN',
                ).order_by(PositionGroup.opening_date.desc()).first()

                if existing:
                    group_id = existing[0]
                else:
                    group_id = str(_uuid.uuid4())
                    session.add(PositionGroup(
                        group_id=group_id,
                        account_number=acct,
                        underlying=und,
                        strategy_label='Shares',
                        status='OPEN',
                    ))
                    groups_created += 1

                for txn_id in txn_ids:
                    stmt = dialect_insert(PositionGroupLot).values(
                        group_id=group_id, transaction_id=txn_id, user_id=user_id,
                    )
                    session.execute(stmt.on_conflict_do_nothing())

    logger.info(f"Seeded {groups_created} position groups")
    return groups_created


def process_equity_transactions(account_number: Optional[str] = None):
    """Create/close equity lots from raw stock transactions.

    Runs after OrderProcessor (which handles options + assignment equity).
    Processes explicit buy/sell equity trades AND Receive Deliver equity
    (ACAT transfers, etc.) from raw_transactions.

    After processing individual transactions, runs a netting pass to close
    opposing equity lots against each other (e.g., call assignment -800 shares
    vs ACAT +800 shares for the same symbol).

    Returns:
        Tuple of (lots_created, lots_closed)
    """
    lots_created = 0
    lots_closed = 0

    with db.get_session() as session:
        # 1. Query equity transactions: Trade + Receive Deliver (ACAT, etc.)
        q = session.query(RawTransaction).filter(
            RawTransaction.instrument_type == 'InstrumentType.EQUITY',
            RawTransaction.transaction_type.in_(['Trade', 'Receive Deliver']),
            RawTransaction.action.isnot(None),
        )
        if account_number:
            q = q.filter(RawTransaction.account_number == account_number)
        q = q.order_by(RawTransaction.executed_at.asc(), RawTransaction.id.asc())

        equity_txns = [row.to_dict() for row in q.all()]

        if not equity_txns:
            return (0, 0)

        # 2. Get existing lot transaction_ids to skip already-processed
        existing_lot_txn_ids = {
            r[0] for r in session.query(
                PositionLotModel.transaction_id,
            ).filter(
                PositionLotModel.instrument_type == 'EQUITY',
            ).all()
        }

        existing_closing_txn_ids = {
            r[0] for r in session.query(
                LotClosingModel.closing_transaction_id,
            ).filter(
                LotClosingModel.closing_transaction_id.isnot(None),
            ).all()
        }

    # 3. Process each transaction chronologically
    for txn in equity_txns:
        txn_id = txn['id']
        action = (txn.get('action') or '').upper()
        txn_type = txn.get('transaction_type', '')
        symbol = txn.get('underlying_symbol') or txn.get('symbol', '')

        # Normalize instrument_type for lot creation
        txn['instrument_type'] = 'EQUITY'

        # For Receive Deliver: only process opening actions (BTO/STO).
        # STC/BTC from Receive Deliver are assignment settlements — OrderProcessor
        # already creates derived lots for those, so skip to avoid double-counting.
        is_receive_deliver = (txn_type == 'Receive Deliver')

        if 'BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action:
            # Opening transaction — create a lot
            if txn_id in existing_lot_txn_ids:
                continue
            lot_manager.create_lot(
                transaction=txn,
                chain_id='',
                leg_index=0,
                opening_order_id=txn.get('order_id', '')
            )
            existing_lot_txn_ids.add(txn_id)
            lots_created += 1

        elif 'SELL_TO_CLOSE' in action and not is_receive_deliver:
            # STC closes long positions (Trade type only)
            if txn_id in existing_closing_txn_ids:
                continue
            qty = abs(int(txn.get('quantity', 0)))
            if qty > 0:
                pnl, affected = lot_manager.close_lot_fifo(
                    account_number=txn['account_number'],
                    symbol=symbol,
                    quantity_to_close=qty,
                    closing_price=float(txn.get('price', 0)),
                    closing_order_id=txn.get('order_id', ''),
                    closing_transaction_id=txn_id,
                    closing_date=txn.get('executed_at', ''),
                    closing_type='MANUAL',
                    close_long=True
                )
                if affected:
                    existing_closing_txn_ids.add(txn_id)
                    lots_closed += len(affected)

        elif 'BUY_TO_CLOSE' in action and not is_receive_deliver:
            # BTC closes short positions (Trade type only)
            if txn_id in existing_closing_txn_ids:
                continue
            qty = abs(int(txn.get('quantity', 0)))
            if qty > 0:
                pnl, affected = lot_manager.close_lot_fifo(
                    account_number=txn['account_number'],
                    symbol=symbol,
                    quantity_to_close=qty,
                    closing_price=float(txn.get('price', 0)),
                    closing_order_id=txn.get('order_id', ''),
                    closing_transaction_id=txn_id,
                    closing_date=txn.get('executed_at', ''),
                    closing_type='MANUAL',
                    close_long=False
                )
                if affected:
                    existing_closing_txn_ids.add(txn_id)
                    lots_closed += len(affected)

    # 4. Netting pass: close opposing equity lots against each other.
    netted = _net_opposing_equity_lots()
    lots_closed += netted

    logger.info(f"Equity lot processing: {lots_created} lots created, {lots_closed} lots closed (incl {netted} netted)")
    return (lots_created, lots_closed)


def _net_opposing_equity_lots() -> int:
    """Close opposing equity lots (positive vs negative) for the same account+symbol.

    When a call assignment creates a derived lot with negative quantity and there are
    existing long lots (from ACAT, buys, or put assignments), they should net to zero.
    Uses FIFO matching: negative lots close against the oldest positive lots first.

    Returns:
        Number of lot sides closed during netting.
    """
    netted = 0

    # Find (account, symbol) pairs that have BOTH positive and negative open equity lots
    with db.get_session() as session:
        nettable = session.query(
            PositionLotModel.account_number,
            PositionLotModel.symbol,
        ).filter(
            PositionLotModel.instrument_type == 'EQUITY',
            PositionLotModel.remaining_quantity != 0,
            PositionLotModel.status != 'CLOSED',
        ).group_by(
            PositionLotModel.account_number,
            PositionLotModel.symbol,
        ).having(
            func.min(PositionLotModel.remaining_quantity) < 0,
            func.max(PositionLotModel.remaining_quantity) > 0,
        ).all()
        nettable = [(r[0], r[1]) for r in nettable]

    for acct, symbol in nettable:
        # Get negative (short) lots to net, ordered by entry date (FIFO)
        with db.get_session() as session:
            neg_rows = session.query(
                PositionLotModel.id,
                PositionLotModel.remaining_quantity,
                PositionLotModel.entry_price,
                PositionLotModel.entry_date,
            ).filter(
                PositionLotModel.account_number == acct,
                PositionLotModel.symbol == symbol,
                PositionLotModel.instrument_type == 'EQUITY',
                PositionLotModel.remaining_quantity < 0,
                PositionLotModel.status != 'CLOSED',
            ).order_by(PositionLotModel.entry_date.asc()).all()
            neg_lots = [(r[0], r[1], r[2], r[3]) for r in neg_rows]

        for neg_id, neg_remaining, neg_price, neg_date in neg_lots:
            qty_to_close = abs(neg_remaining)

            # Determine closing date: use the latest of (negative lot date, latest positive lot date)
            with db.get_session() as session:
                latest_pos_date = session.query(
                    func.max(PositionLotModel.entry_date),
                ).filter(
                    PositionLotModel.account_number == acct,
                    PositionLotModel.symbol == symbol,
                    PositionLotModel.instrument_type == 'EQUITY',
                    PositionLotModel.remaining_quantity > 0,
                    PositionLotModel.status != 'CLOSED',
                ).scalar()

            closing_date = max(neg_date, latest_pos_date) if latest_pos_date else neg_date

            # Close matching long lots at the negative lot's entry price
            pnl, affected = lot_manager.close_lot_fifo(
                account_number=acct,
                symbol=symbol,
                quantity_to_close=qty_to_close,
                closing_price=neg_price,
                closing_order_id='EQUITY_NETTING',
                closing_transaction_id=None,
                closing_date=closing_date,
                closing_type='MANUAL',
                close_long=True
            )

            if not affected:
                continue

            # Determine how much was actually closed from positive lots
            with db.get_session() as session:
                total_closed = session.query(
                    func.coalesce(func.sum(LotClosingModel.quantity_closed), 0),
                ).filter(
                    LotClosingModel.lot_id.in_(affected),
                    LotClosingModel.closing_order_id == 'EQUITY_NETTING',
                ).scalar()

                if total_closed > 0:
                    # Close the negative lot by the same amount
                    neg_lot = session.get(PositionLotModel, neg_id)
                    new_remaining = neg_remaining + total_closed  # e.g., -800 + 800 = 0
                    new_status = 'CLOSED' if new_remaining == 0 else 'PARTIAL'
                    neg_lot.remaining_quantity = new_remaining
                    neg_lot.status = new_status

                    # Create lot_closing record for the negative lot (P&L captured on positive side)
                    session.add(LotClosingModel(
                        lot_id=neg_id,
                        closing_order_id='EQUITY_NETTING',
                        closing_transaction_id=None,
                        quantity_closed=total_closed,
                        closing_price=neg_price,
                        closing_date=closing_date,
                        closing_type='MANUAL',
                        realized_pnl=0,
                    ))

                    netted += len(affected) + 1  # positive lots closed + negative lot
                    logger.info(f"Netted {total_closed} shares of {symbol}: lot {neg_id} ({neg_remaining}) vs {len(affected)} long lots")

    return netted


def seed_new_lots_into_groups():
    """After reprocessing, assign new lots (not in any group) to their chain's group or create new groups."""
    assigned = 0

    unassigned = lot_manager.get_unassigned_lots()
    if not unassigned:
        # Still refresh group statuses even if no new lots to assign
        _refresh_all_group_statuses()
        return 0

    with db.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        # Check if position_groups table has any rows — if empty, do full seed instead
        group_count = session.query(func.count()).select_from(PositionGroup).scalar()
        if group_count == 0:
            return seed_position_groups()

        # Group unassigned lots by chain_id
        chain_lots: Dict[Optional[str], list] = {}
        for lot in unassigned:
            chain_lots.setdefault(lot.chain_id, []).append(lot)

        for chain_id, lots in chain_lots.items():
            if chain_id:
                # Check if a group exists for this chain
                row = session.query(PositionGroup.group_id).filter(
                    PositionGroup.source_chain_id == chain_id,
                ).first()
                if row:
                    group_id = row[0]
                else:
                    # Create new group for this chain
                    chain_info = session.query(
                        OrderChain.strategy_type,
                        OrderChain.opening_date,
                        OrderChain.closing_date,
                    ).filter(OrderChain.chain_id == chain_id).first()

                    group_id = str(_uuid.uuid4())
                    session.add(PositionGroup(
                        group_id=group_id,
                        account_number=lots[0].account_number,
                        underlying=lots[0].underlying,
                        strategy_label=chain_info[0] if chain_info else None,
                        status='OPEN',
                        source_chain_id=chain_id,
                        opening_date=chain_info[1] if chain_info else None,
                        closing_date=chain_info[2] if chain_info else None,
                    ))

                for lot in lots:
                    stmt = dialect_insert(PositionGroupLot).values(
                        group_id=group_id, transaction_id=lot.transaction_id,
                        user_id=user_id,
                    )
                    session.execute(stmt.on_conflict_do_nothing())
                    assigned += 1
            else:
                # No chain_id — add to ungrouped bucket per underlying/account
                buckets: Dict[str, list] = {}
                for lot in lots:
                    key = f"{lot.account_number}|{lot.underlying}"
                    buckets.setdefault(key, []).append(lot)

                for key, blots in buckets.items():
                    acct, und = key.split('|', 1)
                    # Find any existing OPEN group for this account+underlying
                    row = session.query(PositionGroup.group_id).filter(
                        PositionGroup.account_number == acct,
                        PositionGroup.underlying == und,
                        PositionGroup.status == 'OPEN',
                    ).order_by(PositionGroup.opening_date.desc()).first()

                    if row:
                        group_id = row[0]
                    else:
                        group_id = str(_uuid.uuid4())
                        session.add(PositionGroup(
                            group_id=group_id,
                            account_number=acct,
                            underlying=und,
                            strategy_label='Shares',
                            status='OPEN',
                        ))

                    for lot in blots:
                        stmt = dialect_insert(PositionGroupLot).values(
                            group_id=group_id, transaction_id=lot.transaction_id,
                            user_id=user_id,
                        )
                        session.execute(stmt.on_conflict_do_nothing())
                        assigned += 1

    # Update group statuses/dates for affected groups (outside the session above)
    _refresh_all_group_statuses()

    logger.info(f"Seeded {assigned} new lots into position groups")
    return assigned


def _reconcile_stale_groups():
    """Update position_groups whose source_chain_id no longer exists in order_chains.

    For groups with lots from multiple chains (e.g. user moved lots on Ledger),
    set source_chain_id to the earliest lot's chain_id as a best-effort match
    for future seeding.
    """
    reconciled = 0
    with db.get_session() as session:
        # Fix stale source_chain_id references
        stale_groups = session.query(
            PositionGroup.group_id,
            PositionGroup.source_chain_id,
        ).outerjoin(
            OrderChain, PositionGroup.source_chain_id == OrderChain.chain_id,
        ).filter(
            PositionGroup.source_chain_id.isnot(None),
            OrderChain.chain_id.is_(None),
        ).all()

        for stale_gid, stale_chain_id in stale_groups:
            # Find the actual chain_id(s) from the group's lots
            chain_rows = session.query(
                PositionLotModel.chain_id,
            ).join(
                PositionGroupLot,
                PositionLotModel.transaction_id == PositionGroupLot.transaction_id,
            ).filter(
                PositionGroupLot.group_id == stale_gid,
                PositionLotModel.chain_id.isnot(None),
            ).order_by(PositionLotModel.entry_date.asc()).distinct().all()

            if chain_rows:
                # Use the earliest lot's chain_id (best-effort for future seeding)
                new_chain_id = chain_rows[0][0]
                chain_info = session.query(
                    OrderChain.underlying,
                    OrderChain.strategy_type,
                    OrderChain.opening_date,
                    OrderChain.closing_date,
                    OrderChain.chain_status,
                ).filter(OrderChain.chain_id == new_chain_id).first()

                if chain_info:
                    group = session.query(PositionGroup).filter(
                        PositionGroup.group_id == stale_gid,
                    ).first()
                    if group:
                        group.source_chain_id = new_chain_id
                        group.underlying = chain_info[0]
                        group.strategy_label = chain_info[1]
                        group.opening_date = chain_info[2]
                        group.closing_date = chain_info[3]
                        group.status = chain_info[4]
                        reconciled += 1
                        logger.info(f"Reconciled stale group {stale_gid}: "
                                    f"{stale_chain_id} -> {new_chain_id} ({chain_info[0]})")

    if reconciled:
        logger.info(f"Reconciled {reconciled} stale position groups")
    return reconciled


def _refresh_group_status(group_id: str, session=None):
    """Recalculate status, opening_date, closing_date for a single group.

    If session is provided, uses it (caller manages commit).
    Otherwise opens its own session.
    """
    if session is None:
        with db.get_session() as s:
            return _refresh_group_status(group_id, session=s)

    open_count = session.query(func.count()).select_from(
        PositionGroupLot,
    ).join(
        PositionLotModel,
        PositionGroupLot.transaction_id == PositionLotModel.transaction_id,
    ).filter(
        PositionGroupLot.group_id == group_id,
        PositionLotModel.remaining_quantity != 0,
        PositionLotModel.status != 'CLOSED',
    ).scalar()

    total_count = session.query(func.count()).select_from(
        PositionGroupLot,
    ).filter(PositionGroupLot.group_id == group_id).scalar()

    if total_count == 0:
        # Empty group — delete it
        session.query(PositionGroup).filter(
            PositionGroup.group_id == group_id,
        ).delete()
        return

    status = 'OPEN' if open_count > 0 else 'CLOSED'

    opening_date = session.query(
        func.min(PositionLotModel.entry_date),
    ).join(
        PositionGroupLot,
        PositionLotModel.transaction_id == PositionGroupLot.transaction_id,
    ).filter(PositionGroupLot.group_id == group_id).scalar()

    closing_date = None
    if status == 'CLOSED':
        closing_date = session.query(
            func.max(LotClosingModel.closing_date),
        ).join(
            PositionLotModel, LotClosingModel.lot_id == PositionLotModel.id,
        ).join(
            PositionGroupLot,
            PositionLotModel.transaction_id == PositionGroupLot.transaction_id,
        ).filter(PositionGroupLot.group_id == group_id).scalar()

    group = session.query(PositionGroup).filter(
        PositionGroup.group_id == group_id,
    ).first()
    if group:
        group.status = status
        group.opening_date = opening_date
        group.closing_date = closing_date
        group.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _refresh_all_group_statuses(session=None):
    """Recalculate status for all groups.

    If session is provided, uses it. Otherwise opens its own.
    """
    if session is None:
        with db.get_session() as s:
            return _refresh_all_group_statuses(session=s)

    group_ids = [r[0] for r in session.query(PositionGroup.group_id).all()]
    for gid in group_ids:
        _refresh_group_status(gid, session=session)
