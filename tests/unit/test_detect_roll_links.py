"""Direct unit tests for _detect_roll_links in group_manager.py.

OPT-270's chain-only matching invariant lives here; covering it
directly so regressions don't have to wait for an integration test
to surface.
"""

from dataclasses import dataclass
from typing import Optional
import uuid

from src.database.models import PositionGroup
from src.pipeline.group_manager import _detect_roll_links


@dataclass
class _Lot:
    """Minimal stub for _detect_roll_links. chain_id is the structural
    truth; option_type + quantity are read for the signature-match
    fallback (OPT-280)."""
    chain_id: Optional[str]
    option_type: Optional[str] = None
    quantity: int = 0


def _seed_group(
    session,
    *,
    account="ACCT",
    underlying="AAPL",
    label="Covered Call",
    status="OPEN",
    opening_date,
    closing_date=None,
    rolled_from=None,
):
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


def _detect(db, all_ids, group_lots):
    with db.get_session() as session:
        _detect_roll_links(session, all_ids, group_lots)
        # Re-fetch the rolled_from values for inspection
        return {
            row.group_id: row.rolled_from_group_id
            for row in session.query(PositionGroup).filter(
                PositionGroup.group_id.in_(all_ids),
            ).all()
        }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestRollLinkDetected:
    def test_close_then_open_same_day_same_chain(self, db):
        """Group A closed on 3/14 and group B opened on 3/14 sharing a chain id should produce a rolled_from link from B to A."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] == a
        assert result[a] is None  # A is the root; nothing rolled into it

    def test_serial_roll_a_to_b_to_c(self, db):
        """A roll on 3/14 (A→B) followed by another on 3/21 (B→C) should produce two links: B rolled_from A, and C rolled_from B."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="CLOSED",
                opening_date="2025-03-14T10:00:00+00:00",
                closing_date="2025-03-21T10:00:00+00:00",
            )
            c = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-21T10:00:00+00:00",
            )

        result = _detect(db, {a, b, c}, {
            a: [_Lot("C1")], b: [_Lot("C1")], c: [_Lot("C1")],
        })

        assert result[b] == a
        assert result[c] == b


# ---------------------------------------------------------------------------
# Filters: things that should NOT match
# ---------------------------------------------------------------------------

class TestRollLinkRejected:
    def test_no_link_without_chain_overlap(self, db):
        """Same date, same account, same underlying, but the two groups have disjoint chain ids — no link should form (chain_id is the structural truth, not date proximity)."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C2")]})

        assert result[b] is None

    def test_no_link_when_dates_differ(self, db):
        """A close on 3/14 and an open on 3/15 should not link — _detect_roll_links requires same calendar day."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-15T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] is None

    def test_different_accounts_dont_link(self, db):
        """Two groups in different accounts must not be linked even if chain id and dates align."""
        with db.get_session() as session:
            a = _seed_group(
                session, account="ACCT-A", status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, account="ACCT-B", status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] is None

    def test_different_underlyings_dont_link(self, db):
        """Different underlyings should never link, even with matching chain id and dates."""
        with db.get_session() as session:
            a = _seed_group(
                session, underlying="AAPL", status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, underlying="MSFT", status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] is None

    def test_already_linked_target_left_alone(self, db):
        """A target whose rolled_from_group_id is already set should not be re-linked, even if a fresh candidate also qualifies."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            existing_predecessor = "PREEXISTING-UUID"
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
                rolled_from=existing_predecessor,
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] == existing_predecessor

    def test_shares_groups_skipped(self, db):
        """Groups whose strategy_label is 'Shares' should be ignored entirely — equity holdings don't 'roll'."""
        with db.get_session() as session:
            a = _seed_group(
                session, label="Shares", status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, label="Shares", status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: [_Lot("C1")], b: [_Lot("C1")]})

        assert result[b] is None


# ---------------------------------------------------------------------------
# Tie-break
# ---------------------------------------------------------------------------

