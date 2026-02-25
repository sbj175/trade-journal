"""Unit tests for the Group Manager — pure function, shadow comparison, and DB integration."""

import pytest
import uuid
from datetime import datetime, date
from collections import defaultdict

from src.models.lot_manager import Lot
from src.models.order_processor import Chain, Order, OrderType
from src.pipeline.group_manager import assign_lots_to_groups, GroupSpec, GroupPersister
from src.pipeline.strategy_engine import recognize, lots_to_legs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_lot_counter = 0


def _lot(
    *,
    transaction_id=None,
    account_number="ACCT1",
    symbol="AAPL  260321C00170000",
    underlying="AAPL",
    instrument_type="EQUITY_OPTION",
    option_type="Call",
    strike=170.0,
    expiration=date(2026, 3, 21),
    quantity=-1,
    entry_price=2.50,
    entry_date=datetime(2026, 1, 15, 10, 0, 0),
    remaining_quantity=None,
    chain_id=None,
    opening_order_id=None,
    status="OPEN",
):
    """Build a Lot dataclass for testing."""
    global _lot_counter
    _lot_counter += 1
    if remaining_quantity is None:
        remaining_quantity = quantity
    if transaction_id is None:
        transaction_id = f"tx-{_lot_counter:04d}"
    return Lot(
        id=_lot_counter,
        transaction_id=transaction_id,
        account_number=account_number,
        symbol=symbol,
        underlying=underlying,
        instrument_type=instrument_type,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        quantity=quantity,
        entry_price=entry_price,
        entry_date=entry_date,
        remaining_quantity=remaining_quantity,
        original_quantity=abs(quantity),
        chain_id=chain_id,
        leg_index=0,
        opening_order_id=opening_order_id,
        derived_from_lot_id=None,
        derivation_type=None,
        status=status,
    )


def _equity_lot(
    *,
    transaction_id=None,
    account_number="ACCT1",
    symbol="AAPL",
    underlying="AAPL",
    quantity=100,
    entry_price=150.0,
    entry_date=datetime(2026, 1, 15, 10, 0, 0),
    remaining_quantity=None,
    chain_id=None,
    opening_order_id=None,
    status="OPEN",
):
    """Build an equity Lot for testing."""
    return _lot(
        transaction_id=transaction_id,
        account_number=account_number,
        symbol=symbol,
        underlying=underlying,
        instrument_type="EQUITY",
        option_type=None,
        strike=None,
        expiration=None,
        quantity=quantity,
        entry_price=entry_price,
        entry_date=entry_date,
        remaining_quantity=remaining_quantity,
        chain_id=chain_id,
        opening_order_id=opening_order_id,
        status=status,
    )


def _chain(chain_id, underlying="AAPL", account="ACCT1", order_ids=None):
    """Build a Chain with minimal Order stubs."""
    orders = []
    for oid in (order_ids or []):
        orders.append(Order(
            order_id=oid,
            account_number=account,
            underlying=underlying,
            executed_at=datetime(2026, 1, 15, 10, 0, 0),
            order_type=OrderType.OPENING,
        ))
    return Chain(
        chain_id=chain_id,
        underlying=underlying,
        account_number=account,
        orders=orders,
    )


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------

