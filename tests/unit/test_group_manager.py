"""Unit tests for the Group Manager — pure function, shadow comparison, and DB integration."""

import pytest
import uuid
from datetime import datetime, date
from collections import defaultdict

from src.models.lot_manager import Lot
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


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------

class TestAssignLotsToGroups:

    def test_single_lot_creates_group(self):
        lots = [_lot()]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 1
        assert len(specs[0].lot_transaction_ids) == 1

    def test_same_expiration_lots_grouped(self):
        lots = [
            _lot(strike=170.0, option_type="Put",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(strike=165.0, option_type="Put",
                 entry_date=datetime(2026, 1, 15, 10, 1)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 1
        assert len(specs[0].lot_transaction_ids) == 2

    def test_different_underlying_different_groups(self):
        lots = [
            _lot(underlying="AAPL",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(underlying="MSFT", symbol="MSFT  260321C00300000",
                 entry_date=datetime(2026, 1, 15, 10, 1)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 2
        underlyings = {s.underlying for s in specs}
        assert underlyings == {"AAPL", "MSFT"}

    def test_cross_order_iron_condor(self):
        """Put spread + call spread same expiration -> 1 group, Iron Condor."""
        exp = date(2026, 4, 18)
        lots = [
            # Put spread
            _lot(option_type="Put", strike=160.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(option_type="Put", strike=155.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            # Call spread
            _lot(option_type="Call", strike=180.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5)),
            _lot(option_type="Call", strike=185.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 1
        assert specs[0].strategy_label == "Iron Condor"
        assert len(specs[0].lot_transaction_ids) == 4

    def test_cross_order_different_expiration(self):
        """Same underlying, different expirations -> 2 groups."""
        lots = [
            _lot(expiration=date(2026, 3, 21),
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(expiration=date(2026, 4, 18),
                 entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 2

    def test_equity_and_option_separate(self):
        """Short call + equity lot -> 2 groups (options and equity are always separate)."""
        lots = [
            _lot(option_type="Call", strike=180.0, quantity=-1,
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _equity_lot(quantity=100,
                        entry_date=datetime(2026, 1, 15, 10, 5)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 2

    def test_closed_equity_group_new_lot_new_group(self):
        """Existing equity group all CLOSED, new equity lot -> new group."""
        lots = [
            _equity_lot(remaining_quantity=0, status="CLOSED",
                        entry_date=datetime(2026, 1, 10, 10, 0)),
            _equity_lot(entry_date=datetime(2026, 2, 1, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 2
        statuses = {s.status for s in specs}
        assert statuses == {"OPEN", "CLOSED"}

    def test_roll_different_expirations_separate_groups(self):
        """Lots with different expirations -> separate groups (rolls detected post-hoc)."""
        lots = [
            _lot(expiration=date(2026, 3, 21), remaining_quantity=0,
                 status="CLOSED", entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(expiration=date(2026, 4, 18),
                 entry_date=datetime(2026, 3, 20, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots)
        # Different expirations = different groups
        assert len(specs) == 2

    def test_multiple_accounts_isolated(self):
        """Same underlying, different accounts -> 2 groups."""
        lots = [
            _lot(account_number="ACCT1",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(account_number="ACCT2",
                 entry_date=datetime(2026, 1, 15, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 2

    def test_strategy_label_from_engine(self):
        """Put spread legs -> 'Bull Put Spread'."""
        exp = date(2026, 3, 21)
        lots = [
            _lot(option_type="Put", strike=170.0, quantity=-1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
            _lot(option_type="Put", strike=165.0, quantity=1,
                 expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 1
        assert specs[0].strategy_label == "Bull Put Spread"

    def test_empty_lots_returns_empty(self):
        specs = assign_lots_to_groups([])
        assert specs == []

    def test_lots_without_expiration(self):
        """Orphan equity lot -> creates a group with 'Shares' label."""
        lots = [_equity_lot()]
        specs = assign_lots_to_groups(lots)
        assert len(specs) == 1
        assert "Shares" in specs[0].strategy_label or "Long" in specs[0].strategy_label

    def test_exercise_derived_equity_joins_equity_group(self):
        """Exercise-derived stock lot joins existing equity group.

        All equity lots should end up in ONE group regardless of chain_id.
        """
        eq1 = _equity_lot(
            underlying="IBIT", symbol="IBIT", chain_id="EQ-CHAIN-1",
            quantity=4800, entry_price=53.47,
            entry_date=datetime(2025, 5, 5, 14, 0),
        )
        eq2 = _equity_lot(
            underlying="IBIT", symbol="IBIT", chain_id="EQ-CHAIN-2",
            quantity=200, entry_price=61.95,
            entry_date=datetime(2025, 7, 9, 15, 0),
        )

        # LEAPS options (separate expiration)
        opt1 = _lot(
            chain_id="LEAPS-CHAIN", symbol="IBIT 251231C00047000",
            underlying="IBIT", option_type="Call", strike=47.0,
            expiration=date(2025, 12, 31), quantity=8, remaining_quantity=0,
            status="CLOSED", entry_date=datetime(2025, 6, 9, 15, 0),
        )
        opt2 = _lot(
            chain_id="LEAPS-CHAIN", symbol="IBIT 251231C00061000",
            underlying="IBIT", option_type="Call", strike=61.0,
            expiration=date(2025, 12, 31), quantity=-4, remaining_quantity=0,
            status="CLOSED", entry_date=datetime(2025, 6, 9, 15, 0),
        )

        # Exercise-derived stock lot — has LEAPS chain_id
        derived_eq = _equity_lot(
            underlying="IBIT", symbol="IBIT", chain_id="LEAPS-CHAIN",
            quantity=600, entry_price=47.0,
            entry_date=datetime(2025, 12, 31, 22, 0),
        )

        eq3 = _equity_lot(
            underlying="IBIT", symbol="IBIT", chain_id="EQ-CHAIN-3",
            quantity=1000, entry_price=42.20,
            entry_date=datetime(2026, 2, 3, 19, 0),
        )

        all_lots = [eq1, eq2, opt1, opt2, derived_eq, eq3]

        specs = assign_lots_to_groups(all_lots)

        shares_groups = [s for s in specs if s.strategy_label and "Shares" in s.strategy_label]
        open_shares = [s for s in shares_groups if s.status == "OPEN"]

        assert len(open_shares) == 1
        equity_txn_ids = {eq1.transaction_id, eq2.transaction_id,
                          derived_eq.transaction_id, eq3.transaction_id}
        assert equity_txn_ids.issubset(set(open_shares[0].lot_transaction_ids))

        # LEAPS options in a separate group
        option_groups = [s for s in specs
                         if any(tid == opt1.transaction_id for tid in s.lot_transaction_ids)]
        assert len(option_groups) == 1
        assert derived_eq.transaction_id not in option_groups[0].lot_transaction_ids

    def test_chronological_ordering_invariant(self):
        """Lots in random order -> same result as sorted."""
        exp = date(2026, 4, 18)
        lot_a = _lot(option_type="Put", strike=160.0, quantity=-1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 0))
        lot_b = _lot(option_type="Put", strike=155.0, quantity=1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 1))
        lot_c = _lot(option_type="Call", strike=180.0, quantity=-1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 5))
        lot_d = _lot(option_type="Call", strike=185.0, quantity=1,
                     expiration=exp, entry_date=datetime(2026, 1, 15, 10, 6))

        specs_sorted = assign_lots_to_groups([lot_a, lot_b, lot_c, lot_d])
        specs_reversed = assign_lots_to_groups([lot_d, lot_c, lot_b, lot_a])
        specs_shuffled = assign_lots_to_groups([lot_c, lot_a, lot_d, lot_b])

        assert len(specs_sorted) == len(specs_reversed) == len(specs_shuffled)
        for s1, s2, s3 in zip(specs_sorted, specs_reversed, specs_shuffled):
            assert set(s1.lot_transaction_ids) == set(s2.lot_transaction_ids) == set(s3.lot_transaction_ids)


# ---------------------------------------------------------------------------
# Equity grouping tests
# ---------------------------------------------------------------------------

class TestEquityGrouping:
    """Verify equity lots group correctly by (account, underlying)."""

    def test_equity_same_underlying_one_group(self):
        """Two equity lots same underlying -> 1 group."""
        lots = [
            _equity_lot(entry_date=datetime(2026, 1, 10, 10, 0)),
            _equity_lot(entry_date=datetime(2026, 1, 12, 10, 0)),
        ]
        specs = assign_lots_to_groups(lots)
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

        with db.get_session() as session:
            lot1 = self._insert_lot(session, transaction_id="tx-A")
            lot2 = self._insert_lot(session, transaction_id="tx-B",
                                    strike=165.0, option_type="Put")

        persister = GroupPersister(db, lot_manager)
        count = persister.process_groups()

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
            self._insert_lot(session, transaction_id="tx-R1")

        persister = GroupPersister(db, lot_manager)

        persister.process_groups()
        with db.get_session() as session:
            groups1 = {g.group_id for g in session.query(PositionGroup).all()}

        persister.process_groups()
        with db.get_session() as session:
            groups2 = {g.group_id for g in session.query(PositionGroup).all()}

        assert groups1 == groups2

    def test_closing_date_computed(self, db, lot_manager):
        """CLOSED group gets closing_date from lot_closings."""
        from src.database.models import PositionGroup

        with db.get_session() as session:
            lot = self._insert_lot(session, transaction_id="tx-CL1",
                                   remaining_quantity=0, status="CLOSED")
            self._insert_closing(session, lot.id,
                                 closing_date="2026-02-20T14:00:00")

        persister = GroupPersister(db, lot_manager)
        persister.process_groups()

        with db.get_session() as session:
            group = session.query(PositionGroup).first()
            assert group is not None
            assert group.status == "CLOSED"
            assert group.closing_date is not None
            assert "2026-02-20" in str(group.closing_date)

    def test_orphan_groups_deleted(self, db, lot_manager):
        """Group with no remaining lots is deleted on reprocess."""
        from src.database.models import PositionGroup, PositionGroupLot

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

        with db.get_session() as session:
            self._insert_lot(session, transaction_id="tx-REAL")

        persister = GroupPersister(db, lot_manager)
        persister.process_groups()

        with db.get_session() as session:
            orphan = session.query(PositionGroup).filter(
                PositionGroup.group_id == orphan_gid,
            ).first()
            assert orphan is None

            groups = session.query(PositionGroup).all()
            assert len(groups) == 1

    def test_user_merged_groups_survive_reprocess(self, db, lot_manager):
        """User-merged groups should survive when lots are cleared and recreated."""
        from src.database.models import PositionGroup, PositionGroupLot

        merged_group_id = "merged-group-1"
        txn_ids = ["tx-share-1", "tx-share-2", "tx-share-3"]

        with db.get_session() as session:
            for txn_id in txn_ids:
                self._insert_lot(session,
                    transaction_id=txn_id,
                    symbol="IBIT", underlying="IBIT",
                    instrument_type="EQUITY", option_type=None,
                    strike=None, expiration=None,
                    quantity=100, remaining_quantity=100,
                    entry_date="2026-01-10T10:00:00",
                )

            session.add(PositionGroup(
                group_id=merged_group_id,
                account_number="ACCT1",
                underlying="IBIT",
                strategy_label="Shares",
                status="OPEN",
            ))
            for txn_id in txn_ids:
                session.add(PositionGroupLot(
                    group_id=merged_group_id,
                    transaction_id=txn_id,
                ))

        with db.get_session() as session:
            links = session.query(PositionGroupLot).all()
            assert len(links) == 3

        # Clear lots — links survive
        lot_manager.clear_all_lots()

        with db.get_session() as session:
            links = session.query(PositionGroupLot).all()
            assert len(links) == 3

        # Recreate lots with same transaction_ids
        with db.get_session() as session:
            for txn_id in txn_ids:
                self._insert_lot(session,
                    transaction_id=txn_id,
                    symbol="IBIT", underlying="IBIT",
                    instrument_type="EQUITY", option_type=None,
                    strike=None, expiration=None,
                    quantity=100, remaining_quantity=100,
                    entry_date="2026-01-10T10:00:00",
                )

        persister = GroupPersister(db, lot_manager)
        persister.process_groups()

        with db.get_session() as session:
            groups = session.query(PositionGroup).filter(
                PositionGroup.underlying == "IBIT",
            ).all()
            links = session.query(PositionGroupLot).filter(
                PositionGroupLot.group_id == merged_group_id,
            ).all()
            link_txns = {l.transaction_id for l in links}

            assert len(groups) == 1
            assert groups[0].group_id == merged_group_id
            assert link_txns == set(txn_ids)