class TestTieBreak:
    def test_closer_lot_count_wins(self, db):
        """When two candidates qualify, the one whose lot count is closer to the target's should be selected."""
        with db.get_session() as session:
            a_two_lots = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            a_four_lots = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        # target B has 2 lots — should pair with A_two_lots, not A_four_lots
        result = _detect(db, {a_two_lots, a_four_lots, b}, {
            a_two_lots: [_Lot("C1"), _Lot("C1")],
            a_four_lots: [_Lot("C1"), _Lot("C1"), _Lot("C1"), _Lot("C1")],
            b: [_Lot("C1"), _Lot("C1")],
        })

        assert result[b] == a_two_lots


# ---------------------------------------------------------------------------
# Signature-match fallback (OPT-280)
# ---------------------------------------------------------------------------

# Iron Condor leg shape: long-put + short-put + short-call + long-call
def _ic_legs():
    return [
        _Lot("C1", option_type="P", quantity=1),
        _Lot("C1", option_type="P", quantity=-1),
        _Lot("C1", option_type="C", quantity=-1),
        _Lot("C1", option_type="C", quantity=1),
    ]


def _ic_legs_other_chain():
    return [_Lot("C2", option_type=l.option_type, quantity=l.quantity)
            for l in _ic_legs()]


class TestSignatureMatchFallback:
    def test_iron_condor_to_iron_condor_legs_out_and_in_links(self, db):
        """Per the docs: legging out of an Iron Condor and back into a new one the same day (separate broker orders, no chain overlap) should still be detected as a roll. The signature-match fallback handles this case — both groups have identical (option_type, sign) multisets."""
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {a, b}, {a: _ic_legs(), b: _ic_legs_other_chain()})

        assert result[b] == a

    def test_signature_mismatch_does_not_link(self, db):
        """A Bull Call Spread closing the same day a Put Butterfly opens should not link (OPT-261 phantom-strangle case): the signatures differ — calls only vs puts only — so no roll is detected even though account/underlying/day all match."""
        with db.get_session() as session:
            bcs = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-01T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            butterfly = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {bcs, butterfly}, {
            bcs: [
                _Lot("C1", option_type="C", quantity=1),
                _Lot("C1", option_type="C", quantity=-1),
            ],
            butterfly: [
                _Lot("C2", option_type="P", quantity=1),
                _Lot("C2", option_type="P", quantity=-1),
                _Lot("C2", option_type="P", quantity=-1),
                _Lot("C2", option_type="P", quantity=1),
            ],
        })

        assert result[butterfly] is None

    def test_signature_filtered_to_active_at_close_lots(self, db):
        """The signature comparison must use only the source group's lots that closed on its closing_date — rolled-out mid-life adjustments (closed earlier) must be excluded so they don't pollute the multiset. Real-world repro: a USO Iron Condor where the put wing was rolled mid-life left an extra closed-Jun-17 put spread on the group; that should not break the Jun 27 → Jun 27 IC roll detection."""
        from src.database.models import LotClosing
        with db.get_session() as session:
            a = _seed_group(
                session, status="CLOSED",
                opening_date="2025-06-02T10:00:00+00:00",
                closing_date="2025-06-27T16:00:00+00:00",
            )
            b = _seed_group(
                session, status="OPEN",
                opening_date="2025-06-27T16:00:00+00:00",
            )
            session.flush()

            from src.database.models import PositionLot
            def _seed_lot(*, opt, qty, closing_day, lot_attrs=None):
                lot = PositionLot(
                    transaction_id=str(uuid.uuid4()),
                    account_number="ACCT", symbol=f"X{opt}{qty}",
                    underlying="ACCT", instrument_type="EQUITY_OPTION",
                    option_type=opt, strike=100.0,
                    expiration="2025-07-18", quantity=qty,
                    entry_price=1.0,
                    remaining_quantity=0, original_quantity=abs(qty),
                    chain_id="C-A", status="CLOSED",
                    entry_date="2025-06-02T10:00:00+00:00",
                )
                session.add(lot); session.flush()
                if closing_day:
                    session.add(LotClosing(
                        lot_id=lot.id, closing_date=closing_day,
                        closing_price=0.0, quantity_closed=abs(qty),
                        closing_type="MANUAL", closing_order_id="ORD-X",
                        realized_pnl=0.0,
                    ))
                return lot

            # Source group A: 4 legs active at Jun 27 (the IB shape) PLUS
            # 2 historic put legs closed mid-life on Jun 17 (rolled out).
            # The filter must exclude the Jun 17 lots from the signature.
            a_lots = [
                _seed_lot(opt="P", qty=1, closing_day="2025-06-17"),     # rolled out
                _seed_lot(opt="P", qty=-1, closing_day="2025-06-17"),    # rolled out
                _seed_lot(opt="P", qty=1, closing_day="2025-06-27"),     # active long put
                _seed_lot(opt="P", qty=-1, closing_day="2025-06-27"),    # active short put
                _seed_lot(opt="C", qty=-1, closing_day="2025-06-27"),    # active short call
                _seed_lot(opt="C", qty=1, closing_day="2025-06-27"),     # active long call
            ]
            session.flush()
            a_lot_objs = [_Lot(chain_id="C-A", option_type=l.option_type, quantity=l.quantity) for l in a_lots]
            for stub, real in zip(a_lot_objs, a_lots):
                stub.id = real.id  # so the closing-day filter can find them

        # Target B is a fresh 4-leg IC on a different chain (legged in).
        b_lots = [
            _Lot("C-B", option_type="P", quantity=1),
            _Lot("C-B", option_type="P", quantity=-1),
            _Lot("C-B", option_type="C", quantity=-1),
            _Lot("C-B", option_type="C", quantity=1),
        ]

        result = _detect(db, {a, b}, {a: a_lot_objs, b: b_lots})

        assert result[b] == a, (
            "Source's active-at-close legs (4-leg IB shape) should match "
            "target's freshly-opened 4-leg IC, ignoring rolled-out put spread"
        )

    def test_chain_match_preferred_when_both_signal_present(self, db):
        """When two candidates qualify — one shares a chain_id with the target, the other only shares the leg-shape signature — the chain-overlap candidate must win. This preserves parallel-ladder roll behavior where multiple same-shape rungs roll on the same day in one ROLLING order."""
        with db.get_session() as session:
            chain_match = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            signature_only = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            target = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-14T10:00:00+00:00",
            )

        result = _detect(db, {chain_match, signature_only, target}, {
            chain_match: [_Lot("X", option_type="C", quantity=-1)],
            signature_only: [_Lot("Y", option_type="C", quantity=-1)],
            target: [_Lot("X", option_type="C", quantity=-1)],  # chain X
        })

        assert result[target] == chain_match


