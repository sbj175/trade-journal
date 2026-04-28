"""Unit tests for lot-level roll lineage (OPT-284 Phase 2).

Two pure functions are tested:

* ``detect_lot_lineage`` — single source of truth for whether a newly-
  opened lot continued from a previously-closed lot. Pairs same-day,
  structurally-compatible closes and opens at the lot level. Each lot
  pairs at most once (spec §0.2).

* ``derive_rolled_from_group_id`` — projects lot-level lineage onto
  ``position_groups.rolled_from_group_id``. A group has a single
  rolled-from source iff every lot has a parent_lot_id in that source
  AND the source group is fully closed.
"""

import uuid

from src.database.models import (
    LotClosing,
    PositionGroup,
    PositionGroupLot,
    PositionLot,
)
from src.pipeline.lot_lineage import (
    derive_rolled_from_group_id,
    detect_lot_lineage,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_group(session, *, account="ACCT", underlying="AAPL",
                opening_date, closing_date=None, status="CLOSED",
                rolled_from=None, label="Covered Call"):
    gid = str(uuid.uuid4())
    session.add(PositionGroup(
        group_id=gid, account_number=account, underlying=underlying,
        strategy_label=label, status=status,
        opening_date=opening_date, closing_date=closing_date,
        rolled_from_group_id=rolled_from,
    ))
    session.flush()
    return gid


def _seed_lot(session, *, group_id, opt, qty, strike, entry_date,
              expiration, account="ACCT", underlying="AAPL",
              status="OPEN", remaining=None):
    txn = str(uuid.uuid4())
    lot = PositionLot(
        transaction_id=txn,
        account_number=account, symbol=f"X{strike}{opt}",
        underlying=underlying, instrument_type="EQUITY_OPTION",
        option_type=opt, strike=float(strike),
        expiration=expiration, quantity=qty, entry_price=1.0,
        remaining_quantity=qty if remaining is None else remaining,
        original_quantity=abs(qty),
        chain_id=f"C-{txn[:8]}", status=status,
        entry_date=entry_date,
    )
    session.add(lot)
    session.add(PositionGroupLot(group_id=group_id, transaction_id=txn))
    session.flush()
    return lot


def _close(session, *, lot, closing_date, closing_type="MANUAL"):
    session.add(LotClosing(
        lot_id=lot.id, closing_date=closing_date,
        closing_price=0.5, quantity_closed=abs(lot.quantity),
        closing_type=closing_type, closing_order_id=f"CO-{lot.id}",
        realized_pnl=0.0,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# detect_lot_lineage
# ---------------------------------------------------------------------------

class TestDetectLotLineage:
    def test_two_leg_vertical_roll_pairs_by_closest_strike(self, db):
        """Long-72 ↔ long-70 (distance 2); short-77 ↔ short-75 (distance 2). Each leg pairs by closest strike independently within its (option_type, direction) bucket."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl1 = _seed_lot(
                session, group_id=src, opt="P", qty=1, strike=70,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            sl2 = _seed_lot(
                session, group_id=src, opt="P", qty=-1, strike=75,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl1, closing_date="2025-03-14")
            _close(session, lot=sl2, closing_date="2025-03-14")
            tl1 = _seed_lot(
                session, group_id=tgt, opt="P", qty=1, strike=72,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl2 = _seed_lot(
                session, group_id=tgt, opt="P", qty=-1, strike=77,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            sl1_id, sl2_id = sl1.id, sl2.id
            tl1_txn, tl2_txn = tl1.transaction_id, tl2.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 2

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl1_txn).one().parent_lot_id == sl1_id
            assert session.query(PositionLot).filter_by(transaction_id=tl2_txn).one().parent_lot_id == sl2_id

    def test_roll_plus_add_pairs_only_closest_strike(self, db):
        """The IBIT case: 1 close at strike 39, 2 opens (40.5 and 42) of compatible shape. The 40.5 open is closer (1.5 vs 3.0), so it's the roll continuation; the 42 open has no closing counterpart and stays unpaired (new business). This is the bug OPT-283 catalogued and OPT-284 actually fixes."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-04-10T10:00:00+00:00",
            )
            tgt_roll = _seed_group(
                session, opening_date="2025-04-10T10:00:00+00:00",
                status="OPEN",
            )
            tgt_add = _seed_group(
                session, opening_date="2025-04-10T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=39,
                entry_date="2025-03-31T10:00:00+00:00",
                expiration="2025-04-10", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl, closing_date="2025-04-10")
            roll_lot = _seed_lot(
                session, group_id=tgt_roll, opt="C", qty=-1, strike=40.5,
                entry_date="2025-04-10T10:00:00+00:00",
                expiration="2025-04-24",
            )
            add_lot = _seed_lot(
                session, group_id=tgt_add, opt="C", qty=-1, strike=42,
                entry_date="2025-04-10T10:00:00+00:00",
                expiration="2025-04-17",
            )
            sl_id = sl.id
            roll_txn, add_txn = roll_lot.transaction_id, add_lot.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 1

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=roll_txn).one().parent_lot_id == sl_id
            assert session.query(PositionLot).filter_by(transaction_id=add_txn).one().parent_lot_id is None, (
                "Excess open of compatible shape with no closing counterpart "
                "must remain unpaired — that's the entire point of OPT-284"
            )

    def test_excludes_mid_life_rolled_out_legs(self, db):
        """A lot closed on a day OTHER than the target group's opening day cannot be a roll source for that target — closing-day vs opening-day must match. Repros the active-at-close behavior the old _detect_roll_links had to filter for explicitly; under lot-level pairing it falls out naturally."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            mid = _seed_lot(
                session, group_id=src, opt="P", qty=-1, strike=60,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=mid, closing_date="2025-03-01")  # earlier
            tl = _seed_lot(
                session, group_id=tgt, opt="P", qty=-1, strike=62,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 0

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl_txn).one().parent_lot_id is None

    def test_excludes_expiration_assignment_exercise_closings(self, db):
        """Per spec §2 only MANUAL closings count as roll candidates. A lot whose only same-day closing was EXPIRATION (or ASSIGNMENT or EXERCISE) cannot be a parent."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-21T10:00:00+00:00",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-21T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl, closing_date="2025-03-21",
                   closing_type="EXPIRATION")
            tl = _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-21T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 0

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl_txn).one().parent_lot_id is None

    def test_does_not_self_pair_same_day_open_and_close(self, db):
        """A lot that opens and closes on the same day must never be its own parent. Edge case: same-day open-and-close (e.g., a 0DTE scalp)."""
        with db.get_session() as session:
            grp = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                closing_date="2025-03-14T15:00:00+00:00",
            )
            same = _seed_lot(
                session, group_id=grp, opt="C", qty=-1, strike=100,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-03-14", status="CLOSED", remaining=0,
            )
            _close(session, lot=same, closing_date="2025-03-14")
            same_txn = same.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 0

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=same_txn).one().parent_lot_id is None

    def test_cross_account_does_not_pair(self, db):
        """A close in account A and an open in account B with otherwise compatible attrs must not pair. Cross-account links are out of scope (spec §1.1)."""
        with db.get_session() as session:
            srcA = _seed_group(
                session, account="A",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            tgtB = _seed_group(
                session, account="B",
                opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=srcA, account="A", opt="C", qty=-1,
                strike=100, entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl, closing_date="2025-03-14")
            tl = _seed_lot(
                session, group_id=tgtB, account="B", opt="C", qty=-1,
                strike=105, entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 0

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl_txn).one().parent_lot_id is None

    def test_shape_mismatch_does_not_pair(self, db):
        """A long-Put close cannot pair with a short-Put open even at the same strike. (option_type, direction) must match."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="P", qty=1, strike=70,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl, closing_date="2025-03-14")
            tl = _seed_lot(
                session, group_id=tgt, opt="P", qty=-1, strike=70,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        paired = detect_lot_lineage(db)
        assert paired == 0

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl_txn).one().parent_lot_id is None

    def test_idempotent_resets_and_redetects(self, db):
        """Running detect_lot_lineage twice must produce identical state — the first call clears all parent_lot_ids and pairs from scratch, and the second does the same. No accumulation, no overwrite of newer lineage by stale data."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close(session, lot=sl, closing_date="2025-03-14")
            tl = _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            sl_id = sl.id
            tl_txn = tl.transaction_id

        first = detect_lot_lineage(db)
        second = detect_lot_lineage(db)
        assert first == second == 1

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(transaction_id=tl_txn).one().parent_lot_id == sl_id


# ---------------------------------------------------------------------------
# derive_rolled_from_group_id
# ---------------------------------------------------------------------------

class TestDeriveRolledFromGroupId:
    def test_clean_roll_yields_single_source(self, db):
        """All lots in target have parent_lot_ids pointing at lots in the same source group, and the source is CLOSED → target.rolled_from_group_id = source."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
                status="CLOSED",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            tl = _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl.parent_lot_id = sl.id
            session.flush()

        derive_rolled_from_group_id(db)

        with db.get_session() as session:
            tgt_after = session.query(PositionGroup).filter_by(group_id=tgt).one()
            assert tgt_after.rolled_from_group_id == src

    def test_partial_lineage_yields_no_rolled_from(self, db):
        """If some lots in the group have parent_lot_id and others have NULL, that's a partial-leg adjustment — the group continues as itself, no group-level roll. rolled_from must remain NULL."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
                status="CLOSED",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            tl_paired = _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_unpaired = _seed_lot(
                session, group_id=tgt, opt="P", qty=-1, strike=90,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_paired.parent_lot_id = sl.id
            session.flush()

        derive_rolled_from_group_id(db)

        with db.get_session() as session:
            tgt_after = session.query(PositionGroup).filter_by(group_id=tgt).one()
            assert tgt_after.rolled_from_group_id is None

    def test_open_source_yields_no_rolled_from(self, db):
        """Even with all lots paired into a single source, if that source is still OPEN it isn't a roll completion — it's an adjustment with concurrent activity. rolled_from stays NULL."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                status="OPEN",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN",
            )
            sl = _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21",
            )
            tl = _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl.parent_lot_id = sl.id
            session.flush()

        derive_rolled_from_group_id(db)

        with db.get_session() as session:
            tgt_after = session.query(PositionGroup).filter_by(group_id=tgt).one()
            assert tgt_after.rolled_from_group_id is None

    def test_clears_stale_rolled_from(self, db):
        """A group with rolled_from previously set but no supporting lot lineage must have rolled_from cleared — derive is the single source of truth."""
        with db.get_session() as session:
            src = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
                status="CLOSED",
            )
            tgt = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=src,
            )
            _seed_lot(
                session, group_id=src, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _seed_lot(
                session, group_id=tgt, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            # Note: NOT setting parent_lot_id on tl. So lot lineage
            # doesn't support the stored rolled_from value.

        changes = derive_rolled_from_group_id(db)
        assert changes == 1

        with db.get_session() as session:
            tgt_after = session.query(PositionGroup).filter_by(group_id=tgt).one()
            assert tgt_after.rolled_from_group_id is None
