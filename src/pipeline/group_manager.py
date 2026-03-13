"""
Group Manager — first-class position group creation with cross-order merging.

Public API:
    assign_lots_to_groups(lots, chains) -> List[GroupSpec]   (pure, no DB)
    GroupPersister.process_groups(chains, account_number)     (DB persistence)

Part of OPT-121 Stage 6.  Built alongside existing ledger_service.py grouping
— does not modify or replace it.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from src.models.lot_manager import Lot
from src.models.order_processor import Chain, OrderType
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
    source_chain_ids: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Pure grouping function
# ---------------------------------------------------------------------------

def assign_lots_to_groups(
    lots: List[Lot],
    chains: List[Chain],
) -> List[GroupSpec]:
    """Pure function: lots + chains -> grouped, labeled GroupSpecs.

    Algorithm (chronological lot processing):
    1. Build order_id -> chain_id lookup from chains
    2. Sort lots by entry_date
    3. For each lot:
       a. Equity-first: shares always group with shares (by account + underlying)
       b. Rule 1: lot's chain already has a group -> add to it (options/rolls)
       c. Rule 2: same (account, underlying, expiration) -> add (options)
       d. Rule 3: create new group
    4. Run strategy engine on each group's lots -> strategy_label
    5. Compute status (OPEN if any lot has remaining_quantity != 0)

    Index separation: equity lots only update au_to_group (underlying index),
    option lots only update chain_to_group and aue_to_group (chain/expiration
    indexes).  This prevents cross-contamination between equity and option
    group routing.
    """
    if not lots:
        return []

    # --- Step 1: Build order_id -> chain_id and order_type lookups ----------
    order_to_chain: Dict[str, str] = {}
    order_to_type: Dict[str, OrderType] = {}
    for chain in chains:
        for order in chain.orders:
            order_to_chain[order.order_id] = chain.chain_id
            order_to_type[order.order_id] = order.order_type

    # --- Step 2: Sort lots chronologically ---------------------------------
    sorted_lots = sorted(lots, key=lambda lot: lot.entry_date)

    # Internal group tracking
    # group_key -> list of Lot objects
    groups: Dict[str, List[Lot]] = {}
    # group_key -> set of chain_ids
    group_chains: Dict[str, Set[str]] = defaultdict(set)
    # chain_id -> group_key  (Rule 1 lookup)
    chain_to_group: Dict[str, str] = {}
    # (account, underlying, expiration) -> group_key  (Rule 2 lookup, options)
    aue_to_group: Dict[Tuple[str, str, date], str] = {}
    # (account, underlying) -> group_key  (Rule 2b lookup, equity)
    au_to_group: Dict[Tuple[str, str], str] = {}
    # group_key counter
    group_counter = 0

    def _is_group_open(group_key: str) -> bool:
        """Check if any lot in the group still has remaining quantity."""
        return any(lot.remaining_quantity != 0 for lot in groups[group_key])

    def _new_group_key() -> str:
        nonlocal group_counter
        group_counter += 1
        return f"g{group_counter}"

    def _add_lot_to_group(lot: Lot, gk: str, chain_id: Optional[str]) -> None:
        groups[gk].append(lot)
        if chain_id:
            group_chains[gk].add(chain_id)
            # Option lots and non-derived equity update chain→group routing
            # so that related lots in the same chain can find each other
            # (e.g., shares + short call = Covered Call).
            # Derived equity (assignment/exercise) must NOT register here —
            # it would redirect unrelated option lots to the Shares group.
            if lot.expiration or not lot.derivation_type:
                chain_to_group[chain_id] = gk
        # Only option lots update the expiration index
        if lot.expiration:
            aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = gk
        # Only equity lots update the underlying index
        if not lot.expiration:
            au_to_group[(lot.account_number, lot.underlying)] = gk

    # --- Step 3: Assign each lot to a group --------------------------------
    for lot in sorted_lots:
        chain_id = lot.chain_id
        # If lot has no chain_id, try to resolve via opening_order_id
        if not chain_id and lot.opening_order_id:
            chain_id = order_to_chain.get(lot.opening_order_id)

        assigned = False

        # Derived-equity-first: assignment/exercise-derived shares group
        # with other shares, not with the option chain they came from.
        # Normal (directly bought) equity falls through to Rule 1 so it
        # can join its chain's group and be recognized as a Covered Call.
        if not assigned and not lot.expiration and lot.derivation_type:
            au_key = (lot.account_number, lot.underlying)
            if au_key in au_to_group:
                gk = au_to_group[au_key]
                if _is_group_open(gk):
                    _add_lot_to_group(lot, gk, chain_id)
                    assigned = True

        # Rule 1: lot's chain already has a group — merge unless this lot
        # was opened by a ROLLING order (rolls get their own group).
        is_roll_opening = (
            lot.opening_order_id
            and order_to_type.get(lot.opening_order_id) == OrderType.ROLLING
        )
        if not assigned and chain_id and chain_id in chain_to_group and not is_roll_opening:
            gk = chain_to_group[chain_id]
            _add_lot_to_group(lot, gk, chain_id)
            assigned = True

        # Rule 2: (account, underlying, expiration) matches an OPEN group
        if not assigned and lot.expiration:
            aue_key = (lot.account_number, lot.underlying, lot.expiration)
            if aue_key in aue_to_group:
                gk = aue_to_group[aue_key]
                if _is_group_open(gk):
                    _add_lot_to_group(lot, gk, chain_id)
                    assigned = True

        # Rule 3: create new group
        if not assigned:
            gk = _new_group_key()
            groups[gk] = []
            _add_lot_to_group(lot, gk, chain_id)

    # --- Step 4 & 5: Build GroupSpec results with strategy labels ----------
    result: List[GroupSpec] = []
    for gk, lot_list in groups.items():
        # Strategy label from engine (uses only non-closed lots)
        legs = lots_to_legs(lot_list)
        if legs:
            sr = recognize(legs)
            strategy_label = sr.name
        else:
            # All lots are closed — label from all lots for historical display
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
            source_chain_ids=set(group_chains[gk]),
        ))

    return result


def _label_from_all_lots(lot_list: List[Lot]) -> Optional[str]:
    """Derive a strategy label from all lots (including closed) for CLOSED groups.

    When a group contains rolls (multiple opening orders), only the lots from
    the latest opening order are used for labeling.  This prevents a rolled
    bull call spread from being mislabeled as "Custom (4-leg)".

    For mixed groups (equity + options), equity lots are always included
    alongside the latest option cohort so Covered Calls are detected.
    """
    # Check if all lots are equity
    if all(lot.instrument_type in ("Equity", "EQUITY") for lot in lot_list):
        return "Shares"

    # Separate equity and option lots
    equity_lots = [l for l in lot_list if l.instrument_type in ("Equity", "EQUITY")]
    option_lots = [l for l in lot_list if l.instrument_type not in ("Equity", "EQUITY")]

    # For option lots, use only the latest opening cohort (handles rolls)
    lots_for_label = _latest_opening_cohort(option_lots) if option_lots else []

    # Always include equity lots so Covered Calls are detected
    if equity_lots:
        lots_for_label = lots_for_label + equity_lots

    return _recognize_from_lots(lots_for_label)


def _latest_opening_cohort(lot_list: List[Lot]) -> List[Lot]:
    """Return the lots from the most recent opening order.

    If all lots share the same opening_order_id (or have none), returns all.
    """
    # Collect distinct opening_order_ids (ignoring None)
    order_ids = {lot.opening_order_id for lot in lot_list if lot.opening_order_id}

    if len(order_ids) <= 1:
        return lot_list

    # Find the latest entry_date per opening_order_id
    order_latest: Dict[str, datetime] = {}
    for lot in lot_list:
        oid = lot.opening_order_id
        if oid:
            if oid not in order_latest or lot.entry_date > order_latest[oid]:
                order_latest[oid] = lot.entry_date

    latest_oid = max(order_latest, key=order_latest.get)
    return [lot for lot in lot_list if lot.opening_order_id == latest_oid]


def _recognize_from_lots(lot_list: List[Lot]) -> Optional[str]:
    """Run strategy recognition on a list of lots (treating all as open)."""
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

    if legs:
        sr = recognize(legs)
        return sr.name
    return None


# ---------------------------------------------------------------------------
# Roll-link detection
# ---------------------------------------------------------------------------

def _detect_roll_links(session, all_group_ids: Set[str], group_lots: Dict[str, List[Lot]]) -> None:
    """Phase 4b: auto-detect roll relationships between groups.

    Criteria (all must match):
    1. Same account + underlying
    2. Same effective strategy label (user override takes precedence)
    3. Source group's closing_date same calendar day as target group's opening_date
    4. Target doesn't already have a rolled_from_group_id
    5. Skip Shares groups

    Tie-breaking: prefer closest lot count.
    Process sorted by opening_date so serial rolls (A→B→C) link correctly.
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

    # Index CLOSED groups by (account, underlying, effective_label, closing_day)
    closed_by_key: Dict[Tuple[str, str, str, str], List] = defaultdict(list)

    for g in sorted_groups:
        if g.status != 'CLOSED' or not g.closing_date:
            continue
        label = g.strategy_label or ''
        if label == 'Shares':
            continue
        closing_day = str(g.closing_date)[:10]
        key = (g.account_number, g.underlying, label, closing_day)
        closed_by_key[key].append(g)

    links_created = 0

    for g in sorted_groups:
        if g.rolled_from_group_id:
            continue  # already linked
        if not g.opening_date:
            continue
        label = g.strategy_label or ''
        if label == 'Shares':
            continue

        opening_day = str(g.opening_date)[:10]
        key = (g.account_number, g.underlying, label, opening_day)
        candidates = closed_by_key.get(key, [])

        # Filter: candidate must not be the same group
        candidates = [c for c in candidates if c.group_id != g.group_id]
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
            new_key = (g.account_number, g.underlying, label, closing_day)
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
        chains: List[Chain],
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

            # Build order_id -> chain_id and order_type lookups from chains
            order_to_chain: Dict[str, str] = {}
            order_to_type: Dict[str, OrderType] = {}
            for chain in chains:
                for order in chain.orders:
                    order_to_chain[order.order_id] = chain.chain_id
                    order_to_type[order.order_id] = order.order_type

            # =================================================================
            # Phase 2: Seed routing indexes from existing groups
            # =================================================================
            # chain_id -> group_id
            chain_to_group: Dict[str, str] = {}
            # (account, underlying, expiration) -> group_id
            aue_to_group: Dict[Tuple[str, str, date], str] = {}
            # (account, underlying) -> group_id
            au_to_group: Dict[Tuple[str, str], str] = {}
            # group_id -> set of Lot objects (for open-check)
            group_lots: Dict[str, List[Lot]] = defaultdict(list)

            # Collect all existing group_ids from DB (for Phase 4)
            all_group_ids: Set[str] = {
                row[0] for row in session.query(PositionGroup.group_id).all()
            }

            # Seed indexes from existing group-lot links
            for txn_id, group_id in txn_to_group.items():
                lot = txn_to_lot.get(txn_id)
                if not lot:
                    continue  # stale link, cleaned up in Phase 5
                group_lots[group_id].append(lot)

                # Resolve chain_id for this lot
                chain_id = lot.chain_id
                if not chain_id and lot.opening_order_id:
                    chain_id = order_to_chain.get(lot.opening_order_id)

                # Register in routing indexes (same rules as assign_lots_to_groups)
                if chain_id:
                    if lot.expiration or not lot.derivation_type:
                        chain_to_group[chain_id] = group_id
                if lot.expiration:
                    aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = group_id
                if not lot.expiration:
                    au_to_group[(lot.account_number, lot.underlying)] = group_id

            # =================================================================
            # Phase 3: Route new lots
            # =================================================================
            new_groups_created = 0

            def _is_group_open(gid: str) -> bool:
                return any(l.remaining_quantity != 0 for l in group_lots[gid])

            def _add_new_lot(lot: Lot, group_id: str, chain_id: Optional[str]) -> None:
                group_lots[group_id].append(lot)
                txn_to_group[lot.transaction_id] = group_id
                # Update routing indexes
                if chain_id:
                    if lot.expiration or not lot.derivation_type:
                        chain_to_group[chain_id] = group_id
                if lot.expiration:
                    aue_to_group[(lot.account_number, lot.underlying, lot.expiration)] = group_id
                if not lot.expiration:
                    au_to_group[(lot.account_number, lot.underlying)] = group_id

            sorted_new = sorted(new_lots, key=lambda lot: lot.entry_date)
            for lot in sorted_new:
                chain_id = lot.chain_id
                if not chain_id and lot.opening_order_id:
                    chain_id = order_to_chain.get(lot.opening_order_id)

                assigned = False

                # Derived-equity-first: assignment/exercise shares → equity group
                if not assigned and not lot.expiration and lot.derivation_type:
                    au_key = (lot.account_number, lot.underlying)
                    if au_key in au_to_group:
                        gk = au_to_group[au_key]
                        if _is_group_open(gk):
                            _add_new_lot(lot, gk, chain_id)
                            assigned = True

                # Rule 1: chain already has a group — skip for ROLLING orders
                is_roll_opening = (
                    lot.opening_order_id
                    and order_to_type.get(lot.opening_order_id) == OrderType.ROLLING
                )
                if not assigned and chain_id and chain_id in chain_to_group and not is_roll_opening:
                    gk = chain_to_group[chain_id]
                    _add_new_lot(lot, gk, chain_id)
                    assigned = True

                # Rule 2a: same (account, underlying, expiration) OPEN group (options)
                if not assigned and lot.expiration:
                    aue_key = (lot.account_number, lot.underlying, lot.expiration)
                    if aue_key in aue_to_group:
                        gk = aue_to_group[aue_key]
                        if _is_group_open(gk):
                            _add_new_lot(lot, gk, chain_id)
                            assigned = True

                # Rule 2b: same (account, underlying) OPEN group (equity)
                # In the pure function, non-derived equity from different chains
                # creates separate groups (for Covered Call detection). But in
                # incremental mode, existing groups (including user-merged ones)
                # should attract new equity lots for the same underlying.
                if not assigned and not lot.expiration:
                    au_key = (lot.account_number, lot.underlying)
                    if au_key in au_to_group:
                        gk = au_to_group[au_key]
                        if _is_group_open(gk):
                            _add_new_lot(lot, gk, chain_id)
                            assigned = True

                # Rule 3: create new group
                if not assigned:
                    new_gid = str(_uuid.uuid4())
                    group_lots[new_gid] = []
                    _add_new_lot(lot, new_gid, chain_id)
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
                        source_chain_id=None,
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
                    legs = lots_to_legs(lots_in_group)
                    if legs:
                        sr = recognize(legs)
                        group.strategy_label = sr.name
                    else:
                        label = _label_from_all_lots(lots_in_group)
                        if label:
                            group.strategy_label = label

                # source_chain_id: set from lots' chain_ids if single-chain
                lot_chain_ids = {l.chain_id for l in lots_in_group if l.chain_id}
                if len(lot_chain_ids) == 1:
                    group.source_chain_id = next(iter(lot_chain_ids))
                elif not lot_chain_ids:
                    group.source_chain_id = None
                # Multi-chain: leave source_chain_id as-is (could be user-merged)

                group.updated_at = now_str
                count += 1

            # =================================================================
            # Phase 4b: Auto-detect roll links (rolled_from_group_id)
            # =================================================================
            _detect_roll_links(session, all_group_ids, group_lots)

            # =================================================================
            # Phase 5: Cleanup
            # =================================================================
            # Delete stale PositionGroupLot links (transaction_id no longer in position_lots)
            valid_txn_ids = set(txn_to_lot.keys())
            if valid_txn_ids:
                stale_links = session.query(PositionGroupLot).filter(
                    PositionGroupLot.user_id == user_id,
                    ~PositionGroupLot.transaction_id.in_(valid_txn_ids),
                ).all()
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
