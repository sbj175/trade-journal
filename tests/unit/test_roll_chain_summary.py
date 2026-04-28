"""Unit tests for populate_roll_chain_summaries — the rollup that
materializes one row per chain into roll_chain_summaries.

OPT-282: when the rolled_from graph branches (spec §5.2), the rollup
must emit one summary per leaf, not one per root.
"""

import uuid

from src.database.models import (
    LotClosing,
    PositionGroup,
    PositionGroupLot,
    PositionLot,
    RollChainSummary,
)
from src.pipeline.roll_chain_summary import populate_roll_chain_summaries


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


def _seed_lot_for_group(session, *, group_id, strike, expiration,
                        entry_date, account="ACCT", underlying="AAPL"):
    txn = str(uuid.uuid4())
    lot = PositionLot(
        transaction_id=txn,
        account_number=account, symbol=f"X{strike}",
        underlying=underlying, instrument_type="EQUITY_OPTION",
        option_type="C", strike=float(strike),
        expiration=expiration, quantity=-1,
        entry_price=1.0,
        remaining_quantity=0, original_quantity=1,
        chain_id=f"C-{txn[:8]}", status="CLOSED",
        entry_date=entry_date,
    )
    session.add(lot)
    session.add(PositionGroupLot(group_id=group_id, transaction_id=txn))
    session.flush()


class TestBranchingTree:
    def test_one_summary_per_leaf_when_chain_branches(self, db):
        """Spec §5.2: one source can roll into multiple children. Each leaf in the rolled_from tree must get its own summary row, even when leaves share upstream history. Without this, a parallel-roll position (e.g., one source rolling into BOTH a 41-strike branch and a 43-strike branch) would have one branch's chain disappear from the rollup table — the symptom that motivated this test."""
        with db.get_session() as session:
            # Root → A → leaf_short.   Root → B → C → leaf_deep.
            # Root branches at A vs B; both are children of Root.
            # leaf_short is at depth 2; leaf_deep is at depth 3.
            # Pre-fix BFS-from-root would only emit a summary with
            # current=leaf_deep (last visited) and lose leaf_short.
            root = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            a = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                closing_date="2025-03-21T10:00:00+00:00",
                rolled_from=root,
            )
            leaf_short = _seed_group(
                session, opening_date="2025-03-21T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            b = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                closing_date="2025-03-21T10:00:00+00:00",
                rolled_from=root,
            )
            c = _seed_group(
                session, opening_date="2025-03-21T10:00:00+00:00",
                closing_date="2025-03-28T10:00:00+00:00",
                rolled_from=b,
            )
            leaf_deep = _seed_group(
                session, opening_date="2025-03-28T10:00:00+00:00",
                status="OPEN", rolled_from=c,
            )
            # Each group needs at least one lot so the cumulative-PnL pass
            # can join lot rows; trivial single-leg short calls are fine.
            for gid, exp in [
                (root, "2025-03-14"), (a, "2025-03-21"),
                (leaf_short, "2025-03-28"),
                (b, "2025-03-21"), (c, "2025-03-28"),
                (leaf_deep, "2025-04-04"),
            ]:
                _seed_lot_for_group(
                    session, group_id=gid, strike=100, expiration=exp,
                    entry_date="2025-02-21T10:00:00+00:00",
                )

        count = populate_roll_chain_summaries(db)

        assert count == 2, (
            f"Expected one summary per leaf (2), got {count}. "
            f"Pre-fix BFS-from-root would return 1 here."
        )

        with db.get_session() as session:
            heads = {
                row.current_group_id
                for row in session.query(RollChainSummary).all()
            }
            assert heads == {leaf_short, leaf_deep}, (
                f"Both leaves must have a summary row. Got heads {heads}."
            )

            # Both summaries should also share the same root, since the
            # tree branches but starts at one ancestor.
            roots = {
                row.root_group_id
                for row in session.query(RollChainSummary).all()
            }
            assert roots == {root}

            # Chain lengths reflect the unique root→leaf path, not the
            # full tree size. leaf_short = 3 nodes; leaf_deep = 4 nodes.
            lengths = {
                row.current_group_id: row.chain_length
                for row in session.query(RollChainSummary).all()
            }
            assert lengths[leaf_short] == 3
            assert lengths[leaf_deep] == 4

    def test_linear_chain_still_produces_one_summary(self, db):
        """A linear chain (no branching) is the existing happy path: one root, one leaf, one summary. The new per-leaf logic must reduce to this case identically."""
        with db.get_session() as session:
            root = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00",
            )
            mid = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                closing_date="2025-03-21T10:00:00+00:00",
                rolled_from=root,
            )
            leaf = _seed_group(
                session, opening_date="2025-03-21T10:00:00+00:00",
                status="OPEN", rolled_from=mid,
            )
            for gid, exp in [
                (root, "2025-03-14"), (mid, "2025-03-21"),
                (leaf, "2025-03-28"),
            ]:
                _seed_lot_for_group(
                    session, group_id=gid, strike=100, expiration=exp,
                    entry_date="2025-02-21T10:00:00+00:00",
                )

        count = populate_roll_chain_summaries(db)

        assert count == 1
        with db.get_session() as session:
            row = session.query(RollChainSummary).one()
            assert row.root_group_id == root
            assert row.current_group_id == leaf
            assert row.chain_length == 3
            assert row.roll_count == 2


# ---------------------------------------------------------------------------
# Additive cumulative P&L across sibling chains (OPT-284 Phase 3)
# ---------------------------------------------------------------------------

