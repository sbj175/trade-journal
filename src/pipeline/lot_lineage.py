"""Lot-level roll lineage (OPT-284 Phase 1).

Backfills `position_lots.parent_lot_id` from the existing group-level
`rolled_from_group_id` data, by pairing the source group's
active-at-close lots with the target group's opening-day lots.

Phase 1 is intentionally conservative: we only set `parent_lot_id`
where the pairing is unambiguous — same lot count on both sides AND
matching (option_type, direction) when sorted by (option_type,
direction, strike). Cases that require trader intent (e.g., quantity
mismatches, partial-leg rolls, "roll + add" tickets) are left NULL
for a later phase to handle once detection itself moves to the lot
level (Phase 2).

`rolled_from_group_id` remains the authoritative chain signal during
Phase 1; the lot-level lineage is additive metadata that Phase 2 will
promote to source-of-truth.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Tuple

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


def _lot_sort_key(lot: PositionLotModel) -> Tuple:
    """(option_type, direction, strike) — equity lots sort with empty
    option_type first; same-shape lots fall in strike order so both
    sides line up under zip."""
    return (
        lot.option_type or "",
        "long" if lot.quantity > 0 else "short",
        lot.strike if lot.strike is not None else 0.0,
    )


def _pair_shape(lot: PositionLotModel) -> Tuple[str, str]:
    return (
        lot.option_type or "",
        "long" if lot.quantity > 0 else "short",
    )


def backfill_parent_lot_ids(db_manager: "DatabaseManager") -> Tuple[int, int]:
    """Set position_lots.parent_lot_id from rolled_from_group_id pairings.

    Returns (paired, skipped) — paired is the number of lots updated,
    skipped is the number of (target, source) group pairs left
    untouched because the pairing was ambiguous.

    Idempotent: only sets parent_lot_id when currently NULL.
    """
    paired = 0
    skipped = 0

    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        targets = session.query(PositionGroup).filter(
            PositionGroup.user_id == user_id,
            PositionGroup.rolled_from_group_id.isnot(None),
        ).all()

        for target in targets:
            source = session.query(PositionGroup).filter(
                PositionGroup.group_id == target.rolled_from_group_id,
                PositionGroup.user_id == user_id,
            ).first()
            if not source or not source.closing_date or not target.opening_date:
                skipped += 1
                continue

            target_day = str(target.opening_date)[:10]
            source_day = str(source.closing_date)[:10]
            if target_day != source_day:
                skipped += 1
                continue

            target_lots = _lots_opened_on(session, target.group_id, target_day, user_id)
            source_lots = _lots_closed_on(session, source.group_id, source_day, user_id)

            if not target_lots or not source_lots:
                skipped += 1
                continue
            if len(target_lots) != len(source_lots):
                skipped += 1
                continue

            target_lots.sort(key=_lot_sort_key)
            source_lots.sort(key=_lot_sort_key)

            if any(_pair_shape(t) != _pair_shape(s) for t, s in zip(target_lots, source_lots)):
                skipped += 1
                continue

            for tl, sl in zip(target_lots, source_lots):
                if tl.parent_lot_id is None:
                    tl.parent_lot_id = sl.id
                    paired += 1

        session.flush()

    if paired or skipped:
        logger.info(
            "Lot lineage backfill: paired %d lots, skipped %d ambiguous group pairs",
            paired, skipped,
        )
    return paired, skipped


def _lots_opened_on(session, group_id: str, day: str, user_id: str) -> List[PositionLotModel]:
    return (
        session.query(PositionLotModel)
        .join(
            PositionGroupLot,
            (PositionGroupLot.transaction_id == PositionLotModel.transaction_id)
            & (PositionGroupLot.user_id == PositionLotModel.user_id),
        )
        .filter(
            PositionGroupLot.group_id == group_id,
            PositionLotModel.user_id == user_id,
            PositionLotModel.entry_date.like(f"{day}%"),
        )
        .all()
    )


def _lots_closed_on(session, group_id: str, day: str, user_id: str) -> List[PositionLotModel]:
    """Source lots whose lot_closings.closing_date falls on `day`. The
    join through lot_closings is what filters out mid-life rolled-out
    legs that closed earlier in the source's lifetime — only legs
    actively closed at the source's closing event are paired."""
    return (
        session.query(PositionLotModel)
        .join(
            PositionGroupLot,
            (PositionGroupLot.transaction_id == PositionLotModel.transaction_id)
            & (PositionGroupLot.user_id == PositionLotModel.user_id),
        )
        .join(LotClosingModel, LotClosingModel.lot_id == PositionLotModel.id)
        .filter(
            PositionGroupLot.group_id == group_id,
            PositionLotModel.user_id == user_id,
            LotClosingModel.closing_date.like(f"{day}%"),
        )
        .distinct()
        .all()
    )
