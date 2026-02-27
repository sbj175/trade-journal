"""Ledger routes — position groups CRUD and lot management."""

import json as _json
import uuid as _uuid
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import OrderChainCache, PositionGroup, PositionGroupLot, PositionGroupTag, PositionLot as PositionLotModel, Tag
from src.dependencies import db, lot_manager, get_current_user_id
from src.schemas import LedgerGroupUpdate, LedgerMoveLots, LedgerCreateGroup, GroupTagAdd
from src.services.ledger_service import seed_position_groups, _refresh_group_status

router = APIRouter()


@router.get("/api/ledger")
async def get_ledger(account_number: str = '', underlying: str = '', user_id: str = Depends(get_current_user_id)):
    """Main Ledger data endpoint — returns position groups with lots and derived orders."""

    # Auto-seed if position_groups is empty
    with db.get_session() as session:
        group_count = session.query(func.count()).select_from(PositionGroup).scalar()
        if group_count == 0:
            lot_count = session.query(func.count()).select_from(PositionLotModel).scalar()
            if lot_count > 0:
                seed_position_groups()

    # Query groups with filters
    with db.get_session() as session:
        q = session.query(PositionGroup)
        if account_number:
            q = q.filter(PositionGroup.account_number == account_number)
        if underlying:
            q = q.filter(PositionGroup.underlying == underlying)
        q = q.order_by(PositionGroup.underlying.asc(), PositionGroup.opening_date.desc())
        groups_raw = [row.to_dict() for row in q.all()]

    if not groups_raw:
        return []

    group_ids = [g['group_id'] for g in groups_raw]

    # Batch-load tags for all groups
    tags_by_group: Dict[str, list] = {gid: [] for gid in group_ids}
    with db.get_session() as session:
        tag_rows = session.query(
            PositionGroupTag.group_id, Tag.id, Tag.name, Tag.color,
        ).join(Tag, PositionGroupTag.tag_id == Tag.id).filter(
            PositionGroupTag.group_id.in_(group_ids),
        ).all()
        for gid, tid, tname, tcolor in tag_rows:
            tags_by_group[gid].append({"id": tid, "name": tname, "color": tcolor or "#3B82F6"})

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
        with db.get_session() as session:
            rows = session.query(
                OrderChainCache.order_id, OrderChainCache.order_data,
            ).filter(
                OrderChainCache.order_id.in_(list(all_order_ids)),
            ).all()
            for row in rows:
                try:
                    order_cache[row[0]] = _json.loads(row[1])
                except Exception:
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
            'tags': tags_by_group.get(gid, []),
        })

    return result


@router.post("/api/ledger/seed")
async def seed_ledger(user_id: str = Depends(get_current_user_id)):
    """Explicitly seed position groups from existing chains."""
    count = seed_position_groups()
    return {"message": f"Seeded {count} position groups", "groups_created": count}


