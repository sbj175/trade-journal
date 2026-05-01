"""Ledger routes — position groups CRUD and lot management."""

import uuid as _uuid
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import PnlEvent, PositionGroup, PositionGroupLot, PositionGroupTag, PositionLot as PositionLotModel, RawTransaction, RollChainSummary, Tag
from src.database.db_manager import DatabaseManager
from src.models.lot_manager import LotManager
from src.utils.premium import group_premium_from_lots
from src.dependencies import get_db, get_lot_manager, get_current_user_id
from src.schemas import LedgerGroupUpdate, LedgerMoveLots, LedgerCreateGroup, GroupTagAdd
from src.services.ledger_service import seed_position_groups, _refresh_group_status
from src.services.roll_timeline import compute_roll_timeline

router = APIRouter()


def _txn_components(txn_id):
    """Split a (possibly comma-separated) transaction_id into its
    component ids. The lot manager combines multiple same-price fills
    into one lot whose `transaction_id` is the comma-joined list of
    underlying fill ids — fee lookups need to decompose this back into
    individual ids to find each fill's row in `raw_transactions`.
    """
    return [t.strip() for t in (txn_id or '').split(',') if t.strip()]


def compute_lot_fee_breakdown(
    *, lot, lot_closings, fees_by_txn, closing_txn_total_qty,
):
    """Per-lot fee breakdown for the Ledger response.

    Returns ``(opening_fees, closing_fees_per_lot_closing)``.

    Opening fee sums over component transactions when the lot represents
    combined same-price fills. Each closing record's fee is the closing
    transaction's total fee apportioned by this closing's quantity_closed
    (one BTC transaction can close multiple lots; the fee belongs to the
    transaction, not to any single lot).
    """
    opening_fees = sum(
        fees_by_txn.get(tid, 0) for tid in _txn_components(lot.transaction_id)
    )
    closing_fees = []
    for c in lot_closings:
        if not c.closing_transaction_id:
            closing_fees.append(0)
            continue
        txn_fee = fees_by_txn.get(c.closing_transaction_id, 0)
        txn_total_qty = closing_txn_total_qty.get(c.closing_transaction_id, 0)
        if txn_total_qty and c.quantity_closed:
            closing_fees.append(round(
                txn_fee * abs(c.quantity_closed) / txn_total_qty, 4,
            ))
        else:
            closing_fees.append(0)
    return opening_fees, closing_fees


