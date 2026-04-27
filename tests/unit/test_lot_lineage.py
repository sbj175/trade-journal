"""Unit tests for backfill_parent_lot_ids — OPT-284 Phase 1.

Validates that the backfill pairs lots only in unambiguous cases and
leaves NULL where trader intent would be needed (the cases Phase 2
will solve at the detection layer).
"""

import uuid

from src.database.models import (
    LotClosing,
    PositionGroup,
    PositionGroupLot,
    PositionLot,
)
from src.pipeline.lot_lineage import backfill_parent_lot_ids


def _seed_group(session, *, account="ACCT", underlying="AAPL",
                opening_date, closing_date=None, status="CLOSED",
                rolled_from=None, label="Covered Call"):
    gid = str(uuid.uuid4())
    session.add(PositionGroup(
        group_id=gid,
        account_number=account,
        underlying=underlying,
        strategy_label=label,
        status=status,
        opening_date=opening_date,
        closing_date=closing_date,
        rolled_from_group_id=rolled_from,
    ))
    session.flush()
    return gid


def _seed_lot_in_group(session, *, group_id, opt, qty, strike,
                      entry_date, expiration, account="ACCT",
                      underlying="AAPL", status="OPEN", remaining=None):
    txn = str(uuid.uuid4())
    lot = PositionLot(
        transaction_id=txn,
        account_number=account, symbol=f"X{strike}{opt}",
        underlying=underlying, instrument_type="EQUITY_OPTION",
        option_type=opt, strike=float(strike),
        expiration=expiration, quantity=qty,
        entry_price=1.0,
        remaining_quantity=qty if remaining is None else remaining,
        original_quantity=abs(qty),
        chain_id=f"C-{txn[:8]}", status=status,
        entry_date=entry_date,
    )
    session.add(lot)
    session.add(PositionGroupLot(group_id=group_id, transaction_id=txn))
    session.flush()
    return lot


def _close_lot(session, *, lot, closing_date, qty=None):
    session.add(LotClosing(
        lot_id=lot.id,
        closing_date=closing_date,
        closing_price=0.5,
        quantity_closed=qty if qty is not None else abs(lot.quantity),
        closing_type="MANUAL",
        closing_order_id=f"CO-{lot.id}",
        realized_pnl=0.0,
    ))
    session.flush()


