"""Ledger service — position group seeding, equity lot processing, group status management."""

import uuid as _uuid
from typing import Dict, Optional
from loguru import logger

from src.dependencies import db, lot_manager


def seed_position_groups():
    """Seed position_groups from existing chains. Idempotent — skips chains already seeded."""
    groups_created = 0

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Get all distinct chain_ids from position_lots
        cursor.execute("""
            SELECT DISTINCT chain_id, account_number, underlying
            FROM position_lots
            WHERE chain_id IS NOT NULL
        """)
        chain_rows = cursor.fetchall()

        for row in chain_rows:
            chain_id, account_number, underlying = row
            if not chain_id:
                continue

            # Check if group already exists for this chain
            cursor.execute(
                "SELECT group_id FROM position_groups WHERE source_chain_id = ?",
                (chain_id,)
            )
            if cursor.fetchone():
                continue

            # Get chain metadata
            cursor.execute(
                "SELECT strategy_type, opening_date, closing_date, chain_status FROM order_chains WHERE chain_id = ?",
                (chain_id,)
            )
            chain_info = cursor.fetchone()
            strategy_label = chain_info[0] if chain_info else None
            opening_date = chain_info[1] if chain_info else None
            closing_date = chain_info[2] if chain_info else None
            chain_status = chain_info[3] if chain_info else 'OPEN'

            # Check actual lot statuses to determine group status
            cursor.execute("""
                SELECT COUNT(*) FROM position_lots
                WHERE chain_id = ? AND remaining_quantity != 0 AND status != 'CLOSED'
            """, (chain_id,))
            open_count = cursor.fetchone()[0]
            status = 'OPEN' if open_count > 0 else 'CLOSED'

            # Compute opening/closing dates from lots if not available
            if not opening_date:
                cursor.execute(
                    "SELECT MIN(entry_date) FROM position_lots WHERE chain_id = ?",
                    (chain_id,)
                )
                r = cursor.fetchone()
                opening_date = r[0] if r else None

            if status == 'CLOSED' and not closing_date:
                cursor.execute("""
                    SELECT MAX(lc.closing_date) FROM lot_closings lc
                    JOIN position_lots pl ON lc.lot_id = pl.id
                    WHERE pl.chain_id = ?
                """, (chain_id,))
                r = cursor.fetchone()
                closing_date = r[0] if r else None

            group_id = str(_uuid.uuid4())
            cursor.execute("""
                INSERT INTO position_groups
                    (group_id, account_number, underlying, strategy_label, status,
                     source_chain_id, opening_date, closing_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (group_id, account_number, underlying or '', strategy_label,
                  status, chain_id, opening_date, closing_date))

            # Link lots to group via transaction_id
            cursor.execute(
                "SELECT transaction_id FROM position_lots WHERE chain_id = ?",
                (chain_id,)
            )
            txn_ids = [r[0] for r in cursor.fetchall()]
            for txn_id in txn_ids:
                cursor.execute("""
                    INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                    VALUES (?, ?)
                """, (group_id, txn_id))

            groups_created += 1

        # Handle lots with no chain_id — create "Ungrouped" groups per underlying/account
        cursor.execute("""
            SELECT pl.transaction_id, pl.account_number, pl.underlying
            FROM position_lots pl
            LEFT JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
            WHERE pgl.transaction_id IS NULL AND pl.chain_id IS NULL
        """)
        ungrouped = cursor.fetchall()

        if ungrouped:
            # Group by account+underlying
            buckets: Dict[str, list] = {}
            for txn_id, acct, und in ungrouped:
                key = f"{acct}|{und or ''}"
                buckets.setdefault(key, []).append(txn_id)

            for key, txn_ids in buckets.items():
                acct, und = key.split('|', 1)
                group_id = str(_uuid.uuid4())
                cursor.execute("""
                    INSERT INTO position_groups
                        (group_id, account_number, underlying, strategy_label, status,
                         source_chain_id, opening_date, closing_date)
                    VALUES (?, ?, ?, 'Ungrouped', 'OPEN', NULL, NULL, NULL)
                """, (group_id, acct, und))
                for txn_id in txn_ids:
                    cursor.execute("""
                        INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                        VALUES (?, ?)
                    """, (group_id, txn_id))
                groups_created += 1

        conn.commit()

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

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # 1. Query equity transactions: Trade + Receive Deliver (ACAT, etc.)
        query = """
            SELECT id, account_number, order_id, transaction_type,
                   transaction_sub_type, executed_at, action, symbol,
                   instrument_type, underlying_symbol, quantity, price, value
            FROM raw_transactions
            WHERE instrument_type = 'InstrumentType.EQUITY'
              AND transaction_type IN ('Trade', 'Receive Deliver')
              AND action IS NOT NULL
        """
        params = []
        if account_number:
            query += " AND account_number = ?"
            params.append(account_number)
        query += " ORDER BY executed_at ASC, id ASC"
        cursor.execute(query, params)
        equity_txns = [dict(row) for row in cursor.fetchall()]

        if not equity_txns:
            return (0, 0)

        # 2. Get existing lot transaction_ids to skip already-processed
        cursor.execute("""
            SELECT transaction_id FROM position_lots WHERE instrument_type = 'EQUITY'
        """)
        existing_lot_txn_ids = {row[0] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT closing_transaction_id FROM lot_closings
            WHERE closing_transaction_id IS NOT NULL
        """)
        existing_closing_txn_ids = {row[0] for row in cursor.fetchall()}

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

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Find (account, symbol) pairs that have BOTH positive and negative open equity lots
        cursor.execute("""
            SELECT account_number, symbol
            FROM position_lots
            WHERE instrument_type = 'EQUITY' AND remaining_quantity != 0 AND status != 'CLOSED'
            GROUP BY account_number, symbol
            HAVING MIN(remaining_quantity) < 0 AND MAX(remaining_quantity) > 0
        """)
        nettable = [(row[0], row[1]) for row in cursor.fetchall()]

    for acct, symbol in nettable:
        # Get negative (short) lots to net, ordered by entry date (FIFO)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, remaining_quantity, entry_price, entry_date
                FROM position_lots
                WHERE account_number = ? AND symbol = ? AND instrument_type = 'EQUITY'
                  AND remaining_quantity < 0 AND status != 'CLOSED'
                ORDER BY entry_date ASC
            """, (acct, symbol))
            neg_lots = cursor.fetchall()

        for neg_id, neg_remaining, neg_price, neg_date in neg_lots:
            qty_to_close = abs(neg_remaining)

            # Determine closing date: use the latest of (negative lot date, latest positive lot date)
            # so that closing dates never appear before the lots they close
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MAX(entry_date) FROM position_lots
                    WHERE account_number = ? AND symbol = ? AND instrument_type = 'EQUITY'
                      AND remaining_quantity > 0 AND status != 'CLOSED'
                """, (acct, symbol))
                latest_pos_date = cursor.fetchone()[0]

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
            with db.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join(['?' for _ in affected])
                cursor.execute(f"""
                    SELECT COALESCE(SUM(quantity_closed), 0)
                    FROM lot_closings
                    WHERE lot_id IN ({placeholders}) AND closing_order_id = 'EQUITY_NETTING'
                """, affected)
                total_closed = cursor.fetchone()[0]

                if total_closed > 0:
                    # Close the negative lot by the same amount
                    new_remaining = neg_remaining + total_closed  # e.g., -800 + 800 = 0
                    new_status = 'CLOSED' if new_remaining == 0 else 'PARTIAL'
                    cursor.execute("""
                        UPDATE position_lots SET remaining_quantity = ?, status = ? WHERE id = ?
                    """, (new_remaining, new_status, neg_id))

                    # Create lot_closing record for the negative lot (P&L captured on positive side)
                    cursor.execute("""
                        INSERT INTO lot_closings (
                            lot_id, closing_order_id, closing_transaction_id,
                            quantity_closed, closing_price, closing_date,
                            closing_type, realized_pnl
                        ) VALUES (?, 'EQUITY_NETTING', NULL, ?, ?, ?, 'MANUAL', 0)
                    """, (neg_id, total_closed, neg_price, closing_date))

                    conn.commit()
                    netted += len(affected) + 1  # positive lots closed + negative lot
                    logger.info(f"Netted {total_closed} shares of {symbol}: lot {neg_id} ({neg_remaining}) vs {len(affected)} long lots")

    return netted