@router.get("/api/ledger")
async def get_ledger(account_number: str = '', underlying: str = '', db: DatabaseManager = Depends(get_db), lot_manager: LotManager = Depends(get_lot_manager), user_id: str = Depends(get_current_user_id)):
    """Main Ledger data endpoint — returns position groups with lots and derived orders."""

    # Auto-seed if position_groups is empty
    with db.get_session() as session:
        group_count = session.query(func.count()).select_from(PositionGroup).scalar()
        if group_count == 0:
            lot_count = session.query(func.count()).select_from(PositionLotModel).scalar()
            if lot_count > 0:
                seed_position_groups(db=db, lot_manager=lot_manager)

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

    # Batch-load roll source IDs (groups that have something rolled FROM them)
    # and parent pointers so we can walk each chain back to its root.
    with db.get_session() as session:
        parent_rows = session.query(
            PositionGroup.group_id,
            PositionGroup.rolled_from_group_id,
        ).filter(
            PositionGroup.rolled_from_group_id.isnot(None),
        ).all()
        parent_of: Dict[str, str] = {gid: parent for gid, parent in parent_rows}
        roll_source_ids = set(parent_of.values())

    # Walk each group back to its chain root so we can look up the
    # chain summary (keyed by root_group_id) regardless of where in the
    # chain this particular group sits.
    def _chain_root(gid: str) -> str:
        seen = set()
        while gid in parent_of and gid not in seen:
            seen.add(gid)
            gid = parent_of[gid]
        return gid

    group_root = {gid: _chain_root(gid) for gid in group_ids}
    root_ids = list({r for r in group_root.values() if r})

    roll_chain_by_group: Dict[str, dict] = {}
    if root_ids:
        with db.get_session() as session:
            # Materialize inside the session — the instances are detached
            # once we exit the `with` block.
            rc_by_root = {
                rc.root_group_id: {
                    'root_group_id': rc.root_group_id,
                    'chain_length': rc.chain_length,
                    'roll_count': rc.roll_count,
                    'first_opened': rc.first_opened,
                    'last_rolled': rc.last_rolled,
                }
                for rc in session.query(RollChainSummary).filter(
                    RollChainSummary.root_group_id.in_(root_ids),
                ).all()
            }
        for gid, root in group_root.items():
            summary = rc_by_root.get(root)
            if summary:
                roll_chain_by_group[gid] = summary

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

    # Batch-load fees from RawTransaction for opening + closing transaction IDs.
    # A lot's transaction_id can be a comma-separated string when the lot
    # manager combined multiple same-price fills into one lot — split so
    # each component shows up in the fee lookup.
    all_txn_ids: set = set()
    for lots in lots_by_group.values():
        for lot in lots:
            for tid in _txn_components(lot.transaction_id):
                all_txn_ids.add(tid)
    for lot_closings in closings_by_lot.values():
        for c in lot_closings:
            if c.closing_transaction_id:
                all_txn_ids.add(c.closing_transaction_id)

    fees_by_txn: Dict[str, float] = {}
    if all_txn_ids:
        with db.get_session() as session:
            fee_rows = session.query(
                RawTransaction.id,
                RawTransaction.commission,
                RawTransaction.regulatory_fees,
                RawTransaction.clearing_fees,
            ).filter(
                RawTransaction.id.in_(list(all_txn_ids)),
            ).all()
            for txn_id, commission, reg_fees, clearing in fee_rows:
                total = (commission or 0) + (reg_fees or 0) + (clearing or 0)
                fees_by_txn[txn_id] = round(total, 4)

    # Pre-compute the total quantity closed per closing_transaction_id —
    # one BTC transaction can close multiple lots, and the fee on that
    # one transaction must be apportioned across the closings by their
    # quantity_closed (not credited to every lot in full).
    closing_txn_total_qty: Dict[str, int] = {}
    for lot_closings in closings_by_lot.values():
        for c in lot_closings:
            if c.closing_transaction_id and c.quantity_closed:
                closing_txn_total_qty[c.closing_transaction_id] = (
                    closing_txn_total_qty.get(c.closing_transaction_id, 0)
                    + abs(c.quantity_closed)
                )

    # Build response
    result = []
    for g in groups_raw:
        gid = g['group_id']
        lots = lots_by_group.get(gid, [])

        lots_data = []
        total_realized = 0.0
        total_fees = 0.0
        open_lot_count = 0

        for lot in lots:
            lot_closings = closings_by_lot.get(lot.id, [])
            lot_realized = sum(c.realized_pnl for c in lot_closings)
            total_realized += lot_realized

            multiplier = 100 if lot.option_type else 1
            # Positive = credit received (short), negative = debit paid (long)
            cost_basis = abs(lot.entry_price * lot.original_quantity * multiplier)
            if lot.quantity > 0:
                cost_basis = -cost_basis  # long positions are debits

            is_open = lot.remaining_quantity != 0 and lot.status != 'CLOSED'
            if is_open:
                open_lot_count += 1

            closings_data = []
            opening_fees, per_closing_fees = compute_lot_fee_breakdown(
                lot=lot, lot_closings=lot_closings,
                fees_by_txn=fees_by_txn,
                closing_txn_total_qty=closing_txn_total_qty,
            )
            lot_total_fees = opening_fees
            for c, closing_fees in zip(lot_closings, per_closing_fees):
                lot_total_fees += closing_fees
                closings_data.append({
                    'closing_id': c.closing_id,
                    'quantity_closed': c.quantity_closed,
                    'closing_price': c.closing_price,
                    'closing_date': str(c.closing_date) if c.closing_date else None,
                    'closing_type': c.closing_type,
                    'realized_pnl': c.realized_pnl,
                    'fees': closing_fees,
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
                'fees': round(lot_total_fees, 4),
                'opening_fees': opening_fees,
                'closings': closings_data,
            })
            total_fees += lot_total_fees

        rolled_from = g.get('rolled_from_group_id')
        has_roll_chain = bool(rolled_from) or (gid in roll_source_ids)

        # OPT-263: walk-and-balance roll detection for same-exp rolls within this group
        roll_timeline = compute_roll_timeline(lots_data)

        result.append({
            'group_id': gid,
            'underlying': g['underlying'],
            'strategy_label': g['strategy_label'],
            'status': g['status'],
            'account_number': g['account_number'],
            'opening_date': g['opening_date'],
            'closing_date': g['closing_date'],
            'last_activity_date': g.get('last_activity_date'),
            'rolled_from_group_id': rolled_from,
            'has_roll_chain': has_roll_chain,
            'total_pnl': total_realized,
            'realized_pnl': total_realized,
            'unrealized_pnl': 0.0,
            'total_fees': round(total_fees, 4),
            'lot_count': len(lots),
            'open_lot_count': open_lot_count,
            'lots': lots_data,
            'tags': tags_by_group.get(gid, []),
            'current_strike_label': roll_timeline['current_strike_label'],
            'roll_count': roll_timeline['roll_count'],
            'roll_timeline': roll_timeline,
            'roll_chain': roll_chain_by_group.get(gid),
        })

    return result


