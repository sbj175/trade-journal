"""
Roll Chain Summary — materialized roll chain statistics.

Rebuilds roll_chain_summaries from position_groups, position_lots, and lot_closings.
100% derived data, safe to delete-and-rebuild on every pipeline run.

Part of OPT-211.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Set

from src.database.models import (
    LotClosing as LotClosingModel,
    PositionGroup,
    PositionGroupLot,
    PositionLot as PositionLotModel,
    RollChainSummary,
)
from src.database.tenant import DEFAULT_USER_ID

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


def populate_roll_chain_summaries(db_manager: "DatabaseManager") -> int:
    """Rebuild roll_chain_summaries from position_groups.

    Walks rolled_from_group_id links to build chains, then computes
    cumulative premium and realized P&L across all lots in each chain.

    Returns the number of summary rows created.
    """
    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        # Clear existing summaries
        session.query(RollChainSummary).filter(
            RollChainSummary.user_id == user_id,
        ).delete()
        session.flush()

        # Load all groups with roll links
        groups = session.query(PositionGroup).all()
        if not groups:
            return 0

        group_map: Dict[str, PositionGroup] = {}
        children_map: Dict[str, List[str]] = defaultdict(list)
        has_parent: Set[str] = set()

        for g in groups:
            group_map[g.group_id] = g
            if g.rolled_from_group_id:
                children_map[g.rolled_from_group_id].append(g.group_id)
                has_parent.add(g.group_id)

        # Find root groups (groups that are parents but have no parent themselves,
        # OR groups that have children)
        root_ids = set()
        for gid in group_map:
            if gid not in has_parent and gid in children_map:
                root_ids.add(gid)
            elif gid not in has_parent and group_map[gid].rolled_from_group_id:
                # Orphan reference — treat as root
                root_ids.add(gid)

        if not root_ids:
            return 0

        # Build chains from each root
        chains: List[List[str]] = []
        for root_id in root_ids:
            chain = []
            queue = [root_id]
            seen = set()
            while queue:
                gid = queue.pop(0)
                if gid in seen:
                    continue
                seen.add(gid)
                chain.append(gid)
                queue.extend(children_map.get(gid, []))
            if len(chain) >= 2:  # Only chains with at least one roll
                chains.append(chain)

        if not chains:
            return 0

        # Collect all group IDs across all chains for batch loading
        all_chain_group_ids = set()
        for chain in chains:
            all_chain_group_ids.update(chain)

        # Batch-load lots for all chain groups
        group_lot_rows = session.query(
            PositionGroupLot.group_id,
            PositionGroupLot.transaction_id,
        ).filter(
            PositionGroupLot.group_id.in_(list(all_chain_group_ids)),
        ).all()

        group_txn_ids: Dict[str, List[str]] = defaultdict(list)
        all_txn_ids = set()
        for gid, txn_id in group_lot_rows:
            group_txn_ids[gid].append(txn_id)
            all_txn_ids.add(txn_id)

        # Load lots by transaction_id
        lot_map: Dict[str, PositionLotModel] = {}
        if all_txn_ids:
            lots = session.query(PositionLotModel).filter(
                PositionLotModel.transaction_id.in_(list(all_txn_ids)),
            ).all()
            for lot in lots:
                lot_map[lot.transaction_id] = lot

        # Load all closings for those lots
        lot_ids = [lot.id for lot in lot_map.values()]
        closings_by_lot: Dict[int, List[LotClosingModel]] = defaultdict(list)
        if lot_ids:
            closings = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id.in_(lot_ids),
            ).all()
            for c in closings:
                closings_by_lot[c.lot_id].append(c)

        # Build summaries
        count = 0
        for chain in chains:
            root = group_map[chain[0]]
            current = group_map[chain[-1]]

            # Compute cumulative premium and P&L across all groups in chain
            cumulative_premium = 0.0
            cumulative_realized_pnl = 0.0

            for gid in chain:
                for txn_id in group_txn_ids.get(gid, []):
                    lot = lot_map.get(txn_id)
                    if not lot:
                        continue
                    # Premium: entry_price * quantity * multiplier
                    multiplier = 100 if lot.instrument_type == 'EQUITY_OPTION' else 1
                    if lot.entry_price and lot.original_quantity:
                        cumulative_premium += abs(lot.entry_price) * abs(lot.original_quantity) * multiplier
                    # Realized P&L from closings
                    for c in closings_by_lot.get(lot.id, []):
                        cumulative_realized_pnl += c.realized_pnl

            # Find last_rolled date (opening_date of the most recent non-root group)
            last_rolled = None
            if len(chain) >= 2:
                last_group = group_map[chain[-1]]
                last_rolled = last_group.opening_date

            summary = RollChainSummary(
                user_id=user_id,
                root_group_id=root.group_id,
                current_group_id=current.group_id,
                underlying=root.underlying or '',
                account_number=root.account_number or '',
                chain_length=len(chain),
                roll_count=len(chain) - 1,
                first_opened=root.opening_date,
                last_rolled=last_rolled,
                cumulative_premium=cumulative_premium,
                cumulative_realized_pnl=cumulative_realized_pnl,
            )
            session.add(summary)
            count += 1

        session.flush()
        return count
