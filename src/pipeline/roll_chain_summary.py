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

        # Per spec §5.2 / OPT-282 the group-level rolled_from graph can
        # branch (one source group may have multiple children when its
        # lots paired with lots in different new groups). We produce one
        # summary row per leaf (group with no children), walking back via
        # rolled_from_group_id to construct the unique root→leaf path.
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

        # Batch-load lots for the leaf groups (we'll walk lot lineage
        # backward from there) and for any group in a chain (for the
        # group-level metadata only).
        all_chain_group_ids = set()
        for chain in chains:
            all_chain_group_ids.update(chain)

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

        # Load lots both by transaction_id (for grouping) and by id (for
        # walking parent_lot_id lineage). Include all lots in any chain
        # group AND all their ancestors (which may not be in a chain
        # group themselves — though typically they are).
        lots_by_txn: Dict[str, PositionLotModel] = {}
        lots_by_id: Dict[int, PositionLotModel] = {}
        if all_txn_ids:
            seed_lots = session.query(PositionLotModel).filter(
                PositionLotModel.transaction_id.in_(list(all_txn_ids)),
            ).all()
            for lot in seed_lots:
                lots_by_txn[lot.transaction_id] = lot
                lots_by_id[lot.id] = lot

        # Pull in any ancestor lots that weren't already loaded.
        # (A leaf group's lots' parent chain may include lots from groups
        # not in any chain, e.g., an orphan source — defensive load.)
        missing_parent_ids: Set[int] = set()
        for lot in list(lots_by_id.values()):
            pid = lot.parent_lot_id
            while pid is not None and pid not in lots_by_id and pid not in missing_parent_ids:
                missing_parent_ids.add(pid)
                pid = None  # placeholder; we'll re-resolve after the batch load
        if missing_parent_ids:
            extra = session.query(PositionLotModel).filter(
                PositionLotModel.id.in_(list(missing_parent_ids)),
            ).all()
            for lot in extra:
                lots_by_id[lot.id] = lot
            # One more sweep in case ancestors have ancestors not yet loaded.
            for lot in extra:
                cur_pid = lot.parent_lot_id
                while cur_pid is not None and cur_pid not in lots_by_id:
                    parent = session.query(PositionLotModel).filter_by(
                        id=cur_pid,
                    ).first()
                    if not parent:
                        break
                    lots_by_id[parent.id] = parent
                    cur_pid = parent.parent_lot_id

        # Closings for every lot we know about — covers leaf-group lots
        # and all their ancestors.
        closings_by_lot: Dict[int, List[LotClosingModel]] = defaultdict(list)
        if lots_by_id:
            closings = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id.in_(list(lots_by_id.keys())),
            ).all()
            for c in closings:
                closings_by_lot[c.lot_id].append(c)

        # Build summaries
        count = 0
        for chain in chains:
            root = group_map[chain[0]]
            current = group_map[chain[-1]]

            # Walk lot-level lineage from each leaf-group lot to compute
            # cumulative metrics. This is the OPT-284 fix: when group A
            # branches into B and C (A's 5 lots split 3+2), B's chain
            # totals include only the 3 source lots that paired with B,
            # and C's totals include only the 2 that paired with C — no
            # double-counting of the trunk across sibling chains.
            leaf_txns = group_txn_ids.get(chain[-1], [])
            leaf_lots = [lots_by_txn[t] for t in leaf_txns if t in lots_by_txn]
            leaf_lot_ids = {l.id for l in leaf_lots}

            lineage_lot_ids: Set[int] = set()
            for lot in leaf_lots:
                cur = lot
                seen_ids: Set[int] = set()
                while cur and cur.id not in seen_ids:
                    seen_ids.add(cur.id)
                    lineage_lot_ids.add(cur.id)
                    cur = lots_by_id.get(cur.parent_lot_id) if cur.parent_lot_id else None

            # Cumulative realized P&L = sum of realized_pnl over every
            # closing on every lot in the lineage. Each lot is in exactly
            # one chain's lineage (lot has at most one parent), so sums
            # across summaries are additive.
            cumulative_realized_pnl = 0.0
            for lid in lineage_lot_ids:
                for c in closings_by_lot.get(lid, []):
                    cumulative_realized_pnl += c.realized_pnl

            # Net premium = realized P&L of all CLOSED ancestor lots in
            # the lineage + initial premium of the open leaf-group lots.
            net_premium = 0.0
            ancestor_lot_ids = lineage_lot_ids - leaf_lot_ids
            for lid in ancestor_lot_ids:
                for c in closings_by_lot.get(lid, []):
                    net_premium += c.realized_pnl
            for lot in leaf_lots:
                net_premium += lot_premium(lot)

            last_rolled = None
            if len(chain) >= 2:
                last_rolled = group_map[chain[-1]].opening_date

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
