"""Ledger routes — position groups CRUD and lot management."""

import uuid as _uuid
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import PnlEvent, PositionGroup, PositionGroupLot, PositionGroupTag, PositionLot as PositionLotModel, RawTransaction, Tag
from src.database.db_manager import DatabaseManager
from src.models.lot_manager import LotManager
from src.dependencies import get_db, get_lot_manager, get_current_user_id
from src.schemas import LedgerGroupUpdate, LedgerMoveLots, LedgerCreateGroup, GroupTagAdd
from src.services.ledger_service import seed_position_groups, _refresh_group_status

router = APIRouter()


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
    with db.get_session() as session:
        roll_source_ids = {
            row[0] for row in session.query(
                PositionGroup.rolled_from_group_id,
            ).filter(
                PositionGroup.rolled_from_group_id.isnot(None),
            ).all()
        }

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

    # Batch-load fees from RawTransaction for opening + closing transaction IDs
    all_txn_ids = set()
    for lots in lots_by_group.values():
        for lot in lots:
            if lot.transaction_id:
                all_txn_ids.add(lot.transaction_id)
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
            lot_total_fees = fees_by_txn.get(lot.transaction_id, 0)
            for c in lot_closings:
                closing_fees = fees_by_txn.get(c.closing_transaction_id, 0) if c.closing_transaction_id else 0
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
                'opening_fees': fees_by_txn.get(lot.transaction_id, 0),
                'closings': closings_data,
            })
            total_fees += lot_total_fees

        rolled_from = g.get('rolled_from_group_id')
        has_roll_chain = bool(rolled_from) or (gid in roll_source_ids)

        # Detect partial roll: open lots from multiple opening orders on same chain
        lot_chain_ids = {lot.chain_id for lot in lots if lot.chain_id}
        open_order_ids = {lot.opening_order_id for lot in lots
                          if lot.remaining_quantity != 0 and lot.opening_order_id}
        partially_rolled = len(lot_chain_ids) == 1 and len(open_order_ids) > 1

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
            'partially_rolled': partially_rolled,
            'lots': lots_data,
            'tags': tags_by_group.get(gid, []),
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

        # Walk backward to find the root
        current = start
        visited = {current.group_id}
        while current.rolled_from_group_id:
            parent = session.query(PositionGroup).filter(
                PositionGroup.group_id == current.rolled_from_group_id,
            ).first()
            if not parent or parent.group_id in visited:
                break
            visited.add(parent.group_id)
            current = parent
        root_id = current.group_id

        # Walk forward from root to build the full chain
        # Build a reverse lookup: rolled_from_group_id -> group_id
        all_links = session.query(
            PositionGroup.group_id,
            PositionGroup.rolled_from_group_id,
        ).filter(
            PositionGroup.rolled_from_group_id.isnot(None),
        ).all()
        forward_map: Dict[str, List[str]] = defaultdict(list)
        for gid, rfgid in all_links:
            forward_map[rfgid].append(gid)

        chain_ids = []
        queue = [root_id]
        seen = set()
        while queue:
            gid = queue.pop(0)
            if gid in seen:
                continue
            seen.add(gid)
            chain_ids.append(gid)
            # Add children sorted by opening_date
            children = forward_map.get(gid, [])
            queue.extend(children)

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

    # Build ordered response
    chain_result = []
    cumulative_pnl = 0.0
    for gid in chain_ids:
        g = group_map.get(gid)
        if not g:
            continue
        lots = lots_by_group.get(gid, [])
        realized = sum(
            sum(c.realized_pnl for c in closings_by_lot.get(lot.id, []))
            for lot in lots
        )
        # Initial premium for this group's lots
        premium = 0.0
        for lot in lots:
            multiplier = 100 if lot.instrument_type == 'EQUITY_OPTION' else 1
            if lot.entry_price and lot.original_quantity:
                premium += abs(lot.entry_price) * abs(lot.original_quantity) * multiplier
        cumulative_pnl += realized
        chain_result.append({
            'group_id': gid,
            **g,
            'premium': premium,
            'realized_pnl': realized,
            'cumulative_pnl': cumulative_pnl,
            'lot_count': len(lots),
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


@router.get("/api/ledger/suggestions")
async def get_ledger_suggestions(
    account_number: str = '',
    db: DatabaseManager = Depends(get_db),
    lot_manager: LotManager = Depends(get_lot_manager),
    user_id: str = Depends(get_current_user_id),
):
    """Detect potential multi-group strategies and return merge suggestions."""
    from src.pipeline.strategy_engine import recognize, lots_to_legs
    from src.pipeline.strategy_engine.constants import STRATEGIES

    # Load OPEN groups
    with db.get_session() as session:
        q = session.query(PositionGroup).filter(PositionGroup.status == 'OPEN')
        if account_number:
            q = q.filter(PositionGroup.account_number == account_number)
        open_groups = [row.to_dict() for row in q.all()]

    if not open_groups:
        return {"suggestions": []}

    group_ids = [g['group_id'] for g in open_groups]

    # Batch-load lots for all open groups
    lots_by_group = lot_manager.get_lots_for_groups_batch(group_ids)

    # Group by (account, underlying)
    by_au: Dict[tuple, List[dict]] = defaultdict(list)
    for g in open_groups:
        by_au[(g['account_number'], g['underlying'])].append(g)

    def _is_more_specific(combined_name: str, individual_names: List[str]) -> bool:
        """True if the combined strategy is genuinely more specific.

        Rejects cases where the combined result merely matches one of the
        inputs (e.g., Shares + Bull Put Spread → Bull Put Spread is not
        a meaningful merge).
        """
        if combined_name.startswith("Custom"):
            return False
        if combined_name not in STRATEGIES:
            return False
        # The combined name must differ from ALL individual names
        if any(n == combined_name for n in individual_names):
            return False
        return True

    consolidation_suggestions = []
    strategy_suggestions = []

    for (acct, underlying), au_groups in by_au.items():
        if len(au_groups) < 2:
            continue

        # --- Phase 1: Consolidation suggestions ---
        # Groups with the same strategy label should be merged into one.
        by_label: Dict[str, List[dict]] = defaultdict(list)
        for g in au_groups:
            by_label[g['strategy_label'] or 'Unknown'].append(g)

        for label, same_label_groups in by_label.items():
            if len(same_label_groups) < 2:
                continue

            # Sort by opening date so the earliest group is the target
            same_label_groups.sort(key=lambda g: g['opening_date'] or '')

            total_lots = sum(
                len(lots_by_group.get(g['group_id'], []))
                for g in same_label_groups
            )
            gids = [g['group_id'] for g in same_label_groups]
            suggestion_id = _uuid.uuid5(
                _uuid.NAMESPACE_DNS,
                'consolidate:' + ','.join(sorted(gids)),
            ).hex[:12]

            consolidation_suggestions.append({
                'id': suggestion_id,
                'type': 'consolidate',
                'resulting_strategy': label,
                'underlying': underlying,
                'account_number': acct,
                'groups': [
                    {
                        'group_id': g['group_id'],
                        'strategy_label': g['strategy_label'],
                        'status': g['status'],
                        'opening_date': g['opening_date'],
                        'lot_count': len(lots_by_group.get(g['group_id'], [])),
                    }
                    for g in same_label_groups
                ],
                'description': (
                    f"{underlying}: Consolidate {len(same_label_groups)} "
                    f"{label} groups ({total_lots} lots)"
                ),
            })

        # --- Phase 2: Strategy merge suggestions ---
        # Try pairwise first, then 3-wise, up to 4-wise
        max_combo_size = min(len(au_groups), 4)
        already_suggested_sets = set()
        # Deduplicate: for each resulting strategy, keep only the best combo
        # (smallest date spread between groups = most likely intentional pairing)
        best_by_strategy: Dict[str, dict] = {}

        for combo_size in range(2, max_combo_size + 1):
            for combo in combinations(au_groups, combo_size):
                combo_gids = frozenset(g['group_id'] for g in combo)

                # Skip if a subset was already a valid suggestion
                if any(s.issubset(combo_gids) for s in already_suggested_sets):
                    continue

                # Combine all lots from the groups in the combo
                combined_lots = []
                for g in combo:
                    combined_lots.extend(lots_by_group.get(g['group_id'], []))

                if not combined_lots:
                    continue

                # Run strategy engine on combined lots
                legs = lots_to_legs(combined_lots)
                if not legs:
                    continue

                sr = recognize(legs)
                individual_names = [g['strategy_label'] or 'Unknown' for g in combo]

                if _is_more_specific(sr.name, individual_names):
                    # Score by date proximity (smaller = better)
                    dates = [g['opening_date'] or '' for g in combo]
                    date_spread = max(dates) if dates else ''
                    if date_spread and min(dates):
                        date_spread = date_spread  # just use max date as tiebreak

                    combo_gids_sorted = sorted(combo_gids)
                    suggestion_id = _uuid.uuid5(
                        _uuid.NAMESPACE_DNS,
                        ','.join(combo_gids_sorted),
                    ).hex[:12]

                    labels_str = ' + '.join(individual_names)
                    entry = {
                        'id': suggestion_id,
                        'type': 'merge',
                        'resulting_strategy': sr.name,
                        'underlying': underlying,
                        'account_number': acct,
                        'groups': [
                            {
                                'group_id': g['group_id'],
                                'strategy_label': g['strategy_label'],
                                'status': g['status'],
                                'opening_date': g['opening_date'],
                                'lot_count': len(lots_by_group.get(g['group_id'], [])),
                            }
                            for g in combo
                        ],
                        'description': f"{underlying}: {labels_str} \u2192 {sr.name}",
                        '_date_spread': dates,
                    }

                    # Keep only the best combo per strategy name
                    # (closest opening dates = most likely to be intentional)
                    prev = best_by_strategy.get(sr.name)
                    if prev is None:
                        best_by_strategy[sr.name] = entry
                        already_suggested_sets.add(combo_gids)
                    else:
                        # Prefer combo whose groups have dates closest together
                        prev_dates = prev['_date_spread']
                        prev_range = (max(prev_dates) or '') if prev_dates else ''
                        new_range = (max(dates) or '') if dates else ''
                        # More recent pairing wins (latest opening date)
                        if new_range > prev_range:
                            # Remove old combo from already_suggested
                            old_gids = frozenset(
                                g['group_id'] for g in prev['groups']
                            )
                            already_suggested_sets.discard(old_gids)
                            best_by_strategy[sr.name] = entry
                            already_suggested_sets.add(combo_gids)

        for entry in best_by_strategy.values():
            entry.pop('_date_spread', None)
            strategy_suggestions.append(entry)

    # Consolidation first, then strategy merges
    return {"suggestions": consolidation_suggestions + strategy_suggestions}


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
