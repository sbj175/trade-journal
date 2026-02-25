"""
Chain Graph — connected-component chain derivation from lots and closings.

Builds chains AFTER all lots are created by reading position_lots and
lot_closings from the database.  This eliminates the temporal coupling in
the existing _derive_chains() which requires knowing chain membership
BEFORE lots are closed.

Part of OPT-121 Stage 4.  Read-only — does not modify any DB state.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_

from src.database.models import (
    LotClosing as LotClosingModel,
    PositionLot as PositionLotModel,
)
from src.models.order_processor import Chain, Order

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Union-Find (Disjoint Set)
# ---------------------------------------------------------------------------

class UnionFind:
    """Standard union-find with path compression and union by rank."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}
        self._rank: Dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self) -> Dict[str, Set[str]]:
        """Return {root: set_of_members}."""
        groups: Dict[str, Set[str]] = defaultdict(set)
        for x in self._parent:
            groups[self.find(x)].add(x)
        return dict(groups)


# ---------------------------------------------------------------------------
# Pure graph builder
# ---------------------------------------------------------------------------

def build_order_graph(
    lot_edges: List[Tuple[str, str]],
    derived_edges: List[Tuple[str, str]],
) -> Dict[str, Set[str]]:
    """Pure function: edges -> connected components of order IDs.

    Parameters
    ----------
    lot_edges : list of (opening_order_id, closing_order_id)
        Edges from lot -> lot_closings.
    derived_edges : list of (derived_order_id, parent_order_id)
        Edges linking derived lots (e.g. stock from assignment) back to the
        parent lot's chain.

    Returns
    -------
    dict mapping a representative order ID to the set of order IDs in that
    connected component.
    """
    uf = UnionFind()

    for a, b in lot_edges:
        uf.add(a)
        uf.add(b)
        uf.union(a, b)

    for a, b in derived_edges:
        uf.add(a)
        uf.add(b)
        uf.union(a, b)

    return uf.components()


# ---------------------------------------------------------------------------
# Lightweight result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GraphChain:
    """Result of graph-based chain derivation (read-only, not persisted)."""
    chain_id: str
    underlying: str
    account_number: str
    order_ids: Set[str] = field(default_factory=set)
    status: str = "OPEN"


# ---------------------------------------------------------------------------
# DB-aware entry point
# ---------------------------------------------------------------------------