def seed_new_lots_into_groups():
    """After reprocessing, assign new lots (not in any group) to their chain's group or create new groups."""
    assigned = 0

    unassigned = lot_manager.get_unassigned_lots()
    if not unassigned:
        # Still refresh group statuses even if no new lots to assign
        with db.get_connection() as conn:
            cursor = conn.cursor()
            _refresh_all_group_statuses(cursor)
            conn.commit()
        return 0

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Check if position_groups table has any rows — if empty, do full seed instead
        cursor.execute("SELECT COUNT(*) FROM position_groups")
        if cursor.fetchone()[0] == 0:
            return seed_position_groups()

        # Group unassigned lots by chain_id
        chain_lots: Dict[Optional[str], list] = {}
        for lot in unassigned:
            chain_lots.setdefault(lot.chain_id, []).append(lot)

        for chain_id, lots in chain_lots.items():
            if chain_id:
                # Check if a group exists for this chain
                cursor.execute(
                    "SELECT group_id FROM position_groups WHERE source_chain_id = ?",
                    (chain_id,)
                )
                row = cursor.fetchone()
                if row:
                    group_id = row[0]
                else:
                    # Create new group for this chain
                    cursor.execute(
                        "SELECT strategy_type, opening_date, closing_date FROM order_chains WHERE chain_id = ?",
                        (chain_id,)
                    )
                    chain_info = cursor.fetchone()
                    group_id = str(_uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO position_groups
                            (group_id, account_number, underlying, strategy_label, status,
                             source_chain_id, opening_date, closing_date)
                        VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?)
                    """, (group_id, lots[0].account_number, lots[0].underlying,
                          chain_info[0] if chain_info else None,
                          chain_id,
                          chain_info[1] if chain_info else None,
                          chain_info[2] if chain_info else None))

                for lot in lots:
                    cursor.execute("""
                        INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                        VALUES (?, ?)
                    """, (group_id, lot.transaction_id))
                    assigned += 1
            else:
                # No chain_id — add to ungrouped bucket per underlying/account
                buckets: Dict[str, list] = {}
                for lot in lots:
                    key = f"{lot.account_number}|{lot.underlying}"
                    buckets.setdefault(key, []).append(lot)

                for key, blots in buckets.items():
                    acct, und = key.split('|', 1)
                    # Find or create ungrouped group
                    cursor.execute("""
                        SELECT group_id FROM position_groups
                        WHERE account_number = ? AND underlying = ? AND source_chain_id IS NULL
                        AND strategy_label = 'Ungrouped'
                    """, (acct, und))
                    row = cursor.fetchone()
                    if row:
                        group_id = row[0]
                    else:
                        group_id = str(_uuid.uuid4())
                        cursor.execute("""
                            INSERT INTO position_groups
                                (group_id, account_number, underlying, strategy_label, status,
                                 source_chain_id, opening_date, closing_date)
                            VALUES (?, ?, ?, 'Ungrouped', 'OPEN', NULL, NULL, NULL)
                        """, (group_id, acct, und))

                    for lot in blots:
                        cursor.execute("""
                            INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                            VALUES (?, ?)
                        """, (group_id, lot.transaction_id))
                        assigned += 1

        # Update group statuses/dates for affected groups
        _refresh_all_group_statuses(cursor)
        conn.commit()

    logger.info(f"Seeded {assigned} new lots into position groups")
    return assigned


def _reconcile_stale_groups():
    """Update position_groups whose source_chain_id no longer exists in order_chains.

    For groups with lots from multiple chains (e.g. user moved lots on Ledger),
    set source_chain_id to the earliest lot's chain_id as a best-effort match
    for future seeding.
    """
    reconciled = 0
    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Fix stale source_chain_id references
        cursor.execute("""
            SELECT pg.group_id, pg.source_chain_id
            FROM position_groups pg
            LEFT JOIN order_chains oc ON pg.source_chain_id = oc.chain_id
            WHERE pg.source_chain_id IS NOT NULL AND oc.chain_id IS NULL
        """)
        stale_groups = cursor.fetchall()
        for stale_row in stale_groups:
            stale_gid = stale_row[0]
            # Find the actual chain_id(s) from the group's lots
            cursor.execute("""
                SELECT DISTINCT pl.chain_id
                FROM position_group_lots pgl
                JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
                WHERE pgl.group_id = ? AND pl.chain_id IS NOT NULL
                ORDER BY pl.entry_date ASC
            """, (stale_gid,))
            chain_rows = cursor.fetchall()
            if chain_rows:
                # Use the earliest lot's chain_id (best-effort for future seeding)
                new_chain_id = chain_rows[0][0]
                cursor.execute("""
                    SELECT underlying, strategy_type, opening_date, closing_date, chain_status
                    FROM order_chains WHERE chain_id = ?
                """, (new_chain_id,))
                chain_info = cursor.fetchone()
                if chain_info:
                    cursor.execute("""
                        UPDATE position_groups
                        SET source_chain_id = ?, underlying = ?, strategy_label = ?,
                            opening_date = ?, closing_date = ?, status = ?
                        WHERE group_id = ?
                    """, (new_chain_id, chain_info[0], chain_info[1],
                          chain_info[2], chain_info[3], chain_info[4], stale_gid))
                    reconciled += 1
                    logger.info(f"Reconciled stale group {stale_gid}: "
                                f"{stale_row[1]} -> {new_chain_id} ({chain_info[0]})")

        conn.commit()
    if reconciled:
        logger.info(f"Reconciled {reconciled} stale position groups")
    return reconciled


def _refresh_group_status(cursor, group_id: str):
    """Recalculate status, opening_date, closing_date for a single group."""
    cursor.execute("""
        SELECT COUNT(*) FROM position_group_lots pgl
        JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
        WHERE pgl.group_id = ? AND pl.remaining_quantity != 0 AND pl.status != 'CLOSED'
    """, (group_id,))
    open_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM position_group_lots WHERE group_id = ?
    """, (group_id,))
    total_count = cursor.fetchone()[0]

    if total_count == 0:
        # Empty group — delete it
        cursor.execute("DELETE FROM position_groups WHERE group_id = ?", (group_id,))
        return

    status = 'OPEN' if open_count > 0 else 'CLOSED'

    cursor.execute("""
        SELECT MIN(pl.entry_date) FROM position_group_lots pgl
        JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
        WHERE pgl.group_id = ?
    """, (group_id,))
    opening_date = cursor.fetchone()[0]

    closing_date = None
    if status == 'CLOSED':
        cursor.execute("""
            SELECT MAX(lc.closing_date) FROM lot_closings lc
            JOIN position_lots pl ON lc.lot_id = pl.id
            JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
            WHERE pgl.group_id = ?
        """, (group_id,))
        r = cursor.fetchone()
        closing_date = r[0] if r else None

    cursor.execute("""
        UPDATE position_groups
        SET status = ?, opening_date = ?, closing_date = ?, updated_at = CURRENT_TIMESTAMP
        WHERE group_id = ?
    """, (status, opening_date, closing_date, group_id))


def _refresh_all_group_statuses(cursor):
    """Recalculate status for all groups."""
    cursor.execute("SELECT group_id FROM position_groups")
    for row in cursor.fetchall():
        _refresh_group_status(cursor, row[0])
