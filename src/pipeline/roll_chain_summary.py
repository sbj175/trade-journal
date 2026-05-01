"""
Roll Chain Summary — materialized roll chain statistics.

Rebuilds roll_chain_summaries from position_groups, position_lots, and lot_closings.
100% derived data, safe to delete-and-rebuild on every pipeline run.

Cumulative metrics use the lot attribution rule (OPT-284 Phase 3c):
each contract belongs to the chain its lineage ends up in. This makes
per-chain totals match the chain modal AND keeps portfolio totals
additive across chains, even when a source group's lots branch into
multiple children.

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
from src.pipeline.lot_lineage import build_chain_attribution

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

        # Load all lots and group-lot links so the attribution helper has
        # the full graph to walk.
        all_lots = session.query(PositionLotModel).filter(
            PositionLotModel.user_id == user_id,
        ).all()
        lots_by_id: Dict[int, PositionLotModel] = {l.id: l for l in all_lots}

        gl_rows = session.query(
            PositionGroupLot.group_id,
            PositionGroupLot.transaction_id,
        ).filter(
            PositionGroupLot.user_id == user_id,
        ).all()
        txn_to_group: Dict[str, str] = {txn: gid for gid, txn in gl_rows}

        chains_by_leaf, lot_to_leaf = build_chain_attribution(
            group_map=group_map,
            children_map=children_map,
            lots_by_id=lots_by_id,
            txn_to_group=txn_to_group,
        )

        if not chains_by_leaf:
            return 0

        # Closings keyed by lot id, scoped to user.
        closings_by_lot: Dict[int, List[LotClosingModel]] = defaultdict(list)
        if lots_by_id:
            closings = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id.in_(list(lots_by_id.keys())),
            ).all()
            for c in closings:
                closings_by_lot[c.lot_id].append(c)

        # Group lots by their attributed chain (leaf id).
        attributed_lot_ids_by_leaf: Dict[str, set] = defaultdict(set)
        for lid, leaf_id in lot_to_leaf.items():
            attributed_lot_ids_by_leaf[leaf_id].add(lid)

        # Build summaries — one row per leaf, with cumulative metrics
        # over the lots attributed to that chain.
        count = 0
        for leaf_id, chain in chains_by_leaf.items():
            attributed_lot_ids = attributed_lot_ids_by_leaf.get(leaf_id, set())
            leaf_lot_ids = {
                lid for lid in attributed_lot_ids
                if txn_to_group.get(lots_by_id[lid].transaction_id) == leaf_id
            }
            ancestor_lot_ids = attributed_lot_ids - leaf_lot_ids

            cumulative_realized_pnl = 0.0
            for lid in attributed_lot_ids:
                for c in closings_by_lot.get(lid, []):
                    cumulative_realized_pnl += c.realized_pnl

            # Net premium = realized P&L of every closed-history attributed
            # lot + initial premium of the leaf-group attributed lots.
            net_premium = 0.0
            for lid in ancestor_lot_ids:
                for c in closings_by_lot.get(lid, []):
                    net_premium += c.realized_pnl
            for lid in leaf_lot_ids:
                lot = lots_by_id.get(lid)
                if lot is not None:
                    net_premium += lot_premium(lot)

            root = group_map[chain[0]]
            current = group_map[leaf_id]
            last_rolled = current.opening_date if len(chain) >= 2 else None

            session.add(RollChainSummary(
                user_id=user_id,
                root_group_id=root.group_id,
                current_group_id=leaf_id,
                underlying=root.underlying or '',
                account_number=root.account_number or '',
                chain_length=len(chain),
                roll_count=len(chain) - 1,
                first_opened=root.opening_date,
                last_rolled=last_rolled,
                cumulative_premium=net_premium,
                cumulative_realized_pnl=cumulative_realized_pnl,
            ))
            count += 1

        session.flush()
        return count