# ---------------------------------------------------------------------------
# Manual-close filter (spec §2)
# ---------------------------------------------------------------------------

def _seed_lot_with_closing(session, *, chain_id, opt, qty, closing_day, closing_type):
    """Create a real PositionLot + LotClosing row so _detect_roll_links
    sees the source's closing_type. Returns a _Lot stub with .id set so
    the routing-day index can find it."""
    from src.database.models import PositionLot, LotClosing
    lot = PositionLot(
        transaction_id=str(uuid.uuid4()),
        account_number="ACCT", symbol=f"X{opt}{qty}",
        underlying="ACCT", instrument_type="EQUITY_OPTION",
        option_type=opt, strike=100.0,
        expiration="2025-04-18", quantity=qty,
        entry_price=1.0,
        remaining_quantity=0, original_quantity=abs(qty),
        chain_id=chain_id, status="CLOSED",
        entry_date="2025-02-21T10:00:00+00:00",
    )
    session.add(lot); session.flush()
    session.add(LotClosing(
        lot_id=lot.id, closing_date=closing_day,
        closing_price=0.0, quantity_closed=abs(qty),
        closing_type=closing_type, closing_order_id="ORD-X",
        realized_pnl=0.0,
    ))
    stub = _Lot(chain_id=chain_id, option_type=opt, quantity=qty)
    stub.id = lot.id
    return stub


