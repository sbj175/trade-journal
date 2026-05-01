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
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from src.pipeline.lot_lineage import (
    build_chain_attribution,
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


# ---------------------------------------------------------------------------
# build_chain_attribution — pure unit tests with stub objects
# ---------------------------------------------------------------------------

@dataclass
class _GroupStub:
    """Minimal stub matching the fields build_chain_attribution reads."""
    group_id: str
    rolled_from_group_id: Optional[str]
    opening_date: str


@dataclass
class _LotStub:
    """Minimal stub matching the fields build_chain_attribution reads."""
    id: int
    transaction_id: str
    parent_lot_id: Optional[int]


def _build_inputs(groups, lots, group_lot_links):
    """Construct the four argument dicts build_chain_attribution wants
    from a flat list of stub data."""
    group_map = {g.group_id: g for g in groups}
    children_map = defaultdict(list)
    for g in groups:
        if g.rolled_from_group_id:
            children_map[g.rolled_from_group_id].append(g.group_id)
    lots_by_id = {l.id: l for l in lots}
    txn_to_group = {txn: gid for gid, txn in group_lot_links}
    return dict(
        group_map=group_map,
        children_map=children_map,
        lots_by_id=lots_by_id,
        txn_to_group=txn_to_group,
    )


class TestBuildChainAttribution:
    def test_partition_5_into_3_plus_2_attributes_by_descendant(self):
        """At a 5x→3+2 partition (the structural shape OPT-284 was built to fix), each source contract attributes to whichever child its descendant ended up in. No source lot is shared between sibling chains; sibling chain totals never overlap."""
        groups = [
            _GroupStub("A", None, "2025-01-01"),
            _GroupStub("B", "A", "2025-02-01"),
            _GroupStub("C", "A", "2025-02-01"),
        ]
        lots = [
            _LotStub(1, "tA1", None), _LotStub(2, "tA2", None),
            _LotStub(3, "tA3", None), _LotStub(4, "tA4", None),
            _LotStub(5, "tA5", None),
            _LotStub(11, "tB1", 1), _LotStub(12, "tB2", 2), _LotStub(13, "tB3", 3),
            _LotStub(21, "tC1", 4), _LotStub(22, "tC2", 5),
        ]
        links = [
            ("A", "tA1"), ("A", "tA2"), ("A", "tA3"), ("A", "tA4"), ("A", "tA5"),
            ("B", "tB1"), ("B", "tB2"), ("B", "tB3"),
            ("C", "tC1"), ("C", "tC2"),
        ]

        chains_by_leaf, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        assert set(chains_by_leaf.keys()) == {"B", "C"}, "expected one chain per leaf"
        assert lot_to_leaf[1] == "B"
        assert lot_to_leaf[2] == "B"
        assert lot_to_leaf[3] == "B"
        assert lot_to_leaf[4] == "C"
        assert lot_to_leaf[5] == "C"
        assert lot_to_leaf[11] == "B"
        assert lot_to_leaf[12] == "B"
        assert lot_to_leaf[13] == "B"
        assert lot_to_leaf[21] == "C"
        assert lot_to_leaf[22] == "C"

    def test_multi_level_branch(self):
        """A → B + C, then C → D + E. Each lot's attribution follows its unique forward path. Lots in A whose descendants ended up in D's chain attribute to D, etc."""
        groups = [
            _GroupStub("A", None, "2025-01-01"),
            _GroupStub("B", "A", "2025-02-01"),
            _GroupStub("C", "A", "2025-02-01"),
            _GroupStub("D", "C", "2025-03-01"),
            _GroupStub("E", "C", "2025-03-01"),
        ]
        lots = [
            _LotStub(1, "tA1", None),
            _LotStub(2, "tA2", None),
            _LotStub(3, "tA3", None),
            _LotStub(11, "tB1", 1),
            _LotStub(12, "tC1", 2),
            _LotStub(13, "tC2", 3),
            _LotStub(21, "tD1", 12),
            _LotStub(22, "tE1", 13),
        ]
        links = [
            ("A", "tA1"), ("A", "tA2"), ("A", "tA3"),
            ("B", "tB1"),
            ("C", "tC1"), ("C", "tC2"),
            ("D", "tD1"),
            ("E", "tE1"),
        ]

        chains_by_leaf, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        assert set(chains_by_leaf.keys()) == {"B", "D", "E"}
        assert lot_to_leaf[1] == "B"
        assert lot_to_leaf[2] == "D"
        assert lot_to_leaf[3] == "E"
        assert lot_to_leaf[11] == "B"
        assert lot_to_leaf[12] == "D"
        assert lot_to_leaf[13] == "E"
        assert lot_to_leaf[21] == "D"
        assert lot_to_leaf[22] == "E"

    def test_orphan_lot_tiebreak_by_most_recent_leaf(self):
        """A lot in a branching source group with no descendants attributes to the chain whose leaf opened most recently — deterministic tiebreak so re-runs are stable and the orphan can't end up in two chains' totals."""
        groups = [
            _GroupStub("A", None, "2025-01-01"),
            _GroupStub("B", "A", "2025-02-01"),
            _GroupStub("C", "A", "2025-03-01"),  # most recent leaf — wins tiebreak
        ]
        lots = [
            _LotStub(1, "tA1", None),
            _LotStub(2, "tA2", None),
            _LotStub(99, "tA-orphan", None),
            _LotStub(11, "tB1", 1),
            _LotStub(12, "tC1", 2),
        ]
        links = [
            ("A", "tA1"), ("A", "tA2"), ("A", "tA-orphan"),
            ("B", "tB1"),
            ("C", "tC1"),
        ]

        _, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        assert lot_to_leaf[1] == "B"
        assert lot_to_leaf[2] == "C"
        assert lot_to_leaf[99] == "C", (
            "orphan lot should attribute to the chain whose leaf "
            "(C, opened 2025-03-01) opened most recently among the "
            "chains containing this branching group"
        )

    def test_standalone_group_lots_not_attributed(self):
        """A group with no rolled_from in or out is not part of any chain. Its lots have no entry in lot_to_leaf and contribute to no chain summary."""
        groups = [
            _GroupStub("X", None, "2025-01-01"),
        ]
        lots = [_LotStub(1, "tX1", None)]
        links = [("X", "tX1")]

        chains_by_leaf, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        assert chains_by_leaf == {}
        assert lot_to_leaf == {}

    def test_linear_chain_all_lots_attributed_to_unique_leaf(self):
        """Sanity: a clean A→B→C linear chain attributes every lot to the single leaf C, regardless of position in the chain."""
        groups = [
            _GroupStub("A", None, "2025-01-01"),
            _GroupStub("B", "A", "2025-02-01"),
            _GroupStub("C", "B", "2025-03-01"),
        ]
        lots = [
            _LotStub(1, "tA1", None),
            _LotStub(2, "tB1", 1),
            _LotStub(3, "tC1", 2),
        ]
        links = [("A", "tA1"), ("B", "tB1"), ("C", "tC1")]

        chains_by_leaf, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        assert set(chains_by_leaf.keys()) == {"C"}
        assert chains_by_leaf["C"] == ["A", "B", "C"]
        assert lot_to_leaf == {1: "C", 2: "C", 3: "C"}

    def test_cycle_in_parent_lot_id_does_not_infinite_loop(self):
        """Defensive smoke test: a corrupt parent_lot_id cycle must not hang the function. The visited-set guard in the forward walk catches it."""
        groups = [
            _GroupStub("A", None, "2025-01-01"),
            _GroupStub("B", "A", "2025-02-01"),
        ]
        # 2-cycle: lot 1 → 2 → 1
        lots = [
            _LotStub(1, "tA1", 2),
            _LotStub(2, "tB1", 1),
        ]
        links = [("A", "tA1"), ("B", "tB1")]

        chains_by_leaf, lot_to_leaf = build_chain_attribution(**_build_inputs(groups, lots, links))

        # B is non-branching, so the cycle is irrelevant to attribution
        # (pass 1 unique-attribution path doesn't walk children). Both
        # lots attributed; no hang.
        assert "B" in chains_by_leaf
        assert 1 in lot_to_leaf
        assert 2 in lot_to_leaf