class TestAssignLotsToGroups:

    def test_single_lot_creates_group(self):
        lots = [_lot(chain_id="C1")]
        chains = [_chain("C1", order_ids=["O1"])]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert len(specs[0].lot_transaction_ids) == 1

    def test_same_chain_lots_grouped(self):
        lots = [
            _lot(chain_id="C1", strike=170.0, option_type="Put",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="C1", strike=165.0, option_type="Put",
                 entry_date=datetime(2026, 1, 15, 10, 1)),
        ]
        chains = [_chain("C1", order_ids=["O1"])]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert len(specs[0].lot_transaction_ids) == 2

    def test_different_chains_different_underlying(self):
        lots = [
            _lot(chain_id="C1", underlying="AAPL",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="C2", underlying="MSFT", symbol="MSFT  260321C00300000",
                 entry_date=datetime(2026, 1, 15, 10, 1)),
        ]
        chains = [
            _chain("C1", underlying="AAPL", order_ids=["O1"]),
            _chain("C2", underlying="MSFT", order_ids=["O2"]),
        ]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 2
        underlyings = {s.underlying for s in specs}
        assert underlyings == {"AAPL", "MSFT"}

    def test_cross_order_iron_condor(self):
        """Put spread + call spread from different chains, same expiration -> 1 group, Iron Condor."""
        exp = date(2026, 4, 18)
        lots = [
            # Put spread (chain A)
            _lot(chain_id="CA", option_type="Put", strike=160.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="CA", option_type="Put", strike=155.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            # Call spread (chain B)
            _lot(chain_id="CB", option_type="Call", strike=180.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5)),
            _lot(chain_id="CB", option_type="Call", strike=185.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        chains = [
            _chain("CA", order_ids=["OA"]),
            _chain("CB", order_ids=["OB"]),
        ]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert specs[0].strategy_label == "Iron Condor"
        assert len(specs[0].lot_transaction_ids) == 4
        assert specs[0].source_chain_ids == {"CA", "CB"}

    def test_cross_order_different_expiration(self):
        """Same underlying, different expirations -> 2 groups."""
        lots = [
            _lot(chain_id="C1", expiration=date(2026, 3, 21),
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="C2", expiration=date(2026, 4, 18),
                 entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        chains = [
            _chain("C1", order_ids=["O1"]),
            _chain("C2", order_ids=["O2"]),
        ]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 2

    def test_equity_joins_option_group(self):
        """Short call + equity lot (same underlying) -> 1 group, Covered Call."""
        lots = [
            _lot(chain_id="C1", option_type="Call", strike=180.0, quantity=-1,
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _equity_lot(chain_id=None, quantity=100,
                        entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        chains = [_chain("C1", order_ids=["O1"])]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert specs[0].strategy_label == "Covered Call"

    def test_closed_group_not_merged_into(self):
        """Existing group all CLOSED, new lot same exp -> new group (not merged)."""
        exp = date(2026, 3, 21)
        lots = [
            # Old lot - closed (remaining_quantity=0)
            _lot(chain_id="C1", expiration=exp, remaining_quantity=0, status="CLOSED",
                 entry_date=datetime(2026, 1, 10, 10, 0)),
            # New lot - open, same exp
            _lot(chain_id="C2", expiration=exp,
                 entry_date=datetime(2026, 2, 1, 10, 0)),
        ]
        chains = [
            _chain("C1", order_ids=["O1"]),
            _chain("C2", order_ids=["O2"]),
        ]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 2
        # One CLOSED, one OPEN
        statuses = {s.status for s in specs}
        assert statuses == {"OPEN", "CLOSED"}

    def test_roll_chain_single_group(self):
        """Open -> roll -> new position (1 chain) -> 1 group."""
        lots = [
            # Original position
            _lot(chain_id="C1", expiration=date(2026, 3, 21), remaining_quantity=0,
                 status="CLOSED", entry_date=datetime(2026, 1, 15, 10, 0)),
            # Rolled position (same chain)
            _lot(chain_id="C1", expiration=date(2026, 4, 18),
                 entry_date=datetime(2026, 3, 20, 10, 0)),
        ]
        chains = [_chain("C1", order_ids=["O1", "O2"])]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert specs[0].status == "OPEN"

    def test_multiple_accounts_isolated(self):
        """Same underlying, different accounts -> 2 groups."""
        lots = [
            _lot(account_number="ACCT1", chain_id="C1",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(account_number="ACCT2", chain_id="C2",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
        ]
        chains = [
            _chain("C1", account="ACCT1", order_ids=["O1"]),
            _chain("C2", account="ACCT2", order_ids=["O2"]),
        ]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 2

    def test_strategy_label_from_engine(self):
        """Put spread legs -> 'Bull Put Spread'."""
        exp = date(2026, 3, 21)
        lots = [
            _lot(chain_id="C1", option_type="Put", strike=170.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="C1", option_type="Put", strike=165.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
        ]
        chains = [_chain("C1", order_ids=["O1"])]
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert specs[0].strategy_label == "Bull Put Spread"

    def test_empty_lots_returns_empty(self):
        specs = assign_lots_to_groups([], [])
        assert specs == []

    def test_lots_without_chain_or_expiration(self):
        """Orphan equity lot -> creates a group with 'Shares' label."""
        lots = [_equity_lot(chain_id=None)]
        specs = assign_lots_to_groups(lots, [])
        assert len(specs) == 1
        # Single equity leg recognized as "Long Shares" or "Shares"
        assert "Shares" in specs[0].strategy_label or "Long" in specs[0].strategy_label

    def test_chronological_ordering_invariant(self):
        """Lots in random order -> same result as sorted."""
        exp = date(2026, 4, 18)
        # Create lots with distinct times
        lot_a = _lot(chain_id="CA", option_type="Put", strike=160.0, quantity=-1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0))
        lot_b = _lot(chain_id="CA", option_type="Put", strike=155.0, quantity=1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 1))
        lot_c = _lot(chain_id="CB", option_type="Call", strike=180.0, quantity=-1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5))
        lot_d = _lot(chain_id="CB", option_type="Call", strike=185.0, quantity=1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 6))

        chains = [
            _chain("CA", order_ids=["OA"]),
            _chain("CB", order_ids=["OB"]),
        ]

        # Sorted order
        specs_sorted = assign_lots_to_groups([lot_a, lot_b, lot_c, lot_d], chains)
        # Reversed order
        specs_reversed = assign_lots_to_groups([lot_d, lot_c, lot_b, lot_a], chains)
        # Shuffled
        specs_shuffled = assign_lots_to_groups([lot_c, lot_a, lot_d, lot_b], chains)

        # All should produce same number of groups with same txn counts
        assert len(specs_sorted) == len(specs_reversed) == len(specs_shuffled)
        for s1, s2, s3 in zip(specs_sorted, specs_reversed, specs_shuffled):
            assert set(s1.lot_transaction_ids) == set(s2.lot_transaction_ids) == set(s3.lot_transaction_ids)


# ---------------------------------------------------------------------------
# Shadow comparison tests (compare with ledger_service.py grouping baseline)
# ---------------------------------------------------------------------------

class TestShadowComparison:
    """Verify group_manager produces same or better results than ledger_service."""

    def test_shadow_simple_open_close(self):
        """Single chain with open lots -> same result as chain-based grouping."""
        lots = [
            _lot(chain_id="C1", strike=170.0, option_type="Call", quantity=-1,
                 entry_date=datetime(2026, 1, 15, 10, 0)),
        ]
        chains = [_chain("C1", order_ids=["O1"])]

        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1
        assert specs[0].source_chain_ids == {"C1"}
        assert specs[0].status == "OPEN"

    def test_shadow_roll_chain(self):
        """Open -> roll -> close (single chain) -> 1 group, same as chain-based."""
        lots = [
            _lot(chain_id="C1", expiration=date(2026, 3, 21), remaining_quantity=0,
                 status="CLOSED", entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="C1", expiration=date(2026, 4, 18),
                 entry_date=datetime(2026, 3, 20, 10, 0)),
        ]
        chains = [_chain("C1", order_ids=["O1", "O2"])]

        specs = assign_lots_to_groups(lots, chains)
        # Chain-based grouping: 1 group for chain C1
        assert len(specs) == 1
        assert specs[0].source_chain_ids == {"C1"}

    def test_shadow_iron_condor_cross_order(self):
        """Put spread + call spread as separate orders -> IMPROVEMENT: 1 group vs 2.

        ledger_service.py would produce 2 groups (one per chain).
        group_manager merges them into 1 "Iron Condor" group.
        """
        exp = date(2026, 4, 18)
        lots = [
            _lot(chain_id="CA", option_type="Put", strike=160.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="CA", option_type="Put", strike=155.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(chain_id="CB", option_type="Call", strike=180.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 11, 0)),
            _lot(chain_id="CB", option_type="Call", strike=185.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 11, 0)),
        ]
        chains = [
            _chain("CA", order_ids=["OA"]),
            _chain("CB", order_ids=["OB"]),
        ]

        # Old behavior: 2 groups (one per chain)
        # New behavior: 1 group
        specs = assign_lots_to_groups(lots, chains)
        assert len(specs) == 1  # IMPROVEMENT over ledger_service
        assert specs[0].strategy_label == "Iron Condor"

    def test_shadow_equity_ungrouped(self):
        """Equity lots with no chain -> same 'Shares' group as ledger_service."""
        lots = [
            _equity_lot(chain_id=None,
                        entry_date=datetime(2026, 1, 10, 10, 0)),
            _equity_lot(chain_id=None,
                        entry_date=datetime(2026, 1, 12, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots, [])
        # Both should be in same group (same account + underlying, Rule 2b)
        assert len(specs) == 1
        assert len(specs[0].lot_transaction_ids) == 2


# ---------------------------------------------------------------------------
# DB integration tests
# ---------------------------------------------------------------------------

class TestGroupPersister:
    """Integration tests with real SQLite DB."""

    def _insert_lot(self, session, **kwargs):
        """Insert a PositionLot row directly."""
        from src.database.models import PositionLot as PositionLotModel
        defaults = dict(
            transaction_id=f"tx-{uuid.uuid4().hex[:8]}",
            account_number="ACCT1",
            symbol="AAPL  260321C00170000",
            underlying="AAPL",
            instrument_type="EQUITY_OPTION",
            option_type="Call",
            strike=170.0,
            expiration="2026-03-21",
            quantity=-1,
            entry_price=2.50,
            entry_date="2026-01-15T10:00:00",
            remaining_quantity=-1,
            original_quantity=1,
            status="OPEN",
            leg_index=0,
        )
        defaults.update(kwargs)
        row = PositionLotModel(**defaults)
        session.add(row)
        session.flush()
        return row

    def _insert_closing(self, session, lot_id, **kwargs):
        """Insert a LotClosing row directly."""
        from src.database.models import LotClosing as LotClosingModel
        defaults = dict(
            lot_id=lot_id,
            closing_order_id="ORD-CLOSE",
            closing_transaction_id=None,
            quantity_closed=1,
            closing_price=1.00,
            closing_date="2026-02-15T10:00:00",
            closing_type="MANUAL",
            realized_pnl=150.0,
        )
        defaults.update(kwargs)
        row = LotClosingModel(**defaults)
        session.add(row)
        session.flush()
        return row

    def test_process_groups_persists(self, db, lot_manager):
        """GroupPersister creates PositionGroup + PositionGroupLot rows."""
        from src.database.models import PositionGroup, PositionGroupLot

        # Insert lots directly
        with db.get_session() as session:
            lot1 = self._insert_lot(session, transaction_id="tx-A", chain_id="C1")
            lot2 = self._insert_lot(session, transaction_id="tx-B", chain_id="C1",
                                    strike=165.0, option_type="Put")

        chains = [_chain("C1", order_ids=["O1"])]
        persister = GroupPersister(db, lot_manager)
        count = persister.process_groups(chains)

        assert count >= 1

        with db.get_session() as session:
            groups = session.query(PositionGroup).all()
            assert len(groups) >= 1

            links = session.query(PositionGroupLot).all()
            txn_ids = {link.transaction_id for link in links}
            assert "tx-A" in txn_ids
            assert "tx-B" in txn_ids

    def test_reprocess_preserves_group_ids(self, db, lot_manager):
        """Reprocessing keeps same group UUIDs."""
        from src.database.models import PositionGroup

        with db.get_session() as session:
            self._insert_lot(session, transaction_id="tx-R1", chain_id="C1")

        chains = [_chain("C1", order_ids=["O1"])]
        persister = GroupPersister(db, lot_manager)

        # First run
        persister.process_groups(chains)
        with db.get_session() as session:
            groups1 = {g.group_id for g in session.query(PositionGroup).all()}

        # Second run (reprocess)
        persister.process_groups(chains)
        with db.get_session() as session:
            groups2 = {g.group_id for g in session.query(PositionGroup).all()}

        # Same UUIDs
        assert groups1 == groups2

    def test_closing_date_computed(self, db, lot_manager):
        """CLOSED group gets closing_date from lot_closings."""
        from src.database.models import PositionGroup

        with db.get_session() as session:
            lot = self._insert_lot(session, transaction_id="tx-CL1", chain_id="C1",
                                   remaining_quantity=0, status="CLOSED")
            self._insert_closing(session, lot.id,
                                 closing_date="2026-02-20T14:00:00")

        chains = [_chain("C1", order_ids=["O1"])]
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(chains)

        with db.get_session() as session:
            group = session.query(PositionGroup).first()
            assert group is not None
            assert group.status == "CLOSED"
            assert group.closing_date is not None
            assert "2026-02-20" in str(group.closing_date)

    def test_orphan_groups_deleted(self, db, lot_manager):
        """Group with no remaining lots is deleted on reprocess."""
        from src.database.models import PositionGroup, PositionGroupLot

        # Create a group manually that won't be covered by lots
        orphan_gid = str(uuid.uuid4())
        with db.get_session() as session:
            session.add(PositionGroup(
                group_id=orphan_gid,
                account_number="ACCT1",
                underlying="AAPL",
                status="OPEN",
            ))
            session.add(PositionGroupLot(
                group_id=orphan_gid,
                transaction_id="tx-ORPHAN",
            ))

        # Insert a real lot with a different chain
        with db.get_session() as session:
            self._insert_lot(session, transaction_id="tx-REAL", chain_id="C1")

        chains = [_chain("C1", order_ids=["O1"])]
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(chains)

        with db.get_session() as session:
            # Orphan group should be deleted
            orphan = session.query(PositionGroup).filter(
                PositionGroup.group_id == orphan_gid,
            ).first()
            assert orphan is None

            # Real group should exist
            groups = session.query(PositionGroup).all()
            assert len(groups) == 1