def derive_chains(
    db: "DatabaseManager",
    orders: List[Order],
    account_number: Optional[str] = None,
) -> List[Chain]:
    """Derive chains from lots/closings stored in the database.

    Reads position_lots and lot_closings, builds a graph of order IDs via
    connected components, then maps back to Order objects to produce Chain
    objects compatible with the existing ``_derive_chains()`` output.

    This function is **read-only** — it does not modify lots, chains, or
    any other DB state.

    Parameters
    ----------
    db : DatabaseManager
        Used to open a read-only session.
    orders : list[Order]
        The Order objects produced by ``OrderProcessor._create_orders()``.
        Used to map order IDs back to full Order objects.
    account_number : str, optional
        Restrict to a single account.  If None, processes all accounts.
    """
    order_map: Dict[str, Order] = {o.order_id: o for o in orders}

    with db.get_session() as session:
        # ----- 1. Load lots -------------------------------------------------
        lot_q = session.query(PositionLotModel)
        if account_number:
            lot_q = lot_q.filter(PositionLotModel.account_number == account_number)
        all_lots = lot_q.all()

        lot_by_id: Dict[int, PositionLotModel] = {lot.id: lot for lot in all_lots}
        lot_ids = set(lot_by_id.keys())

        # ----- 2. Load closings for those lots --------------------------------
        closing_q = session.query(LotClosingModel)
        if lot_ids:
            closing_q = closing_q.filter(LotClosingModel.lot_id.in_(lot_ids))
        all_closings = closing_q.all()

        # ----- 3. Build edges ------------------------------------------------
        lot_edges: List[Tuple[str, str]] = []
        derived_edges: List[Tuple[str, str]] = []

        for closing in all_closings:
            lot = lot_by_id.get(closing.lot_id)
            if not lot or not lot.opening_order_id:
                continue
            if closing.closing_order_id:
                lot_edges.append((lot.opening_order_id, closing.closing_order_id))

        # Derived-lot edges (e.g. stock from assignment)
        for lot in all_lots:
            if lot.derived_from_lot_id is None:
                continue
            parent = lot_by_id.get(lot.derived_from_lot_id)
            if parent is None:
                continue

            # The derived lot may have opening_order_id=None (current behavior).
            # Bridge through the parent's ASSIGNMENT closing instead.
            derived_opener = lot.opening_order_id
            if not derived_opener:
                # Find the assignment closing on the parent that created this lot
                for closing in all_closings:
                    if (closing.lot_id == parent.id and
                            closing.resulting_lot_id == lot.id):
                        derived_opener = closing.closing_order_id
                        break

            parent_opener = parent.opening_order_id
            if derived_opener and parent_opener:
                derived_edges.append((derived_opener, parent_opener))

    # ----- 4. Run graph algorithm ----------------------------------------
    components = build_order_graph(lot_edges, derived_edges)

    # ----- 5. Map components to Chain objects -----------------------------
    # Index: account+underlying for each order (needed for chain metadata)
    used_order_ids: Set[str] = set()
    chains: List[Chain] = []

    for _root, member_ids in components.items():
        if len(member_ids) < 1:
            continue

        # Collect Order objects for this component
        component_orders = []
        for oid in member_ids:
            if oid in order_map:
                component_orders.append(order_map[oid])
                used_order_ids.add(oid)

        if not component_orders:
            continue

        # Sort chronologically
        component_orders.sort(key=lambda o: o.executed_at)
        earliest = component_orders[0]

        # Build chain_id in same format as existing code
        chain_id = (
            f"{earliest.underlying}_OPENING_"
            f"{earliest.executed_at.strftime('%Y%m%d')}_"
            f"{earliest.order_id[:8]}"
        )

        chain = Chain(
            chain_id=chain_id,
            underlying=earliest.underlying,
            account_number=earliest.account_number,
            orders=component_orders,
        )

        # Determine status from lots
        chain.status = _determine_status(db, chain_id, component_orders, account_number)
        chains.append(chain)

    # ----- 6. Orphan orders → single-order chains -------------------------
    for order in orders:
        if order.order_id in used_order_ids:
            continue
        if account_number and order.account_number != account_number:
            continue

        chain_id = (
            f"{order.underlying}_OPENING_"
            f"{order.executed_at.strftime('%Y%m%d')}_"
            f"{order.order_id[:8]}"
        )
        chain = Chain(
            chain_id=chain_id,
            underlying=order.underlying,
            account_number=order.account_number,
            orders=[order],
        )
        chain.status = _determine_status(db, chain_id, [order], account_number)
        chains.append(chain)

    return chains


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _determine_status(
    db: "DatabaseManager",
    chain_id: str,
    component_orders: List[Order],
    account_number: Optional[str],
) -> str:
    """Determine chain status by inspecting lots in the DB.

    Uses the chain_id that was assigned to lots during processing.
    Falls back to matching by opening_order_id when chain_id doesn't match
    (the graph-derived chain_id may differ from what was stored on lots).
    """
    order_ids = {o.order_id for o in component_orders}

    with db.get_session() as session:
        # Try matching by opening_order_id (always accurate)
        lots = (
            session.query(PositionLotModel)
            .filter(PositionLotModel.opening_order_id.in_(order_ids))
            .all()
        )

        # Also include derived lots whose parent is in our set
        lot_ids = {lot.id for lot in lots}
        if lot_ids:
            derived = (
                session.query(PositionLotModel)
                .filter(PositionLotModel.derived_from_lot_id.in_(lot_ids))
                .all()
            )
            lots = list(lots) + list(derived)

        if not lots:
            return "OPEN"

        has_open = any(lot.remaining_quantity != 0 for lot in lots)
        has_assignment = False
        if has_open:
            # Check if any lot has an ASSIGNMENT closing
            all_lot_ids = {lot.id for lot in lots}
            assignment_count = (
                session.query(LotClosingModel)
                .filter(
                    LotClosingModel.lot_id.in_(all_lot_ids),
                    LotClosingModel.closing_type == "ASSIGNMENT",
                )
                .count()
            )
            has_assignment = assignment_count > 0

        if has_open and has_assignment:
            return "ASSIGNED"
        if has_open:
            return "OPEN"
        return "CLOSED"
