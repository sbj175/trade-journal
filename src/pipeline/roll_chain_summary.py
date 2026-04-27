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

from src.utils.premium import lot_premium

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

        for g in groups:
            group_map[g.group_id] = g
            if g.rolled_from_group_id:
                children_map[g.rolled_from_group_id].append(g.group_id)

        # Per spec §5.2 the rolled_from graph is a tree, not a linked list:
        # a single source can have multiple children (parallel rolls). We
        # produce one summary row per leaf (group with no children in the
        # tree), walking back via rolled_from_group_id to construct the
        # unique root→leaf path. Shared upstream history appears in
        # multiple chains — that's correct, since each leaf is its own
        # continuation of the same source.
        chains: List[List[str]] = []
        for gid, g in group_map.items():
            if gid in children_map:
                continue  # not a leaf
            if not g.rolled_from_group_id:
                continue  # standalone group, no rolls
            chain: List[str] = []
            cur = gid
            seen: Set[str] = set()
            while cur and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                parent_g = group_map.get(cur)
                cur = parent_g.rolled_from_group_id if parent_g else None
            chain.reverse()  # root → leaf order
            if len(chain) >= 2:
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

            # Compute net premium and cumulative P&L across all groups in chain
            # Net Premium = realized P&L from closed groups + initial premium of current (open) group
            cumulative_realized_pnl = 0.0
            per_group_realized: dict = {}
            per_group_premium: dict = {}

            for gid in chain:
                group_realized = 0.0
                group_premium = 0.0
                for txn_id in group_txn_ids.get(gid, []):
                    lot = lot_map.get(txn_id)
                    if not lot:
                        continue
                    group_premium += lot_premium(lot)
                    for c in closings_by_lot.get(lot.id, []):
                        group_realized += c.realized_pnl
                per_group_realized[gid] = group_realized
                per_group_premium[gid] = group_premium
                cumulative_realized_pnl += group_realized

            # Net premium = sum of realized P&L from all closed groups + premium of current group
            current_gid = chain[-1]
            net_premium = sum(
                per_group_realized[gid] for gid in chain[:-1]
            ) + per_group_premium[current_gid]

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
                cumulative_premium=net_premium,
                cumulative_realized_pnl=cumulative_realized_pnl,
            )
            session.add(summary)
            count += 1

        session.flush()
        return count