class TestBackfillUnambiguous:
    def test_simple_two_leg_roll_pairs_correctly(self, db):
        """A vertical-spread roll (long+short put) where both source and target have the same shape and counts: pair by sorted strike. Each new lot gets parent_lot_id pointing at the structurally compatible closed lot."""
        with db.get_session() as session:
            source = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=source,
            )
            # Source: long P 70 + short P 75
            sl1 = _seed_lot_in_group(
                session, group_id=source, opt="P", qty=1, strike=70,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            sl2 = _seed_lot_in_group(
                session, group_id=source, opt="P", qty=-1, strike=75,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close_lot(session, lot=sl1, closing_date="2025-03-14")
            _close_lot(session, lot=sl2, closing_date="2025-03-14")
            # Target: long P 72 + short P 77 (rolled up)
            tl1 = _seed_lot_in_group(
                session, group_id=target, opt="P", qty=1, strike=72,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl2 = _seed_lot_in_group(
                session, group_id=target, opt="P", qty=-1, strike=77,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            sl1_id, sl2_id = sl1.id, sl2.id
            tl1_txn, tl2_txn = tl1.transaction_id, tl2.transaction_id

        paired, skipped = backfill_parent_lot_ids(db)
        assert paired == 2
        assert skipped == 0

        with db.get_session() as session:
            tl1_after = session.query(PositionLot).filter_by(transaction_id=tl1_txn).one()
            tl2_after = session.query(PositionLot).filter_by(transaction_id=tl2_txn).one()
            # Sorted by (option_type, direction, strike): (P, long, 70) → (P, long, 72)
            #                                             (P, short, 75) → (P, short, 77)
            assert tl1_after.parent_lot_id == sl1_id, "long-72 should pair with long-70"
            assert tl2_after.parent_lot_id == sl2_id, "short-77 should pair with short-75"

    def test_excludes_mid_life_rolled_out_legs_from_source(self, db):
        """A source group that had a mid-life adjustment (one leg closed earlier than closing_date) should pair only the legs whose closing_date matches the source's closing_day. Active-at-close filter is in lot_lineage exactly as in _detect_roll_links."""
        with db.get_session() as session:
            source = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=source,
            )
            mid = _seed_lot_in_group(
                session, group_id=source, opt="P", qty=-1, strike=60,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            active = _seed_lot_in_group(
                session, group_id=source, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close_lot(session, lot=mid, closing_date="2025-03-01")  # mid-life
            _close_lot(session, lot=active, closing_date="2025-03-14")  # at close
            tl = _seed_lot_in_group(
                session, group_id=target, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            active_id = active.id
            tl_txn = tl.transaction_id

        paired, _ = backfill_parent_lot_ids(db)
        assert paired == 1

        with db.get_session() as session:
            tl_after = session.query(PositionLot).filter_by(transaction_id=tl_txn).one()
            assert tl_after.parent_lot_id == active_id


class TestBackfillAmbiguous:
    def test_count_mismatch_leaves_null(self, db):
        """The IBIT-style "roll + add": source closed 1 lot, target opens 2 lots of compatible shape. The 1-vs-2 count mismatch is the trader-intent question (which open continued the close?), so backfill must leave parent_lot_id NULL — Phase 2 will resolve via quantity-aware pairing at detection time."""
        with db.get_session() as session:
            source = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=source,
            )
            sl = _seed_lot_in_group(
                session, group_id=source, opt="C", qty=-1, strike=39,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-14", status="CLOSED", remaining=0,
            )
            _close_lot(session, lot=sl, closing_date="2025-03-14")
            tl1 = _seed_lot_in_group(
                session, group_id=target, opt="C", qty=-1, strike=40.5,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-24",
            )
            tl2 = _seed_lot_in_group(
                session, group_id=target, opt="C", qty=-1, strike=42,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-17",
            )
            tl1_txn, tl2_txn = tl1.transaction_id, tl2.transaction_id

        paired, skipped = backfill_parent_lot_ids(db)
        assert paired == 0
        assert skipped == 1

        with db.get_session() as session:
            for txn in (tl1_txn, tl2_txn):
                lot = session.query(PositionLot).filter_by(transaction_id=txn).one()
                assert lot.parent_lot_id is None, (
                    f"Ambiguous pairing must leave parent_lot_id NULL "
                    f"(transaction_id={txn})"
                )

    def test_shape_mismatch_leaves_null(self, db):
        """If the multisets of (option_type, direction) don't line up under sorted-zip — e.g., source closed a long put but target opened a short put — pairing is skipped entirely. Same intent: don't guess; defer to Phase 2."""
        with db.get_session() as session:
            source = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=source,
            )
            sl = _seed_lot_in_group(
                session, group_id=source, opt="P", qty=1, strike=70,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close_lot(session, lot=sl, closing_date="2025-03-14")
            tl = _seed_lot_in_group(
                session, group_id=target, opt="P", qty=-1, strike=70,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        paired, skipped = backfill_parent_lot_ids(db)
        assert paired == 0
        assert skipped == 1

        with db.get_session() as session:
            assert session.query(PositionLot).filter_by(
                transaction_id=tl_txn,
            ).one().parent_lot_id is None


class TestIdempotent:
    def test_running_twice_does_not_re_pair(self, db):
        """Backfill is part of the pipeline orchestrator and runs every reprocess. Running it on already-paired lots must not double-count or overwrite."""
        with db.get_session() as session:
            source = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=source,
            )
            sl = _seed_lot_in_group(
                session, group_id=source, opt="C", qty=-1, strike=100,
                entry_date="2025-02-21T10:00:00+00:00",
                expiration="2025-03-21", status="CLOSED", remaining=0,
            )
            _close_lot(session, lot=sl, closing_date="2025-03-14")
            tl = _seed_lot_in_group(
                session, group_id=target, opt="C", qty=-1, strike=105,
                entry_date="2025-03-14T10:00:00+00:00",
                expiration="2025-04-18",
            )
            tl_txn = tl.transaction_id

        first_paired, _ = backfill_parent_lot_ids(db)
        second_paired, _ = backfill_parent_lot_ids(db)

        assert first_paired == 1
        assert second_paired == 0, (
            "Already-set parent_lot_id must not be re-counted on re-run"
        )

        with db.get_session() as session:
            tl_after = session.query(PositionLot).filter_by(transaction_id=tl_txn).one()
            assert tl_after.parent_lot_id is not None
