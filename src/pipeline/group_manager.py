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
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from src.models.lot_manager import Lot
from src.models.order_processor import Chain
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

    # --- Step 1: Build order_id -> chain_id lookup -------------------------
    order_to_chain: Dict[str, str] = {}
    for chain in chains:
        for order in chain.orders:
            order_to_chain[order.order_id] = chain.chain_id

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
            # Only option lots update chain→group routing.  Equity lots must
            # not redirect option lots away from their chain group.
            if lot.expiration:
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

        # Equity-first: shares always group with shares, not with the
        # option chain they were derived from (e.g. via exercise).
        if not assigned and not lot.expiration:
            au_key = (lot.account_number, lot.underlying)
            if au_key in au_to_group:
                gk = au_to_group[au_key]
                if _is_group_open(gk):
                    _add_lot_to_group(lot, gk, chain_id)
                    assigned = True

        # Rule 1: lot's chain already has a group (always merge — rolls stay together)
        if not assigned and chain_id and chain_id in chain_to_group:
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
    """Derive a strategy label from all lots (including closed) for CLOSED groups."""
    # Check if all lots are equity
    if all(lot.instrument_type in ("Equity", "EQUITY") for lot in lot_list):
        return "Shares"

    # Build synthetic legs treating all lots as if open (for labeling only)
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
# DB persistence layer
# ---------------------------------------------------------------------------

class GroupPersister:
    """Loads lots from DB, calls pure function, persists PositionGroup + PositionGroupLot."""

    def __init__(self, db_manager: "DatabaseManager", lot_manager: "LotManager"):
        self.db = db_manager
        self.lot_mgr = lot_manager

    def process_groups(
        self,
        chains: List[Chain],
        account_number: Optional[str] = None,
    ) -> int:
        """Full (re)processing: load lots -> group -> persist -> refresh statuses.

        Preserves existing group_ids where lots overlap (UUID stability).
        Computes closing_date from lot_closings for CLOSED groups.
        Returns number of groups created/updated.
        """
        from sqlalchemy import func
        from src.database.engine import dialect_insert
        from src.database.models import (
            PositionGroup,
            PositionGroupLot,
            PositionLot as PositionLotModel,
            LotClosing as LotClosingModel,
        )
        from src.database.tenant import DEFAULT_USER_ID

        # --- Load all lots from DB -----------------------------------------
        with self.db.get_session() as session:
            user_id = session.info.get("user_id", DEFAULT_USER_ID)
            q = session.query(PositionLotModel)
            if account_number:
                q = q.filter(PositionLotModel.account_number == account_number)
            q = q.order_by(PositionLotModel.entry_date.asc())
            all_lots = [self.lot_mgr._orm_to_lot(row) for row in q.all()]

        if not all_lots:
            return 0

        # --- Run pure grouping function ------------------------------------
        specs = assign_lots_to_groups(all_lots, chains)
        if not specs:
            return 0

        # --- Match new specs to existing DB groups by txn overlap ----------
        with self.db.get_session() as session:
            user_id = session.info.get("user_id", DEFAULT_USER_ID)

            # Build txn_id -> existing group_id mapping
            existing_links = session.query(
                PositionGroupLot.transaction_id,
                PositionGroupLot.group_id,
            ).all()
            txn_to_existing_group: Dict[str, str] = {
                row[0]: row[1] for row in existing_links
            }

            # Existing group_ids that we want to keep
            existing_group_ids = set(txn_to_existing_group.values())

            # Track which existing groups are covered by new specs
            covered_existing: Set[str] = set()
            count = 0

            for spec in specs:
                # Find existing group that overlaps with this spec's txn_ids
                overlapping_group_id = None
                for txn_id in spec.lot_transaction_ids:
                    if txn_id in txn_to_existing_group:
                        overlapping_group_id = txn_to_existing_group[txn_id]
                        break

                if overlapping_group_id:
                    group_id = overlapping_group_id
                    covered_existing.add(group_id)
                else:
                    group_id = str(_uuid.uuid4())

                # Compute closing_date for CLOSED groups
                closing_date = None
                if spec.status == "CLOSED":
                    # Get lot IDs for this group's transaction_ids
                    lot_ids = [
                        r[0] for r in session.query(PositionLotModel.id).filter(
                            PositionLotModel.transaction_id.in_(spec.lot_transaction_ids),
                        ).all()
                    ]
                    if lot_ids:
                        closing_date = session.query(
                            func.max(LotClosingModel.closing_date),
                        ).filter(
                            LotClosingModel.lot_id.in_(lot_ids),
                        ).scalar()

                # Source chain: use first chain_id if only one, else NULL
                source_chain_id = None
                if len(spec.source_chain_ids) == 1:
                    source_chain_id = next(iter(spec.source_chain_ids))

                # Upsert PositionGroup
                existing_group = session.query(PositionGroup).filter(
                    PositionGroup.group_id == group_id,
                ).first()
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if existing_group:
                    existing_group.account_number = spec.account_number
                    existing_group.underlying = spec.underlying
                    existing_group.strategy_label = spec.strategy_label
                    existing_group.status = spec.status
                    existing_group.source_chain_id = source_chain_id
                    existing_group.opening_date = (
                        spec.opening_date.isoformat() if spec.opening_date else None
                    )
                    existing_group.closing_date = closing_date
                    existing_group.updated_at = now_str
                else:
                    session.add(PositionGroup(
                        group_id=group_id,
                        account_number=spec.account_number,
                        underlying=spec.underlying,
                        strategy_label=spec.strategy_label,
                        status=spec.status,
                        source_chain_id=source_chain_id,
                        opening_date=(
                            spec.opening_date.isoformat() if spec.opening_date else None
                        ),
                        closing_date=closing_date,
                        updated_at=now_str,
                    ))

                # Delete stale group-lot links for this group, then re-insert
                session.query(PositionGroupLot).filter(
                    PositionGroupLot.group_id == group_id,
                    PositionGroupLot.user_id == user_id,
                ).delete()

                for txn_id in spec.lot_transaction_ids:
                    session.add(PositionGroupLot(
                        group_id=group_id,
                        transaction_id=txn_id,
                        user_id=user_id,
                    ))

                count += 1

            # Delete orphan groups (existing groups no longer covered)
            orphans = existing_group_ids - covered_existing
            if orphans:
                session.query(PositionGroupLot).filter(
                    PositionGroupLot.group_id.in_(orphans),
                    PositionGroupLot.user_id == user_id,
                ).delete(synchronize_session=False)
                session.query(PositionGroup).filter(
                    PositionGroup.group_id.in_(orphans),
                    PositionGroup.user_id == user_id,
                ).delete(synchronize_session=False)
                logger.info(f"Deleted {len(orphans)} orphan groups")

        logger.info(f"GroupPersister: processed {count} groups from {len(all_lots)} lots")
        return count