@router.get("/api/ledger/group-roll-chain/{group_id}")
async def get_group_roll_chain(
    group_id: str,
    db: DatabaseManager = Depends(get_db),
    lot_manager: LotManager = Depends(get_lot_manager),
    user_id: str = Depends(get_current_user_id),
):
    """Walk the roll chain for a group, returning all linked groups in order."""

    with db.get_session() as session:
        # Verify the starting group exists
        start = session.query(PositionGroup).filter(
            PositionGroup.group_id == group_id,
        ).first()
        if not start:
            raise HTTPException(status_code=404, detail="Group not found")

        # The chain runs root → ... → clicked group → ... → leaf. We walk
        # backward to root via rolled_from_group_id (linear by schema —
        # each group has at most one parent), then forward from the
        # clicked group to a leaf via children. At a forward branch
        # (clicked group has multiple children, e.g., a partition into
        # two same-shape positions), we pick the child whose own chain
        # leaf opened most recently — the trader's most active
        # continuation. The frontend can highlight the requested group
        # within the result; the modal isn't truncated at midpoint
        # clicks.
        chain_back: List[str] = [start.group_id]
        current = start
        visited = {current.group_id}
        while current.rolled_from_group_id:
            parent = session.query(PositionGroup).filter(
                PositionGroup.group_id == current.rolled_from_group_id,
            ).first()
            if not parent or parent.group_id in visited:
                break
            visited.add(parent.group_id)
            chain_back.append(parent.group_id)
            current = parent

        chain_forward: List[str] = []
        cur_id = start.group_id
        while True:
            children = session.query(PositionGroup).filter(
                PositionGroup.rolled_from_group_id == cur_id,
            ).all()
            children = [c for c in children if c.group_id not in visited]
            if not children:
                break
            children.sort(key=lambda c: c.opening_date or '', reverse=True)
            picked = children[0]
            visited.add(picked.group_id)
            chain_forward.append(picked.group_id)
            cur_id = picked.group_id

        chain_ids = list(reversed(chain_back)) + chain_forward

        # Load groups for the chain — convert to dicts inside session
        chain_groups = session.query(PositionGroup).filter(
            PositionGroup.group_id.in_(chain_ids),
        ).all()
        group_map = {}
        for g in chain_groups:
            group_map[g.group_id] = {
                'underlying': g.underlying,
                'strategy_label': g.strategy_label,
                'status': g.status,
                'opening_date': g.opening_date,
                'closing_date': g.closing_date,
                'rolled_from_group_id': g.rolled_from_group_id,
            }

    # Load lots for realized P&L calculation
    lots_by_group = lot_manager.get_lots_for_groups_batch(chain_ids)
    all_lot_ids = []
    for lots in lots_by_group.values():
        for lot in lots:
            all_lot_ids.append(lot.id)
    closings_by_lot = lot_manager.get_lot_closings_batch(all_lot_ids) if all_lot_ids else {}

    # Compute lot-to-chain attribution so per-row realized/premium reflect
    # only the lots attributed to THIS chain (OPT-284 Phase 3c). Matters
    # at branching source groups — without this, both children's modals
    # would over-credit the shared trunk.
    from collections import defaultdict
    from src.pipeline.lot_lineage import build_chain_attribution
    leaf_id = chain_ids[-1] if chain_ids else None
    use_attribution = False
    attributed_lot_ids: set = set()
    if leaf_id:
        with db.get_session() as session:
            all_groups = session.query(PositionGroup).all()
            grp_map = {g.group_id: g for g in all_groups}
            children_map_full: Dict[str, List[str]] = defaultdict(list)
            for g in all_groups:
                if g.rolled_from_group_id:
                    children_map_full[g.rolled_from_group_id].append(g.group_id)
            all_lots = session.query(PositionLotModel).all()
            lots_by_id = {l.id: l for l in all_lots}
            txn_to_group: Dict[str, str] = {}
            for gid, txn in session.query(
                PositionGroupLot.group_id, PositionGroupLot.transaction_id,
            ).all():
                txn_to_group[txn] = gid
            # Run attribution INSIDE the session — it lazy-loads ORM
            # attributes (rolled_from_group_id, parent_lot_id, etc.) and
            # would raise DetachedInstanceError if invoked after the
            # session closes.
            chains_by_leaf, lot_to_leaf = build_chain_attribution(
                group_map=grp_map, children_map=children_map_full,
                lots_by_id=lots_by_id, txn_to_group=txn_to_group,
            )
        # Attribution only applies when the requested group is the leaf
        # of an actual chain. When the user opens the modal from a
        # mid-chain CLOSED group, leaf_id is that midpoint, not a real
        # chain leaf — there are no lots attributed to that key, and
        # filtering would zero out every per-row total. Fall back to the
        # legacy per-group sum in that case.
        if leaf_id in chains_by_leaf:
            use_attribution = True
            attributed_lot_ids = {
                lid for lid, lf in lot_to_leaf.items() if lf == leaf_id
            }

    # Build ordered response
    chain_result = []
    cumulative_pnl = 0.0
    for gid in chain_ids:
        g = group_map.get(gid)
        if not g:
            continue
        lots = lots_by_group.get(gid, [])
        # When the modal was opened from a chain leaf, filter to lots
        # attributed to THIS chain (so branching scenarios don't
        # over-credit the trunk). When opened from a midpoint or a
        # group that isn't a chain leaf, fall back to the per-group
        # sum — there's no single chain to attribute to.
        chain_lots = (
            [l for l in lots if l.id in attributed_lot_ids]
            if use_attribution
            else lots
        )
        realized = sum(
            sum(c.realized_pnl for c in closings_by_lot.get(lot.id, []))
            for lot in chain_lots
        )
        premium = group_premium_from_lots(chain_lots)
        cumulative_pnl += realized
        chain_result.append({
            'group_id': gid,
            **g,
            'premium': premium,
            'realized_pnl': realized,
            'cumulative_pnl': cumulative_pnl,
            'lot_count': len(chain_lots),
        })

    # Net Premium = sum of realized P&L from closed groups + premium of current (last) group
    net_premium = cumulative_pnl
    if chain_result:
        net_premium = sum(
            item['realized_pnl'] for item in chain_result[:-1]
        ) + chain_result[-1]['premium']

    # Unrealized P&L for the current (open) group from cached quotes
    unrealized_pnl = None
    if chain_ids:
        current_gid = chain_ids[-1]
        current_lots = lots_by_group.get(current_gid, [])
        open_lots = [l for l in current_lots if l.remaining_quantity != 0 and l.status != 'CLOSED']
        if open_lots:
            symbols = list({l.symbol for l in open_lots})
            quotes = db.get_cached_quotes(symbols)
            if quotes:
                unrealized_pnl = 0.0
                for lot in open_lots:
                    quote = quotes.get(lot.symbol)
                    mark = quote.get('mark') if quote else None
                    if mark is None:
                        continue
                    multiplier = 100 if lot.instrument_type == 'EQUITY_OPTION' else 1
                    qty = abs(lot.remaining_quantity)
                    market_value = mark * qty * multiplier
                    cost = abs(lot.entry_price) * qty * multiplier if lot.entry_price else 0
                    if lot.quantity < 0:  # Short
                        unrealized_pnl += cost - market_value
                    else:  # Long
                        unrealized_pnl += market_value - cost

    return {
        'root_group_id': chain_ids[0] if chain_ids else group_id,
        'chain_length': len(chain_result),
        'net_premium': net_premium,
        'unrealized_pnl': unrealized_pnl,
        'chain': chain_result,
    }


