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
    """Minimal stub — _detect_roll_links only reads chain_id."""
    chain_id: Optional[str]


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
