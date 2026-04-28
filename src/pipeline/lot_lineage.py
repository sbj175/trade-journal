"""Lot-level roll lineage (OPT-284 Phase 2).

Two pipeline functions live here:

1. ``detect_lot_lineage`` — the single source of truth for whether
   a newly-opened lot continued from a previously-closed lot. Pairs
   same-day, structurally-compatible closes and opens at the lot
   level, ignoring broker `order_id` and `chain_id` (spec §0.1).
   Per spec §0.2 each lot is in at most one chain, so a close pairs
   with at most one open and vice versa.

2. ``derive_rolled_from_group_id`` — projects the lot-level lineage
   back onto position groups. A group has ``rolled_from_group_id``
   set to a source iff every lot in the group has a parent lot in
   that source AND the source group is fully closed; otherwise NULL.

The orchestrator runs (1) then (2) after group routing. The result
is that ``position_groups.rolled_from_group_id`` is a derived view
of lot-level facts rather than its own stored truth.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Tuple

from src.database.models import (
    LotClosing as LotClosingModel,
    PositionGroup,
    PositionGroupLot,
    PositionLot as PositionLotModel,
)
from src.database.tenant import DEFAULT_USER_ID

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


def _direction(lot) -> str:
    return "long" if lot.quantity > 0 else "short"


def detect_lot_lineage(db_manager: "DatabaseManager") -> int:
    """Pair same-day compatible closes and opens at the lot level.

    For every (account, underlying, day, option_type, direction) bucket:
      - "closes" = lots with a MANUAL closing on `day` matching those attrs
      - "opens"  = lots with `entry_date` on `day` matching those attrs
      - Greedy closest-strike pairing; each lot pairs at most once
      - Excess on either side is unpaired (new business or simple close)

    Sets ``position_lots.parent_lot_id`` on the open side. Resets
    existing values first so re-detection is clean (idempotent within a
    single pipeline run).

    Returns the number of pair links created.
    """
    paired = 0

    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        # Reset — lot-level detection is the source of truth, so any
        # previously-set parent_lot_id is recomputed from raw events.
        session.query(PositionLotModel).filter(
            PositionLotModel.user_id == user_id,
        ).update({PositionLotModel.parent_lot_id: None})
        session.flush()

        # Build closes bucket. Only MANUAL closings count as roll
        # candidates per spec §2 (expiration / assignment / exercise
        # are mutually exclusive with rolls).
        closing_rows = (
            session.query(LotClosingModel, PositionLotModel)
            .join(PositionLotModel, LotClosingModel.lot_id == PositionLotModel.id)
            .filter(
                PositionLotModel.user_id == user_id,
                LotClosingModel.closing_type == "MANUAL",
            )
            .all()
        )

        # closes[(acct, undl, day, opt, dir)] = [(strike, lot_id), ...]
        closes_bucket: Dict[Tuple, List[Tuple[float, int]]] = defaultdict(list)
        for closing, lot in closing_rows:
            day = str(closing.closing_date)[:10]
            key = (
                lot.account_number, lot.underlying, day,
                lot.option_type or "", _direction(lot),
            )
            closes_bucket[key].append((lot.strike or 0.0, lot.id))

        if not closes_bucket:
            return 0

        # Build opens bucket — only fetch lots whose entry_date matches a
        # bucketed day, by filtering on the days that actually appear as
        # closing days.
        days_of_interest = {key[2] for key in closes_bucket.keys()}
        if not days_of_interest:
            return 0

        # SQLite/Postgres compat: use a per-day LIKE clause via OR.
        # The set is small (one day per close event group) so a single
        # IN-style filter on prefixes works via an OR of LIKEs. Simplest
        # approach: pull all user lots and filter in Python — typical
        # production volume is small enough not to matter.
        all_lots = (
            session.query(PositionLotModel)
            .filter(PositionLotModel.user_id == user_id)
            .all()
        )
        # Index by lot_id for back-reference during pairing.
        lot_by_id: Dict[int, PositionLotModel] = {l.id: l for l in all_lots}

        opens_bucket: Dict[Tuple, List[Tuple[float, int]]] = defaultdict(list)
        for lot in all_lots:
            if not lot.entry_date:
                continue
            day = str(lot.entry_date)[:10]
            if day not in days_of_interest:
                continue
            key = (
                lot.account_number, lot.underlying, day,
                lot.option_type or "", _direction(lot),
            )
            opens_bucket[key].append((lot.strike or 0.0, lot.id))

        # Pair per bucket.
        for key, closes in closes_bucket.items():
            opens = opens_bucket.get(key, [])
            if not opens:
                continue

            # All (close_idx, open_idx, strike_distance) triples, sorted
            # so the closest-strike pair is processed first. Ties broken
            # deterministically by lot_id.
            candidates = []
            for ci, (cstrike, cid) in enumerate(closes):
                for oi, (ostrike, oid) in enumerate(opens):
                    if cid == oid:
                        # Same lot opened-and-closed same-day — never
                        # self-pair.
                        continue
                    distance = abs(cstrike - ostrike)
                    candidates.append((distance, ci, oi, cid, oid))
            candidates.sort()

            close_used: set = set()
            open_used: set = set()
            for _dist, ci, oi, cid, oid in candidates:
                if ci in close_used or oi in open_used:
                    continue
                open_lot = lot_by_id.get(oid)
                if open_lot is None:
                    continue
                open_lot.parent_lot_id = cid
                close_used.add(ci)
                open_used.add(oi)
                paired += 1

        session.flush()

    if paired:
        logger.info("Lot lineage: paired %d open lots to predecessors", paired)
    return paired


def derive_rolled_from_group_id(db_manager: "DatabaseManager") -> int:
    """Set position_groups.rolled_from_group_id from lot-level lineage.

    A target group has rolled_from = source iff:
      - Every lot in the target has parent_lot_id set
      - All those parents are in the same source group
      - The source group is fully CLOSED

    Otherwise rolled_from is cleared. The lot-level lineage is the
    single source of truth.

    Returns the number of groups whose rolled_from_group_id was changed.
    """
    changes = 0

    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        all_groups = (
            session.query(PositionGroup)
            .filter(PositionGroup.user_id == user_id)
            .all()
        )
        group_by_id: Dict[str, PositionGroup] = {g.group_id: g for g in all_groups}

        # transaction_id → group_id  (for finding parent lot's group)
        gl_rows = (
            session.query(PositionGroupLot.group_id, PositionGroupLot.transaction_id)
            .filter(PositionGroupLot.user_id == user_id)
            .all()
        )
        group_by_txn: Dict[str, str] = {txn: gid for gid, txn in gl_rows}

        # group_id → list of PositionLot
        group_lots: Dict[str, List[PositionLotModel]] = defaultdict(list)
        all_lot_rows = (
            session.query(PositionGroupLot.group_id, PositionLotModel)
            .join(
                PositionGroupLot,
                (PositionGroupLot.transaction_id == PositionLotModel.transaction_id)
                & (PositionGroupLot.user_id == PositionLotModel.user_id),
            )
            .filter(PositionLotModel.user_id == user_id)
            .all()
        )
        for gid, lot in all_lot_rows:
            group_lots[gid].append(lot)

        # lot_id → its lot row (used to look up parent lots)
        lot_by_id: Dict[int, PositionLotModel] = {
            lot.id: lot
            for lots in group_lots.values()
            for lot in lots
        }

        for group in all_groups:
            lots = group_lots.get(group.group_id, [])
            new_value = _derive_for_group(
                lots,
                lot_by_id=lot_by_id,
                group_by_txn=group_by_txn,
                group_by_id=group_by_id,
            )
            if (group.rolled_from_group_id or None) != new_value:
                group.rolled_from_group_id = new_value
                changes += 1

        session.flush()

    if changes:
        logger.info("Derived rolled_from_group_id for %d groups", changes)
    return changes


def _derive_for_group(
    lots: List[PositionLotModel],
    *,
    lot_by_id: Dict[int, PositionLotModel],
    group_by_txn: Dict[str, str],
    group_by_id: Dict[str, PositionGroup],
):
    """Return the rolled_from_group_id value for a group's lots, or
    None if the group is a fresh root / partial-adjustment / mixed-source."""
    if not lots:
        return None

    parent_ids = [l.parent_lot_id for l in lots]
    if any(pid is None for pid in parent_ids):
        # At least one lot has no parent → fresh business in this group
        # (a new position, or a partial-leg adjustment of an existing
        # position). Either way, no clean rolled_from at the group level.
        return None

    # All lots have parents — collect the source group(s).
    source_group_ids = set()
    for pid in parent_ids:
        parent_lot = lot_by_id.get(pid)
        if parent_lot is None:
            return None
        source_gid = group_by_txn.get(parent_lot.transaction_id)
        if source_gid is None:
            return None
        source_group_ids.add(source_gid)

    if len(source_group_ids) != 1:
        # Lots' parents are in multiple source groups → no single
        # rolled_from. Possible in legged-in-from-two-sources scenarios;
        # surface as new business at the group level until manual link.
        return None

    source_id = source_group_ids.pop()
    source_group = group_by_id.get(source_id)
    if source_group is None or source_group.status != "CLOSED":
        # Source not fully closed → not a roll continuation, just an
        # adjustment that happens to share lot lineage with an open
        # source.
        return None

    return source_id
