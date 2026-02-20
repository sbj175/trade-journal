"""Ledger routes — position groups CRUD and lot management."""

import json as _json
import uuid as _uuid
from typing import Dict

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.dependencies import db, lot_manager
from src.schemas import LedgerGroupUpdate, LedgerMoveLots, LedgerCreateGroup
from src.services.ledger_service import seed_position_groups, _refresh_group_status

router = APIRouter()


@router.get("/api/ledger")
async def get_ledger(account_number: str = '', underlying: str = ''):
    """Main Ledger data endpoint — returns position groups with lots and derived orders."""

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Auto-seed if position_groups is empty
        cursor.execute("SELECT COUNT(*) FROM position_groups")
        if cursor.fetchone()[0] == 0:
            cursor.execute("SELECT COUNT(*) FROM position_lots")
            if cursor.fetchone()[0] > 0:
                seed_position_groups()

    # Query groups with filters
    query = "SELECT * FROM position_groups WHERE 1=1"
    params = []
    if account_number:
        query += " AND account_number = ?"
        params.append(account_number)
    if underlying:
        query += " AND underlying = ?"
        params.append(underlying)
    query += " ORDER BY underlying ASC, opening_date DESC"

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        groups_raw = [dict(row) for row in cursor.fetchall()]

    if not groups_raw:
        return []

    group_ids = [g['group_id'] for g in groups_raw]

    # Batch-load lots
    lots_by_group = lot_manager.get_lots_for_groups_batch(group_ids)

    # Collect all lot IDs for batch closing load
    all_lot_ids = []
    for lots in lots_by_group.values():
        for lot in lots:
            all_lot_ids.append(lot.id)

    closings_by_lot = lot_manager.get_lot_closings_batch(all_lot_ids) if all_lot_ids else {}

    # Collect all order_ids to derive orders per group
    all_order_ids = set()
    group_order_ids: Dict[str, set] = {gid: set() for gid in group_ids}

    for gid, lots in lots_by_group.items():
        for lot in lots:
            if lot.opening_order_id:
                all_order_ids.add(lot.opening_order_id)
                group_order_ids[gid].add(lot.opening_order_id)
            for closing in closings_by_lot.get(lot.id, []):
                if closing.closing_order_id:
                    all_order_ids.add(closing.closing_order_id)
                    group_order_ids[gid].add(closing.closing_order_id)

    # Fetch order data from cache
    order_cache: Dict[str, Dict] = {}
    if all_order_ids:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            oid_list = list(all_order_ids)
            placeholders = ','.join(['?' for _ in oid_list])
            cursor.execute(f"""
                SELECT order_id, order_data FROM order_chain_cache
                WHERE order_id IN ({placeholders})
            """, oid_list)
            for row in cursor.fetchall():
                try:
                    order_cache[row[0]] = _json.loads(row[1])
                except:
                    pass

    # Build response
    result = []
    for g in groups_raw:
        gid = g['group_id']
        lots = lots_by_group.get(gid, [])

        lots_data = []
        total_realized = 0.0
        open_lot_count = 0

        for lot in lots:
            lot_closings = closings_by_lot.get(lot.id, [])
            lot_realized = sum(c.realized_pnl for c in lot_closings)
            total_realized += lot_realized

            multiplier = 100 if lot.option_type else 1
            cost_basis = abs(lot.entry_price * lot.original_quantity * multiplier)

            is_open = lot.remaining_quantity != 0 and lot.status != 'CLOSED'
            if is_open:
                open_lot_count += 1

            closings_data = []
            for c in lot_closings:
                closings_data.append({
                    'closing_id': c.closing_id,
                    'quantity_closed': c.quantity_closed,
                    'closing_price': c.closing_price,
                    'closing_date': str(c.closing_date) if c.closing_date else None,
                    'closing_type': c.closing_type,
                    'realized_pnl': c.realized_pnl,
                })

            lots_data.append({
                'lot_id': lot.id,
                'transaction_id': lot.transaction_id,
                'symbol': lot.symbol,
                'underlying': lot.underlying,
                'instrument_type': lot.instrument_type,
                'option_type': lot.option_type,
                'strike': lot.strike,
                'expiration': str(lot.expiration) if lot.expiration else None,
                'quantity': lot.quantity,
                'entry_price': lot.entry_price,
                'entry_date': str(lot.entry_date) if lot.entry_date else None,
                'remaining_quantity': lot.remaining_quantity,
                'original_quantity': lot.original_quantity,
                'status': lot.status,
                'leg_index': lot.leg_index,
                'derived_from_lot_id': lot.derived_from_lot_id,
                'derivation_type': lot.derivation_type,
                'cost_basis': cost_basis,
                'realized_pnl': lot_realized,
                'total_pnl': lot_realized,
                'closings': closings_data,
            })

        # Build orders for Action view
        orders_data = []
        for oid in sorted(group_order_ids.get(gid, []),
                          key=lambda x: order_cache.get(x, {}).get('order_date', ''),
                          reverse=True):
            if oid in order_cache:
                orders_data.append(order_cache[oid])

        result.append({
            'group_id': gid,
            'underlying': g['underlying'],
            'strategy_label': g['strategy_label'],
            'status': g['status'],
            'account_number': g['account_number'],
            'opening_date': g['opening_date'],
            'closing_date': g['closing_date'],
            'source_chain_id': g['source_chain_id'],
            'total_pnl': total_realized,
            'realized_pnl': total_realized,
            'unrealized_pnl': 0.0,
            'lot_count': len(lots),
            'open_lot_count': open_lot_count,
            'lots': lots_data,
            'orders': orders_data,
        })

    return result