@router.put("/api/ledger/groups/{group_id}")
async def update_ledger_group(group_id: str, body: LedgerGroupUpdate, user_id: str = Depends(get_current_user_id)):
    """Update group metadata (strategy label)."""
    with db.get_session() as session:
        row = session.query(PositionGroup).filter(
            PositionGroup.group_id == group_id,
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Group not found")

        if body.strategy_label is not None:
            row.strategy_label = body.strategy_label
            row.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return {"message": "Group updated"}


@router.post("/api/ledger/move-lots")
async def move_lots(body: LedgerMoveLots, user_id: str = Depends(get_current_user_id)):
    """Move lots between position groups. All lots and target must share underlying + account."""
    if not body.transaction_ids:
        raise HTTPException(status_code=400, detail="No transaction_ids provided")

    with db.get_session() as session:
        target = session.query(
            PositionGroup.account_number, PositionGroup.underlying,
        ).filter(PositionGroup.group_id == body.target_group_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Target group not found")
        target_account, target_underlying = target

        lot_accounts = session.query(
            PositionLotModel.account_number, PositionLotModel.underlying,
        ).filter(
            PositionLotModel.transaction_id.in_(body.transaction_ids),
        ).distinct().all()

        for row in lot_accounts:
            if row[0] != target_account or (row[1] or '') != (target_underlying or ''):
                raise HTTPException(
                    status_code=400,
                    detail="All lots must share the same underlying and account as the target group"
                )

        source_groups = [r[0] for r in session.query(
            PositionGroupLot.group_id,
        ).filter(
            PositionGroupLot.transaction_id.in_(body.transaction_ids),
        ).distinct().all()]

        from src.database.engine import dialect_insert
        from src.database.tenant import DEFAULT_USER_ID
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        session.query(PositionGroupLot).filter(
            PositionGroupLot.transaction_id.in_(body.transaction_ids),
            PositionGroupLot.user_id == user_id,
        ).delete(synchronize_session='fetch')
        for txn_id in body.transaction_ids:
            stmt = dialect_insert(PositionGroupLot).values(
                group_id=body.target_group_id, transaction_id=txn_id,
                user_id=user_id,
            )
            session.execute(stmt.on_conflict_do_nothing(index_elements=['group_id', 'transaction_id', 'user_id']))

        all_affected = set(source_groups + [body.target_group_id])
        for gid in all_affected:
            _refresh_group_status(gid, session=session)

    return {"message": f"Moved {len(body.transaction_ids)} lots"}


@router.post("/api/ledger/groups")
async def create_ledger_group(body: LedgerCreateGroup, user_id: str = Depends(get_current_user_id)):
    """Create a new empty position group."""
    group_id = str(_uuid.uuid4())

    with db.get_session() as session:
        session.add(PositionGroup(
            group_id=group_id,
            account_number=body.account_number,
            underlying=body.underlying,
            strategy_label=body.strategy_label,
            status='OPEN',
        ))

    return {"group_id": group_id, "message": "Group created"}


@router.delete("/api/ledger/groups/{group_id}")
async def delete_ledger_group(group_id: str, user_id: str = Depends(get_current_user_id)):
    """Delete a group. Orphaned lots become unassigned (picked up by next seed)."""
    with db.get_session() as session:
        row = session.query(PositionGroup).filter(
            PositionGroup.group_id == group_id,
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Group not found")

        session.delete(row)

    return {"message": "Group deleted"}


@router.post("/api/ledger/groups/{group_id}/tags")
async def add_tag_to_group(group_id: str, body: GroupTagAdd, user_id: str = Depends(get_current_user_id)):
    """Add a tag to a group. Accepts tag_id or name (find-or-create)."""
    with db.get_session() as session:
        # Resolve tag
        if body.tag_id:
            tag = session.query(Tag).filter(Tag.id == body.tag_id).first()
            if not tag:
                raise HTTPException(status_code=404, detail="Tag not found")
        elif body.name:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Tag name is required")
            tag = session.query(Tag).filter(Tag.name == name).first()
            if not tag:
                tag = Tag(name=name, color="#3B82F6")
                session.add(tag)
                session.flush()
        else:
            raise HTTPException(status_code=400, detail="Provide tag_id or name")

        # Check if already associated
        existing = session.query(PositionGroupTag).filter(
            PositionGroupTag.group_id == group_id,
            PositionGroupTag.tag_id == tag.id,
        ).first()
        if not existing:
            session.add(PositionGroupTag(group_id=group_id, tag_id=tag.id))

        return {"id": tag.id, "name": tag.name, "color": tag.color or "#3B82F6"}


@router.delete("/api/ledger/groups/{group_id}/tags/{tag_id}")
async def remove_tag_from_group(group_id: str, tag_id: int, user_id: str = Depends(get_current_user_id)):
    """Remove a tag association from a group."""
    with db.get_session() as session:
        deleted = session.query(PositionGroupTag).filter(
            PositionGroupTag.group_id == group_id,
            PositionGroupTag.tag_id == tag_id,
        ).delete()
        if not deleted:
            raise HTTPException(status_code=404, detail="Tag association not found")

    return {"message": "Tag removed from group"}