@router.post("/api/ledger/seed")
async def seed_ledger(db: DatabaseManager = Depends(get_db), lot_manager: LotManager = Depends(get_lot_manager), user_id: str = Depends(get_current_user_id)):
    """Explicitly seed position groups from existing chains."""
    count = seed_position_groups(db=db, lot_manager=lot_manager)
    return {"message": f"Seeded {count} position groups", "groups_created": count}


@router.put("/api/ledger/groups/{group_id}")
async def update_ledger_group(group_id: str, body: LedgerGroupUpdate, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Update group metadata (strategy label)."""
    with db.get_session() as session:
        row = session.query(PositionGroup).filter(
            PositionGroup.group_id == group_id,
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Group not found")

        if body.strategy_label is not None:
            row.strategy_label = body.strategy_label
            row.strategy_label_user_override = True
            row.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return {"message": "Group updated"}


@router.post("/api/ledger/move-lots")
async def move_lots(body: LedgerMoveLots, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
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

        # Update pnl_events.group_id for moved lots
        moved_lot_ids = [
            r[0] for r in session.query(PositionLotModel.id).filter(
                PositionLotModel.transaction_id.in_(body.transaction_ids),
            ).all()
        ]
        if moved_lot_ids:
            session.query(PnlEvent).filter(
                PnlEvent.lot_id.in_(moved_lot_ids),
                PnlEvent.user_id == user_id,
            ).update({"group_id": body.target_group_id}, synchronize_session=False)

        # Refresh target group status
        _refresh_group_status(body.target_group_id, session=session, db=db)

        # Clean up source groups: delete if empty, refresh otherwise
        for gid in source_groups:
            if gid == body.target_group_id:
                continue
            remaining = session.query(func.count()).select_from(
                PositionGroupLot,
            ).filter(PositionGroupLot.group_id == gid).scalar()
            if remaining == 0:
                session.query(PositionGroup).filter(
                    PositionGroup.group_id == gid,
                ).delete(synchronize_session=False)
                logger.info(f"Deleted empty source group {gid}")
            else:
                _refresh_group_status(gid, session=session, db=db)

    return {"message": f"Moved {len(body.transaction_ids)} lots"}


@router.post("/api/ledger/groups")
async def create_ledger_group(body: LedgerCreateGroup, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
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
async def delete_ledger_group(group_id: str, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
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
async def add_tag_to_group(group_id: str, body: GroupTagAdd, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
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
async def remove_tag_from_group(group_id: str, tag_id: int, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Remove a tag association from a group."""
    with db.get_session() as session:
        from src.database.tenant import DEFAULT_USER_ID
        uid = session.info.get("user_id", DEFAULT_USER_ID)
        deleted = session.query(PositionGroupTag).filter(
            PositionGroupTag.group_id == group_id,
            PositionGroupTag.tag_id == tag_id,
            PositionGroupTag.user_id == uid,
        ).delete()
        if not deleted:
            raise HTTPException(status_code=404, detail="Tag association not found")

    return {"message": "Tag removed from group"}