@router.post("/api/ledger/seed")
async def seed_ledger():
    """Explicitly seed position groups from existing chains."""
    count = seed_position_groups()
    return {"message": f"Seeded {count} position groups", "groups_created": count}


@router.put("/api/ledger/groups/{group_id}")
async def update_ledger_group(group_id: str, body: LedgerGroupUpdate):
    """Update group metadata (strategy label)."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT group_id FROM position_groups WHERE group_id = ?", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Group not found")

        updates = []
        params = []
        if body.strategy_label is not None:
            updates.append("strategy_label = ?")
            params.append(body.strategy_label)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(group_id)
            cursor.execute(
                f"UPDATE position_groups SET {', '.join(updates)} WHERE group_id = ?",
                params
            )

    return {"message": "Group updated"}


@router.post("/api/ledger/move-lots")
async def move_lots(body: LedgerMoveLots):
    """Move lots between position groups. All lots and target must share underlying + account."""
    if not body.transaction_ids:
        raise HTTPException(status_code=400, detail="No transaction_ids provided")

    with db.get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT account_number, underlying FROM position_groups WHERE group_id = ?",
            (body.target_group_id,)
        )
        target = cursor.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Target group not found")
        target_account, target_underlying = target

        placeholders = ','.join(['?' for _ in body.transaction_ids])
        cursor.execute(f"""
            SELECT DISTINCT pl.account_number, pl.underlying
            FROM position_lots pl
            WHERE pl.transaction_id IN ({placeholders})
        """, body.transaction_ids)
        lot_accounts = cursor.fetchall()

        for row in lot_accounts:
            if row[0] != target_account or (row[1] or '') != (target_underlying or ''):
                raise HTTPException(
                    status_code=400,
                    detail="All lots must share the same underlying and account as the target group"
                )

        cursor.execute(f"""
            SELECT DISTINCT group_id FROM position_group_lots
            WHERE transaction_id IN ({placeholders})
        """, body.transaction_ids)
        source_groups = [row[0] for row in cursor.fetchall()]

        cursor.execute(f"""
            DELETE FROM position_group_lots
            WHERE transaction_id IN ({placeholders})
        """, body.transaction_ids)

        for txn_id in body.transaction_ids:
            cursor.execute("""
                INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                VALUES (?, ?)
            """, (body.target_group_id, txn_id))

        all_affected = set(source_groups + [body.target_group_id])
        for gid in all_affected:
            _refresh_group_status(cursor, gid)

        conn.commit()

    return {"message": f"Moved {len(body.transaction_ids)} lots"}


@router.post("/api/ledger/groups")
async def create_ledger_group(body: LedgerCreateGroup):
    """Create a new empty position group."""
    group_id = str(_uuid.uuid4())

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO position_groups
                (group_id, account_number, underlying, strategy_label, status)
            VALUES (?, ?, ?, ?, 'OPEN')
        """, (group_id, body.account_number, body.underlying, body.strategy_label))

    return {"group_id": group_id, "message": "Group created"}


@router.delete("/api/ledger/groups/{group_id}")
async def delete_ledger_group(group_id: str):
    """Delete a group. Orphaned lots become unassigned (picked up by next seed)."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT group_id FROM position_groups WHERE group_id = ?", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Group not found")

        cursor.execute("DELETE FROM position_groups WHERE group_id = ?", (group_id,))

    return {"message": "Group deleted"}
