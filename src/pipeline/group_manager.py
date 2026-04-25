"""
Group Manager — position group creation by expiration (options) or underlying (equity).

Public API:
    assign_lots_to_groups(lots) -> List[GroupSpec]          (pure, no DB)
    GroupPersister.process_groups(account_number)            (DB persistence)

Part of OPT-121 Stage 6.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from src.models.lot_manager import Lot
from src.pipeline.strategy_engine import recognize, lots_to_legs

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure data structures
# ---------------------------------------------------------------------------

@dataclass
class GroupSpec:
    """A group produced by the pure grouping function."""
    group_key: str                          # Internal key (NOT the DB UUID)
    account_number: str
    underlying: str
    strategy_label: Optional[str]
    status: str                             # OPEN or CLOSED
    opening_date: Optional[datetime]
    lot_transaction_ids: List[str]


# ---------------------------------------------------------------------------
# Pure grouping function
# ---------------------------------------------------------------------------

def assign_lots_to_groups(
    lots: List[Lot],
) -> List[GroupSpec]:
    """Pure function: lots -> grouped, labeled GroupSpecs.

    Algorithm (chronological lot processing):
    1. Sort lots by entry_date
    2. For each lot:
       a. Rule 1: options group by (account, underlying, expiration)
       b. Rule 2: equity group by (account, underlying), must be open
       c. Rule 3: create new group
    3. Run strategy engine on each group's lots -> strategy_label
    4. Compute status (OPEN if any lot has remaining_quantity != 0)

    Index separation: equity lots only update au_to_group,
    option lots only update aue_to_group.  This prevents
    cross-contamination between equity and option group routing.
    """
    if not lots:
        return []

    # --- Step 1: Sort lots chronologically ---------------------------------
    sorted_lots = sorted(lots, key=lambda lot: lot.entry_date)

    # Internal group tracking
    # group_key -> list of Lot objects
    groups: Dict[str, List[Lot]] = {}
    # (account, underlying, expiration) -> group_key  (options)
    aue_to_group: Dict[Tuple[str, str, date], str] = {}
    # (account, underlying) -> group_key  (equity)
    au_to_group: Dict[Tuple[str, str], str] = {}
    # chain_id -> group_key  (chain-aware routing for partial rolls)
    chain_to_group: Dict[str, str] = {}
    # group_key counter
    group_counter = 0

    def _is_group_open(group_key: str) -> bool:
        """Check if any lot in the group still has remaining quantity."""
        return any(lot.remaining_quantity != 0 for lot in groups[group_key])

    def _new_group_key() -> str:
        nonlocal group_counter
        group_counter += 1
        return f"g{group_counter}"

    def _add_lot_to_group(lot: Lot, gk: str) -> None:
        groups[gk].append(lot)
        if lot.expiration:
            aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = gk
        if not lot.expiration:
            au_to_group[(lot.account_number, lot.underlying)] = gk
        if lot.chain_id:
            chain_to_group[lot.chain_id] = gk

    # --- Step 2: Assign each lot to a group --------------------------------
    for lot in sorted_lots:
        assigned = False

        # Rule 0: chain-aware routing — keep partially-rolled positions together
        if not assigned and lot.chain_id and lot.chain_id in chain_to_group:
            gk = chain_to_group[lot.chain_id]
            if _is_group_open(gk):
                _add_lot_to_group(lot, gk)
                assigned = True

        # Rule 1: option lots group by (account, underlying, expiration).
        # The candidate group must still be open — otherwise a closed lot's
        # stale expiration anchor would pull an unrelated new open lot in
        # (e.g., May-1 43C closed today doesn't get to claim a new May-1 41C
        # from a different chain).
        if not assigned and lot.expiration:
            aue_key = (lot.account_number, lot.underlying, lot.expiration)
            if aue_key in aue_to_group:
                gk = aue_to_group[aue_key]
                if _is_group_open(gk):
                    _add_lot_to_group(lot, gk)
                    assigned = True

        # Rule 2: equity lots group by (account, underlying)
        if not assigned and not lot.expiration:
            au_key = (lot.account_number, lot.underlying)
            if au_key in au_to_group:
                gk = au_to_group[au_key]
                if _is_group_open(gk):
                    _add_lot_to_group(lot, gk)
                    assigned = True

        # Rule 3: create new group
        if not assigned:
            gk = _new_group_key()
            groups[gk] = []
            _add_lot_to_group(lot, gk)

    # --- Step 3 & 4: Build GroupSpec results with strategy labels ----------
    # May split groups when the recognizer finds multiple strategies.
    result: List[GroupSpec] = []
    for gk, lot_list in groups.items():
        # Check if all lots share a single chain_id (indicates one position lifecycle)
        chain_ids = {lot.chain_id for lot in lot_list if lot.chain_id}
        single_chain = len(chain_ids) == 1

        # Strategy label from engine (uses only non-closed lots)
        legs = lots_to_legs(lot_list)
        if not legs:
            # All lots are closed — build legs from all lots for labeling
            legs = _legs_from_all_lots(lot_list)

        if legs:
            sr = recognize(legs)

            # For single-chain groups (partial rolls), if the recognizer finds
            # multiple strategies from open legs, recover the original strategy
            # by recognizing only the opening order's legs.
            if single_chain and sr.sub_strategies and len(set(n for n, _ in sr.sub_strategies)) > 1:
                first_order = min(lot_list, key=lambda l: l.entry_date).opening_order_id
                if first_order:
                    opening_lots = [l for l in lot_list if l.opening_order_id == first_order]
                    opening_legs = _legs_from_all_lots(opening_lots)
                    if opening_legs:
                        sr = recognize(opening_legs)

            # Split group if recognizer found multiple distinct strategies,
            # but NOT if all lots share a chain (single position lifecycle).
            if not single_chain and sr.sub_strategies and len(set(n for n, _ in sr.sub_strategies)) > 1:
                sub_groups = _split_lots_by_partition(lot_list, legs, sr.sub_strategies)
                for sub_label, sub_lots in sub_groups:
                    has_open = any(lot.remaining_quantity != 0 for lot in sub_lots)
                    result.append(GroupSpec(
                        group_key=_new_group_key(),
                        account_number=sub_lots[0].account_number,
                        underlying=sub_lots[0].underlying,
                        strategy_label=sub_label,
                        status="OPEN" if has_open else "CLOSED",
                        opening_date=min(lot.entry_date for lot in sub_lots),
                        lot_transaction_ids=[lot.transaction_id for lot in sub_lots],
                    ))
                continue
            strategy_label = sr.name
        else:
            strategy_label = _label_from_all_lots(lot_list)

        # Status: OPEN if any lot has remaining quantity
        has_open = any(lot.remaining_quantity != 0 for lot in lot_list)
        status = "OPEN" if has_open else "CLOSED"

        # Opening date: earliest entry_date
        opening_date = min(lot.entry_date for lot in lot_list) if lot_list else None

        result.append(GroupSpec(
            group_key=gk,
            account_number=lot_list[0].account_number,
            underlying=lot_list[0].underlying,
            strategy_label=strategy_label,
            status=status,
            opening_date=opening_date,
            lot_transaction_ids=[lot.transaction_id for lot in lot_list],
        ))

    # --- Step 5: Upgrade Short Call → Covered Call where shares exist -------
    # Index: (account, underlying) -> list of Shares groups with date ranges
    shares_index: Dict[Tuple[str, str], List[GroupSpec]] = defaultdict(list)
    for gs in result:
        if gs.strategy_label == "Shares":
            shares_index[(gs.account_number, gs.underlying)].append(gs)

    for gs in result:
        if gs.strategy_label != "Short Call":
            continue
        key = (gs.account_number, gs.underlying)
        if key not in shares_index:
            continue
        call_open = gs.opening_date or datetime.min
        call_close = None  # We don't have closing_date on GroupSpec; assume overlap
        # If shares exist for same account+underlying, upgrade
        gs.strategy_label = "Covered Call"

    return result


def _split_lots_by_partition(
    lot_list: List[Lot],
    legs: list,
    sub_strategies: tuple,
) -> List[Tuple[str, List[Lot]]]:
    """Split lots into sub-groups based on the recognizer's partition.

    Each sub-strategy references leg indices. A leg is an aggregation of lots
    sharing the same structural key (instrument_type, option_type, strike,
    expiration, direction). We map leg indices back to lots via that key.
    """
    from src.pipeline.strategy_engine.types import Leg as LegType

    # Build leg-index → structural key mapping
    leg_keys: Dict[int, tuple] = {}
    for i, leg in enumerate(legs):
        leg_keys[i] = (leg.instrument_type, leg.option_type, leg.strike,
                        leg.expiration, leg.direction)

    # Build structural key → lots mapping
    key_to_lots: Dict[tuple, List[Lot]] = defaultdict(list)
    for lot in lot_list:
        inst = "Equity" if lot.instrument_type in ("Equity", "EQUITY") else "Option"
        opt = None
        if lot.option_type:
            opt = "C" if lot.option_type.upper().startswith("C") else "P"
        direction = "short" if lot.is_short else "long"
        key = (inst, opt, lot.strike, lot.expiration, direction)
        key_to_lots[key].append(lot)

    # Assign lots to sub-groups
    result: List[Tuple[str, List[Lot]]] = []
    assigned_lot_ids: Set[str] = set()
    for name, leg_indices in sub_strategies:
        sub_lots: List[Lot] = []
        for idx in leg_indices:
            key = leg_keys.get(idx)
            if key and key in key_to_lots:
                for lot in key_to_lots[key]:
                    if lot.transaction_id not in assigned_lot_ids:
                        sub_lots.append(lot)
                        assigned_lot_ids.add(lot.transaction_id)
        if sub_lots:
            result.append((name, sub_lots))

    # Any remaining lots (closed lots not in the partition) go to the first sub-group
    remaining = [lot for lot in lot_list if lot.transaction_id not in assigned_lot_ids]
    if remaining and result:
        result[0] = (result[0][0], result[0][1] + remaining)
    elif remaining:
        result.append((None, remaining))

    return result


def _label_from_all_lots(lot_list: List[Lot]) -> Optional[str]:
    """Derive a strategy label from all lots (including closed) for CLOSED groups."""
    if all(lot.instrument_type in ("Equity", "EQUITY") for lot in lot_list):
        return "Shares"

    legs = _legs_from_all_lots(lot_list)
    if legs:
        sr = recognize(legs)
        return sr.name
    return None



def _legs_from_all_lots(lot_list: List[Lot]) -> list:
    """Build aggregated Leg objects from all lots (including closed), treating all as open."""
    from src.pipeline.strategy_engine.types import Leg

    leg_groups: dict[tuple, int] = defaultdict(int)
    for lot in lot_list:
        if lot.instrument_type in ("Equity", "EQUITY"):
            inst_type = "Equity"
        else:
            inst_type = "Option"

        opt_type = None
        if lot.option_type:
            opt_type = "C" if lot.option_type.upper().startswith("C") else "P"

        direction = "short" if lot.is_short else "long"
        key = (inst_type, opt_type, lot.strike, lot.expiration, direction)
        leg_groups[key] += abs(lot.quantity)

    legs = []
    for (inst_type, opt_type, strike, exp, direction), qty in leg_groups.items():
        legs.append(Leg(
            instrument_type=inst_type,
            option_type=opt_type,
            strike=strike,
            expiration=exp,
            direction=direction,
            quantity=qty,
        ))

    return legs


# ---------------------------------------------------------------------------
# Roll-link detection
# ---------------------------------------------------------------------------

def _upgrade_covered_calls(
    session, all_group_ids: Set[str], group_lots: Dict[str, List[Lot]],
) -> None:
    """Upgrade 'Short Call' groups to 'Covered Call' when shares exist.

    A Short Call group whose account+underlying has a Shares group that
    overlaps in time is really a Covered Call.
    """
    from src.database.models import PositionGroup

    groups = session.query(PositionGroup).filter(
        PositionGroup.group_id.in_(all_group_ids),
    ).all()

    # Index: (account, underlying) -> list of Shares groups with date ranges
    shares_index: Dict[Tuple[str, str], List] = defaultdict(list)
    for g in groups:
        if g.strategy_label == "Shares":
            shares_index[(g.account_number, g.underlying)].append(g)

    for g in groups:
        if g.strategy_label != "Short Call" or g.strategy_label_user_override:
            continue

        key = (g.account_number, g.underlying)
        if key not in shares_index:
            continue

        # Check if any Shares group overlaps with this Short Call's lifetime
        for shares_group in shares_index[key]:
            shares_open = shares_group.opening_date or ""
            shares_close = shares_group.closing_date or "9999-12-31"
            call_open = g.opening_date or ""
            call_close = g.closing_date or "9999-12-31"

            # Overlap: shares opened before call closed AND shares closed after call opened
            if shares_open <= call_close and shares_close >= call_open:
                g.strategy_label = "Covered Call"
                break


def _persist_group_split(
    session, group, original_gid: str,
    sub_groups: List[Tuple[str, List[Lot]]],
    lots_in_group: List[Lot],
    user_id: str, now_str: str,
    all_group_ids: Set[str],
    group_lots: Dict[str, List[Lot]],
) -> None:
    """Split an existing group into multiple sub-groups based on recognizer partition.

    - Keeps the original group for the first sub-strategy (preserves group_id, tags, notes)
    - Creates new groups for the remaining sub-strategies
    - Reassigns PositionGroupLot links accordingly
    - Computes closing_date and last_activity_date for each sub-group
    """
    from sqlalchemy import func
    from src.database.models import (
        PositionGroup, PositionGroupLot,
        PositionLot as PositionLotModel, LotClosing as LotClosingModel,
    )

    first = True
    for label, sub_lots in sub_groups:
        txn_ids = {lot.transaction_id for lot in sub_lots}
        has_open = any(lot.remaining_quantity != 0 for lot in sub_lots)
        status = "OPEN" if has_open else "CLOSED"
        opening = min(l.entry_date for l in sub_lots).isoformat() if sub_lots else None

        # Compute closing_date and last_activity_date from lot_closings
        lot_ids = [
            r[0] for r in session.query(PositionLotModel.id).filter(
                PositionLotModel.transaction_id.in_(txn_ids),
            ).all()
        ]
        max_closing_date = None
        if lot_ids:
            max_closing_date = session.query(
                func.max(LotClosingModel.closing_date),
            ).filter(LotClosingModel.lot_id.in_(lot_ids)).scalar()

        closing_date = max_closing_date if status == "CLOSED" else None
        max_entry = session.query(
            func.max(PositionLotModel.entry_date),
        ).filter(PositionLotModel.transaction_id.in_(txn_ids)).scalar()
        activity_candidates = [d for d in [max_closing_date, max_entry] if d]
        last_activity = max(activity_candidates) if activity_candidates else None

        if first:
            # Reuse the original group — update its label and remove lots not in this sub
            group.strategy_label = label
            group.status = status
            group.opening_date = opening
            group.closing_date = closing_date
            group.last_activity_date = last_activity
            group.updated_at = now_str

            # Delete lot links that don't belong to this sub-group
            session.query(PositionGroupLot).filter(
                PositionGroupLot.group_id == original_gid,
                PositionGroupLot.user_id == user_id,
                ~PositionGroupLot.transaction_id.in_(txn_ids),
            ).delete(synchronize_session="fetch")

            group_lots[original_gid] = sub_lots
            first = False
        else:
            # Create a new group for this sub-strategy
            new_gid = str(_uuid.uuid4())
            session.add(PositionGroup(
                group_id=new_gid,
                account_number=sub_lots[0].account_number,
                underlying=sub_lots[0].underlying,
                strategy_label=label,
                status=status,
                opening_date=opening,
                closing_date=closing_date,
                last_activity_date=last_activity,
                updated_at=now_str,
            ))
            for txn_id in txn_ids:
                session.add(PositionGroupLot(
                    group_id=new_gid,
                    transaction_id=txn_id,
                    user_id=user_id,
                ))
            all_group_ids.add(new_gid)
            group_lots[new_gid] = sub_lots

    session.flush()


def _detect_roll_links(session, all_group_ids: Set[str], group_lots: Dict[str, List[Lot]]) -> None:
    """Phase 4b: auto-detect roll relationships between groups.

    Criteria (all must match):
    1. Same account + underlying
    2. Source group's closing_date same calendar day as target group's opening_date
    3. Target and candidate share at least one lot.chain_id (true roll lineage)
    4. Target doesn't already have a rolled_from_group_id
    5. Skip Shares groups

    Tie-breaking: prefer closest lot count.
    Process sorted by opening_date so serial rolls (A→B→C) link correctly.

    Note: strategy_label is intentionally NOT a matching criterion. The
    recognizer is a heuristic interpretation layer; lineage is determined
    by the deterministic chain_id from the lot layer. A label mismatch
    (e.g., a Covered Call roll temporarily mis-classified as a Diagonal
    Spread) must not sever the chain.
    """
    from src.database.models import PositionGroup

    # Load all groups with their metadata
    groups = session.query(PositionGroup).filter(
        PositionGroup.group_id.in_(all_group_ids),
    ).all()

    if not groups:
        return

    # Sort by opening_date ascending for serial roll detection
    sorted_groups = sorted(groups, key=lambda g: g.opening_date or '')

    # Index CLOSED groups by (account, underlying, closing_day)
    closed_by_key: Dict[Tuple[str, str, str], List] = defaultdict(list)

    for g in sorted_groups:
        if g.status != 'CLOSED' or not g.closing_date:
            continue
        if (g.strategy_label or '') == 'Shares':
            continue
        closing_day = str(g.closing_date)[:10]
        key = (g.account_number, g.underlying, closing_day)
        closed_by_key[key].append(g)

    links_created = 0

    for g in sorted_groups:
        if g.rolled_from_group_id:
            continue  # already linked
        if not g.opening_date:
            continue
        if (g.strategy_label or '') == 'Shares':
            continue

        opening_day = str(g.opening_date)[:10]
        key = (g.account_number, g.underlying, opening_day)
        candidates = closed_by_key.get(key, [])

        # Filter: candidate must not be the same group
        candidates = [c for c in candidates if c.group_id != g.group_id]
        if not candidates:
            continue

        # Filter: target must share a chain_id with at least one candidate.
        # chain_id is the structural truth for roll lineage — it's set on the
        # new lot during ROLLING processing by inheritance from the closed lot.
        target_chains = {lot.chain_id for lot in group_lots.get(g.group_id, []) if lot.chain_id}
        candidates = [
            c for c in candidates
            if target_chains & {lot.chain_id for lot in group_lots.get(c.group_id, []) if lot.chain_id}
        ]
        if not candidates:
            continue

        # Tie-break: prefer closest lot count
        target_lot_count = len(group_lots.get(g.group_id, []))
        best = min(
            candidates,
            key=lambda c: abs(len(group_lots.get(c.group_id, [])) - target_lot_count),
        )

        g.rolled_from_group_id = best.group_id
        links_created += 1

        # Register this group as a closed source too (for serial A→B→C)
        if g.status == 'CLOSED' and g.closing_date:
            closing_day = str(g.closing_date)[:10]
            new_key = (g.account_number, g.underlying, closing_day)
            closed_by_key[new_key].append(g)

    if links_created:
        logger.info(f"Phase 4b: detected {links_created} roll links")


# ---------------------------------------------------------------------------
# DB persistence layer
# ---------------------------------------------------------------------------

class GroupPersister:
    """Incremental group manager: preserves existing group assignments, only routes new lots."""

    def __init__(self, db_manager: "DatabaseManager", lot_manager: "LotManager"):
        self.db = db_manager
        self.lot_mgr = lot_manager

    def process_groups(
        self,
        account_number: Optional[str] = None,
    ) -> int:
        """Incremental group processing that preserves user merges.

        Phase 1: Load state (lots, existing group links)
        Phase 2: Seed routing indexes from existing groups
        Phase 3: Route new lots (no existing group link) using same rules as assign_lots_to_groups
        Phase 4: Refresh metadata for ALL groups (status, strategy, dates)
        Phase 5: Cleanup stale links and empty groups

        Returns number of groups created or updated.
        """
        from sqlalchemy import func
        from src.database.models import (
            PositionGroup,
            PositionGroupLot,
            PositionGroupTag,
            PositionNote,
            PositionLot as PositionLotModel,
            LotClosing as LotClosingModel,
        )
        from src.database.tenant import DEFAULT_USER_ID

        with self.db.get_session() as session:
            user_id = session.info.get("user_id", DEFAULT_USER_ID)

            # =================================================================
            # Phase 1: Load state
            # =================================================================
            q = session.query(PositionLotModel)
            if account_number:
                q = q.filter(PositionLotModel.account_number == account_number)
            q = q.order_by(PositionLotModel.entry_date.asc())
            all_lot_rows = q.all()
            all_lots = [self.lot_mgr._orm_to_lot(row) for row in all_lot_rows]

            if not all_lots:
                return 0

            # Build transaction_id -> Lot lookup
            txn_to_lot: Dict[str, Lot] = {lot.transaction_id: lot for lot in all_lots}

            # Load existing group-lot links: transaction_id -> group_id
            existing_links = session.query(
                PositionGroupLot.transaction_id,
                PositionGroupLot.group_id,
            ).filter(PositionGroupLot.user_id == user_id).all()
            txn_to_group: Dict[str, str] = {row[0]: row[1] for row in existing_links}

            # Identify new lots (transaction_id has no group link)
            new_lots = [lot for lot in all_lots if lot.transaction_id not in txn_to_group]

            logger.info(
                "Phase 1: %d lots, %d existing group links, %d new lots",
                len(all_lots), len(existing_links), len(new_lots),
            )

            # =================================================================
            # Phase 2: Seed routing indexes from existing groups
            # =================================================================
            # (account, underlying, expiration) -> group_id  (options)
            aue_to_group: Dict[Tuple[str, str, date], str] = {}
            # (account, underlying) -> group_id  (equity)
            au_to_group: Dict[Tuple[str, str], str] = {}
            # chain_id -> group_id  (chain-aware routing for partial rolls)
            chain_to_group: Dict[str, str] = {}
            # group_id -> set of Lot objects (for open-check)
            group_lots: Dict[str, List[Lot]] = defaultdict(list)

            # Collect existing group_ids from DB (for Phase 4)
            gid_q = session.query(PositionGroup.group_id)
            if account_number:
                gid_q = gid_q.filter(PositionGroup.account_number == account_number)
            all_group_ids: Set[str] = {row[0] for row in gid_q.all()}

            # Seed indexes from existing group-lot links
            for txn_id, group_id in txn_to_group.items():
                lot = txn_to_lot.get(txn_id)
                if not lot:
                    continue  # stale link, cleaned up in Phase 5
                group_lots[group_id].append(lot)

                if lot.expiration:
                    aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = group_id
                if not lot.expiration:
                    au_to_group[(lot.account_number, lot.underlying)] = group_id
                if lot.chain_id:
                    chain_to_group[lot.chain_id] = group_id

            # =================================================================
            # Phase 3: Route new lots
            # =================================================================
            new_groups_created = 0

            def _is_group_open(gid: str) -> bool:
                return any(l.remaining_quantity != 0 for l in group_lots[gid])

            def _add_new_lot(lot: Lot, group_id: str) -> None:
                group_lots[group_id].append(lot)
                txn_to_group[lot.transaction_id] = group_id
                if lot.expiration:
                    aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = group_id
                if not lot.expiration:
                    au_to_group[(lot.account_number, lot.underlying)] = group_id
                if lot.chain_id:
                    chain_to_group[lot.chain_id] = group_id

            sorted_new = sorted(new_lots, key=lambda lot: lot.entry_date)
            for lot in sorted_new:
                assigned = False

                # Rule 0: chain-aware routing — keep partially-rolled positions together
                if not assigned and lot.chain_id and lot.chain_id in chain_to_group:
                    gk = chain_to_group[lot.chain_id]
                    if _is_group_open(gk):
                        _add_new_lot(lot, gk)
                        assigned = True

                # Rule 1: option lots group by (account, underlying, expiration).
                # The candidate group must still be open — otherwise a closed
                # lot's stale expiration anchor would pull an unrelated new
                # open lot from a different chain into it.
                if not assigned and lot.expiration:
                    aue_key = (lot.account_number, lot.underlying, lot.expiration)
                    if aue_key in aue_to_group:
                        gk = aue_to_group[aue_key]
                        if _is_group_open(gk):
                            _add_new_lot(lot, gk)
                            assigned = True

                # Rule 2: equity lots group by (account, underlying)
                if not assigned and not lot.expiration:
                    au_key = (lot.account_number, lot.underlying)
                    if au_key in au_to_group:
                        gk = au_to_group[au_key]
                        if _is_group_open(gk):
                            _add_new_lot(lot, gk)
                            assigned = True

                # Rule 3: create new group
                if not assigned:
                    new_gid = str(_uuid.uuid4())
                    group_lots[new_gid] = []
                    _add_new_lot(lot, new_gid)
                    new_groups_created += 1

            # Persist new group-lot links
            for lot in sorted_new:
                group_id = txn_to_group[lot.transaction_id]
                session.add(PositionGroupLot(
                    group_id=group_id,
                    transaction_id=lot.transaction_id,
                    user_id=user_id,
                ))

            # Create PositionGroup rows for newly created groups
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for gid, lots_in_group in group_lots.items():
                if gid not in all_group_ids and lots_in_group:
                    first_lot = lots_in_group[0]
                    session.add(PositionGroup(
                        group_id=gid,
                        account_number=first_lot.account_number,
                        underlying=first_lot.underlying,
                        strategy_label=None,  # set in Phase 4
                        status="OPEN",
                        opening_date=None,
                        updated_at=now_str,
                    ))
                    all_group_ids.add(gid)

            # Flush so Phase 4 can see all new rows
            session.flush()

            # =================================================================
            # Phase 4: Refresh metadata for ALL groups
            # =================================================================
            count = 0
            for gid in list(all_group_ids):
                lots_in_group = group_lots.get(gid, [])
                if not lots_in_group:
                    continue  # empty group, cleaned up in Phase 5

                group = session.query(PositionGroup).filter(
                    PositionGroup.group_id == gid,
                ).first()
                if not group:
                    continue

                # Status
                has_open = any(l.remaining_quantity != 0 for l in lots_in_group)
                group.status = "OPEN" if has_open else "CLOSED"

                # Opening date
                group.opening_date = min(
                    l.entry_date for l in lots_in_group
                ).isoformat() if lots_in_group else None

                # Closing date and last_activity_date
                lot_ids = [
                    r[0] for r in session.query(PositionLotModel.id).filter(
                        PositionLotModel.transaction_id.in_(
                            [l.transaction_id for l in lots_in_group]
                        ),
                    ).all()
                ]
                max_closing_date = None
                if lot_ids:
                    max_closing_date = session.query(
                        func.max(LotClosingModel.closing_date),
                    ).filter(
                        LotClosingModel.lot_id.in_(lot_ids),
                    ).scalar()

                if group.status == "CLOSED":
                    group.closing_date = max_closing_date
                else:
                    group.closing_date = None

                # last_activity_date = MAX(closing dates, entry dates)
                max_entry = None
                if lots_in_group:
                    max_entry = session.query(
                        func.max(PositionLotModel.entry_date),
                    ).filter(
                        PositionLotModel.transaction_id.in_(
                            [l.transaction_id for l in lots_in_group]
                        ),
                    ).scalar()
                candidates = [d for d in [max_closing_date, max_entry] if d]
                group.last_activity_date = max(candidates) if candidates else None

                # Strategy label (unless user overrode)
                if not group.strategy_label_user_override:
                    # Check if all lots share a single chain (one position lifecycle)
                    lot_chain_ids = {l.chain_id for l in lots_in_group if l.chain_id}
                    single_chain = len(lot_chain_ids) == 1

                    legs = lots_to_legs(lots_in_group)
                    if not legs:
                        legs = _legs_from_all_lots(lots_in_group)

                    if legs:
                        sr = recognize(legs)

                        # For single-chain groups (partial rolls), if the recognizer
                        # finds multiple strategies from open legs, recover the
                        # original strategy by recognizing the opening order's legs.
                        if single_chain and sr.sub_strategies and len(set(n for n, _ in sr.sub_strategies)) > 1:
                            first_order = min(lots_in_group, key=lambda l: l.entry_date).opening_order_id
                            if first_order:
                                opening_lots = [l for l in lots_in_group if l.opening_order_id == first_order]
                                opening_legs = _legs_from_all_lots(opening_lots)
                                if opening_legs:
                                    sr = recognize(opening_legs)

                        # Split group if recognizer found multiple distinct strategies,
                        # but NOT if all lots share a chain (single position lifecycle).
                        if not single_chain and sr.sub_strategies and len(set(n for n, _ in sr.sub_strategies)) > 1:
                            sub_groups = _split_lots_by_partition(
                                lots_in_group, legs, sr.sub_strategies,
                            )
                            if len(sub_groups) > 1:
                                _persist_group_split(
                                    session, group, gid, sub_groups,
                                    lots_in_group, user_id, now_str,
                                    all_group_ids, group_lots,
                                )
                                count += len(sub_groups)
                                continue

                        group.strategy_label = sr.name

                group.updated_at = now_str
                count += 1

            # =================================================================
            # Phase 4b: Covered Call upgrade
            # =================================================================
            # Short Call groups that overlap with a Shares group for the same
            # account+underlying are really Covered Calls.
            _upgrade_covered_calls(session, all_group_ids, group_lots)

            # =================================================================
            # Phase 4c: Auto-detect roll links (rolled_from_group_id)
            # =================================================================
            _detect_roll_links(session, all_group_ids, group_lots)

            # =================================================================
            # Phase 5: Cleanup
            # =================================================================
            # Delete stale PositionGroupLot links (transaction_id no longer in position_lots)
            # When account-scoped, only clean up links for groups we processed
            valid_txn_ids = set(txn_to_lot.keys())
            if valid_txn_ids:
                stale_q = session.query(PositionGroupLot).filter(
                    PositionGroupLot.user_id == user_id,
                    ~PositionGroupLot.transaction_id.in_(valid_txn_ids),
                )
                if account_number:
                    # Only clean links belonging to groups we touched
                    stale_q = stale_q.filter(
                        PositionGroupLot.group_id.in_(all_group_ids),
                    )
                stale_links = stale_q.all()
                if stale_links:
                    stale_count = len(stale_links)
                    for link in stale_links:
                        session.delete(link)
                    logger.info(f"Cleaned up {stale_count} stale group-lot links")

            # Delete empty groups (no lot links) and their orphaned tags/notes
            for gid in list(all_group_ids):
                link_count = session.query(func.count()).select_from(
                    PositionGroupLot
                ).filter(
                    PositionGroupLot.group_id == gid,
                    PositionGroupLot.user_id == user_id,
                ).scalar()

                if link_count == 0:
                    session.query(PositionGroupTag).filter(
                        PositionGroupTag.group_id == gid,
                        PositionGroupTag.user_id == user_id,
                    ).delete(synchronize_session=False)
                    session.query(PositionNote).filter(
                        PositionNote.note_key == f"group_{gid}",
                        PositionNote.user_id == user_id,
                    ).delete(synchronize_session=False)
                    session.query(PositionGroup).filter(
                        PositionGroup.group_id == gid,
                        PositionGroup.user_id == user_id,
                    ).delete(synchronize_session=False)
                    logger.debug(f"Deleted empty group {gid} (with orphaned tags/notes)")

        logger.info(f"GroupPersister: processed {count} groups ({new_groups_created} new, {len(new_lots)} new lots) from {len(all_lots)} total lots")
        return count