def _seed_closed_lot(session, *, group_id, strike, realized_pnl,
                     account="ACCT", underlying="AAPL"):
    """Closed source lot with a single MANUAL closing row carrying the
    given realized_pnl. Used for the additivity test."""
    txn = str(uuid.uuid4())
    lot = PositionLot(
        transaction_id=txn,
        account_number=account, symbol=f"X{strike}",
        underlying=underlying, instrument_type="EQUITY_OPTION",
        option_type="C", strike=float(strike),
        expiration="2025-03-21", quantity=-1, entry_price=1.0,
        remaining_quantity=0, original_quantity=1,
        chain_id=f"C-{txn[:8]}", status="CLOSED",
        entry_date="2025-02-21T10:00:00+00:00",
    )
    session.add(lot)
    session.add(PositionGroupLot(group_id=group_id, transaction_id=txn))
    session.flush()
    session.add(LotClosing(
        lot_id=lot.id, closing_date="2025-03-14",
        closing_price=0.5, quantity_closed=1,
        closing_type="MANUAL", closing_order_id=f"CO-{lot.id}",
        realized_pnl=realized_pnl,
    ))
    session.flush()
    return lot


def _seed_open_child_lot(session, *, group_id, strike, parent_lot_id,
                         account="ACCT", underlying="AAPL"):
    """Open child lot whose parent_lot_id points at a previously-closed
    source lot. Carries an entry_price chosen so lot_premium is small;
    we only assert cumulative_realized_pnl in the additivity test."""
    txn = str(uuid.uuid4())
    lot = PositionLot(
        transaction_id=txn,
        account_number=account, symbol=f"Y{strike}",
        underlying=underlying, instrument_type="EQUITY_OPTION",
        option_type="C", strike=float(strike),
        expiration="2025-04-18", quantity=-1, entry_price=0.0,
        remaining_quantity=-1, original_quantity=1,
        chain_id=f"C-{txn[:8]}", status="OPEN",
        entry_date="2025-03-14T10:00:00+00:00",
        parent_lot_id=parent_lot_id,
    )
    session.add(lot)
    session.add(PositionGroupLot(group_id=group_id, transaction_id=txn))
    session.flush()
    return lot


class TestAdditivityAcrossSiblingChains:
    def test_partition_5_into_3_plus_2_cumulative_is_additive(self, db):
        """OPT-284 integrity fix: when a single source group A branches into two children B (3 lots) and C (2 lots), each lot in A pairs with exactly one child's lot. B's chain cumulative_realized_pnl must include only the 3 source lots that paired with B, and C's must include only the 2 that paired with C. Sum of chain totals = total of A's realized P&L (no double-counting of the shared trunk).

Pre-Phase-3 (group-level summing): both B and C would credit ALL of A's realized P&L to their own chain → double-counted.
        """
        with db.get_session() as session:
            a = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            c = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            # A: 5 lots, each closed with realized_pnl=100.0 → total 500.
            a_lots = [
                _seed_closed_lot(
                    session, group_id=a, strike=100 + i,
                    realized_pnl=100.0,
                )
                for i in range(5)
            ]
            # B inherits the first 3 of A's lots.
            for i in range(3):
                _seed_open_child_lot(
                    session, group_id=b, strike=110 + i,
                    parent_lot_id=a_lots[i].id,
                )
            # C inherits the last 2.
            for i in range(2):
                _seed_open_child_lot(
                    session, group_id=c, strike=120 + i,
                    parent_lot_id=a_lots[3 + i].id,
                )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            rows = {
                row.current_group_id: row
                for row in session.query(RollChainSummary).all()
            }
            assert set(rows) == {b, c}, "expected one summary per leaf"
            assert rows[b].cumulative_realized_pnl == 300.0, (
                "B's chain should include only the 3 source lots that "
                "paired into B, not all 5"
            )
            assert rows[c].cumulative_realized_pnl == 200.0, (
                "C's chain should include only the 2 source lots that "
                "paired into C, not all 5"
            )
            total = rows[b].cumulative_realized_pnl + rows[c].cumulative_realized_pnl
            assert total == 500.0, (
                "Summed chain totals must equal A's full realized P&L — "
                "this is the additivity invariant. Pre-fix: 500 + 500 = 1000."
            )

    def test_unpaired_leaf_lots_excluded_from_lineage(self, db):
        """If a leaf-group lot has parent_lot_id=NULL (e.g., the IBIT 42C add-on), only the lots that DO have a lineage walk contribute to cumulative_realized_pnl. The unpaired lot itself contributes its open-side premium via net_premium / cumulative_premium, but no upstream realized P&L."""
        with db.get_session() as session:
            a = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            paired_source = _seed_closed_lot(
                session, group_id=a, strike=100, realized_pnl=100.0,
            )
            unpaired_source = _seed_closed_lot(
                session, group_id=a, strike=101, realized_pnl=100.0,
            )
            # B has 2 lots: one paired into A's `paired_source`, one with
            # NULL parent (the add-on case).
            _seed_open_child_lot(
                session, group_id=b, strike=110,
                parent_lot_id=paired_source.id,
            )
            _seed_open_child_lot(
                session, group_id=b, strike=111, parent_lot_id=None,
            )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            row = session.query(RollChainSummary).filter_by(
                current_group_id=b,
            ).one()
            # Only `paired_source`'s realized P&L (100) is in B's lineage.
            # `unpaired_source` belongs to no chain (it stayed in A's
            # standalone history); B doesn't inherit it.
            assert row.cumulative_realized_pnl == 100.0