class TestManualCloseFilter:
    """Spec §2: a roll requires a manual closing event (BTC/STC).
    Expiration, assignment, and exercise are mutually exclusive with rolls."""

    def test_expiration_source_does_not_link(self, db):
        """Source whose only closing on closing_day was EXPIRATION must not link as a roll, even when chain_id and same-day open match."""
        with db.get_session() as session:
            source = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-21T16:00:00+00:00",
            )
            target = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-21T16:00:00+00:00",
            )
            session.flush()
            source_stub = _seed_lot_with_closing(
                session, chain_id="C-EXP", opt="C", qty=-1,
                closing_day="2025-03-21", closing_type="EXPIRATION",
            )

        result = _detect(db, {source, target}, {
            source: [source_stub],
            target: [_Lot("C-EXP", option_type="C", quantity=-1)],
        })

        assert result[target] is None, (
            "Expired source must not be picked as a roll source — the new "
            "same-day position is a fresh trade per spec §2"
        )

    def test_assignment_source_does_not_link(self, db):
        """Source closed by ASSIGNMENT (broker auto-close) must not link as a roll source even when chain and timing align."""
        with db.get_session() as session:
            source = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-21T16:00:00+00:00",
            )
            target = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-21T16:00:00+00:00",
            )
            session.flush()
            source_stub = _seed_lot_with_closing(
                session, chain_id="C-ASN", opt="P", qty=-1,
                closing_day="2025-03-21", closing_type="ASSIGNMENT",
            )

        result = _detect(db, {source, target}, {
            source: [source_stub],
            target: [_Lot("C-ASN", option_type="P", quantity=-1)],
        })

        assert result[target] is None

    def test_exercise_source_does_not_link(self, db):
        """Source closed by EXERCISE must not link as a roll source. Long-side counterpart of the assignment case."""
        with db.get_session() as session:
            source = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-21T16:00:00+00:00",
            )
            target = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-21T16:00:00+00:00",
            )
            session.flush()
            source_stub = _seed_lot_with_closing(
                session, chain_id="C-EX", opt="C", qty=1,
                closing_day="2025-03-21", closing_type="EXERCISE",
            )

        result = _detect(db, {source, target}, {
            source: [source_stub],
            target: [_Lot("C-EX", option_type="C", quantity=1)],
        })

        assert result[target] is None

    def test_manual_close_among_mixed_types_still_links(self, db):
        """A multi-leg source where SOME legs closed MANUAL and others closed via assignment/exercise on the same day still qualifies. The filter only rejects when *all* same-day closings are non-manual — at least one BTC/STC means the trader actively rolled."""
        with db.get_session() as session:
            source = _seed_group(
                session, status="CLOSED",
                opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-21T16:00:00+00:00",
            )
            target = _seed_group(
                session, status="OPEN",
                opening_date="2025-03-21T16:00:00+00:00",
            )
            session.flush()
            assigned_leg = _seed_lot_with_closing(
                session, chain_id="C-MIX", opt="P", qty=-1,
                closing_day="2025-03-21", closing_type="ASSIGNMENT",
            )
            manual_leg = _seed_lot_with_closing(
                session, chain_id="C-MIX", opt="C", qty=-1,
                closing_day="2025-03-21", closing_type="MANUAL",
            )

        result = _detect(db, {source, target}, {
            source: [assigned_leg, manual_leg],
            target: [_Lot("C-MIX", option_type="C", quantity=-1)],
        })

        assert result[target] == source
