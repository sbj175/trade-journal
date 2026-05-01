"""Unit tests for populate_roll_chain_summaries — the rollup that
materializes one row per chain into roll_chain_summaries.

OPT-282: when the rolled_from graph branches (spec §5.2), the rollup
must emit one summary per leaf, not one per root.
"""

import uuid
from collections import defaultdict

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

    def test_chain_group_with_mixed_parent_lots_includes_all(self, db):
        """A chain group can contain lots with mixed parentage — some with parent_lot_id (lineage from a prior chain), some with parent_lot_id=NULL (a fresh adjustment that day). When the group is in only ONE chain (no branching at the group level), the attribution rule includes EVERY lot in the chain group toward that chain's cumulative_realized_pnl, matching what the chain modal shows.

This is the structural shape behind the user's IBIT 41-strike chain: chain root group b377a836 has lot 27754 (parent in a different upstream chain) and lot 27755 (parent=None — fresh add). Both belong to the 41-strike chain because b377a836 is in only that chain.
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
            # A has two closed lots: one with normal lineage (paired_src),
            # one with parent=NULL (a fresh adjustment that day).
            paired_source = _seed_closed_lot(
                session, group_id=a, strike=100, realized_pnl=100.0,
            )
            _seed_closed_lot(  # adjustment lot in A, parent=None
                session, group_id=a, strike=101, realized_pnl=50.0,
            )
            # B has one lot paired into A's `paired_source`.
            _seed_open_child_lot(
                session, group_id=b, strike=110,
                parent_lot_id=paired_source.id,
            )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            row = session.query(RollChainSummary).filter_by(
                current_group_id=b,
            ).one()
            # All of A's lots count toward B's chain — A is in only one
            # chain (B's), so attribution is unambiguous. Total = 100 + 50.
            assert row.cumulative_realized_pnl == 150.0, (
                "Both of A's lots should be attributed to B's chain — "
                "non-branching source group, all lots flow to the single "
                "downstream chain"
            )

    def test_lot_in_chain_does_not_pull_in_unrelated_chain(self, db):
        """When a chain group contains a lot whose parent_lot_id points into a DIFFERENT chain (e.g., the user's lot 27754 with parent in 2f4d359d's chain), the attribution rule does NOT pull the unrelated chain's lots into this chain's cumulative. Each chain stays isolated to its own group's lots.
        """
        with db.get_session() as session:
            # X → Y is a separate, completed chain ending at Y.
            x = _seed_group(
                session, opening_date="2025-01-01T10:00:00+00:00",
                closing_date="2025-01-15T10:00:00+00:00", status="CLOSED",
            )
            y = _seed_group(
                session, opening_date="2025-01-15T10:00:00+00:00",
                closing_date="2025-02-01T10:00:00+00:00", status="CLOSED",
                rolled_from=x,
            )
            x_lot = _seed_closed_lot(
                session, group_id=x, strike=80, realized_pnl=200.0,
            )
            y_lot = _seed_closed_lot(
                session, group_id=y, strike=82, realized_pnl=200.0,
            )

            # A → B is a separate chain. B has a lot whose parent_lot_id
            # is y_lot (an unrelated chain's lot).
            a = _seed_group(
                session, opening_date="2025-02-21T10:00:00+00:00",
                closing_date="2025-03-14T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-03-14T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            a_lot = _seed_closed_lot(
                session, group_id=a, strike=100, realized_pnl=100.0,
            )
            # Pin parent_lot_id of B's lot to y_lot — crossing chain
            # boundary in the lot graph but not in the rolled_from graph.
            from src.database.models import PositionLot, PositionGroupLot
            import uuid as _uuid_inner
            txn = str(_uuid_inner.uuid4())
            cross_lot = PositionLot(
                transaction_id=txn,
                account_number="ACCT", symbol=f"Y110",
                underlying="AAPL", instrument_type="EQUITY_OPTION",
                option_type="C", strike=110.0,
                expiration="2025-04-18", quantity=-1, entry_price=0.0,
                remaining_quantity=-1, original_quantity=1,
                chain_id=f"C-{txn[:8]}", status="OPEN",
                entry_date="2025-03-14T10:00:00+00:00",
                parent_lot_id=y_lot.id,  # cross-chain parent
            )
            session.add(cross_lot)
            session.add(PositionGroupLot(group_id=b, transaction_id=txn))
            session.flush()
            # Add a normal lineage lot too so B's chain is well-formed.
            _seed_open_child_lot(
                session, group_id=b, strike=111,
                parent_lot_id=a_lot.id,
            )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            rows = {
                r.current_group_id: r
                for r in session.query(RollChainSummary).all()
            }
            # B's chain: A's 100 + B's lots. The cross-chain `cross_lot`
            # is in group B, so it's IN this chain. Y's lots are NOT in
            # B's chain (they're in X→Y's chain).
            assert rows[b].cumulative_realized_pnl == 100.0, (
                "B's chain should sum its own groups' lots only — "
                "the cross-chain parent_lot_id link does NOT pull Y's "
                "realized P&L into B's chain total"
            )
            # Y's chain: X's 200 + Y's 200.
            assert rows[y].cumulative_realized_pnl == 400.0, (
                "Y's chain should be unaffected by B's cross-link; "
                "additivity preserved"
            )


# ---------------------------------------------------------------------------
# Rollup / modal consistency invariant (OPT-284 Phase 3c contract)
# ---------------------------------------------------------------------------

class TestRollupModalConsistency:
    """The contract OPT-284 was built to hold: the chain summary's
    ``cumulative_realized_pnl`` must equal the per-group breakdown the
    chain modal would display when summed across its rows.

    Both the rollup and the modal endpoint use ``build_chain_attribution``
    to decide which lots belong to a chain. These tests pin down the
    invariant: if either code path drifts (one starts bucketing
    differently, or the per-group sum diverges from the chain sum),
    the suite catches it. The user's IBIT 41-strike "row vs. modal"
    discrepancy was exactly this invariant breaking; any future change
    that re-introduces it should fail here.
    """

    def _modal_perchain_total(self, db, leaf_id):
        """Simulate what the chain modal endpoint computes for a chain:
        walk root → leaf via rolled_from_group_id, and for each group
        sum the realized P&L of lots attributed to this chain. Return
        the running total — the same number the modal renders as
        'Chain Realized'."""
        from src.pipeline.lot_lineage import build_chain_attribution
        from src.database.models import (
            LotClosing, PositionGroup, PositionGroupLot, PositionLot,
        )
        with db.get_session() as session:
            all_groups = session.query(PositionGroup).all()
            grp_map = {g.group_id: g for g in all_groups}
            children_map = defaultdict(list)
            for g in all_groups:
                if g.rolled_from_group_id:
                    children_map[g.rolled_from_group_id].append(g.group_id)
            all_lots = session.query(PositionLot).all()
            lots_by_id = {l.id: l for l in all_lots}
            txn_to_group = {}
            for gid, txn in session.query(
                PositionGroupLot.group_id, PositionGroupLot.transaction_id,
            ).all():
                txn_to_group[txn] = gid
            chains_by_leaf, lot_to_leaf = build_chain_attribution(
                group_map=grp_map, children_map=children_map,
                lots_by_id=lots_by_id, txn_to_group=txn_to_group,
            )
            chain_groups = chains_by_leaf.get(leaf_id, [])
            attributed = {lid for lid, lf in lot_to_leaf.items() if lf == leaf_id}
            closings = session.query(LotClosing).filter(
                LotClosing.lot_id.in_(list(attributed)) if attributed else False,
            ).all() if attributed else []
            closings_by_lot = defaultdict(list)
            for c in closings:
                closings_by_lot[c.lot_id].append(c)

            total = 0.0
            for gid in chain_groups:
                group_lots_in_chain = [
                    l for l in all_lots
                    if txn_to_group.get(l.transaction_id) == gid and l.id in attributed
                ]
                for lot in group_lots_in_chain:
                    for c in closings_by_lot.get(lot.id, []):
                        total += c.realized_pnl
            return total

    def test_summary_cumulative_equals_modal_perchain_total_linear(self, db):
        """For a clean linear chain (no branching), the rollup's cumulative_realized_pnl must equal the modal's per-row sum. Catches any drift between the two code paths in the most common case."""
        with db.get_session() as session:
            a = _seed_group(
                session, opening_date="2025-01-01T10:00:00+00:00",
                closing_date="2025-02-01T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            a_lot = _seed_closed_lot(
                session, group_id=a, strike=100, realized_pnl=250.0,
            )
            _seed_open_child_lot(
                session, group_id=b, strike=105, parent_lot_id=a_lot.id,
            )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            row = session.query(RollChainSummary).filter_by(
                current_group_id=b,
            ).one()
            cumulative = row.cumulative_realized_pnl

        modal_total = self._modal_perchain_total(db, leaf_id=b)
        assert cumulative == modal_total, (
            f"rollup cumulative ({cumulative}) must equal modal per-chain "
            f"total ({modal_total}) for linear chain"
        )

    def test_summary_cumulative_equals_modal_perchain_total_branching(self, db):
        """For a branching partition (one source A, two children B and C of the same shape), each chain summary's cumulative must equal what the modal renders for THAT chain. Sibling chains stay isolated, no double-counting of the trunk."""
        with db.get_session() as session:
            a = _seed_group(
                session, opening_date="2025-01-01T10:00:00+00:00",
                closing_date="2025-02-01T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            c = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            a_lots = [
                _seed_closed_lot(session, group_id=a, strike=100 + i,
                                 realized_pnl=100.0)
                for i in range(5)
            ]
            for i in range(3):
                _seed_open_child_lot(
                    session, group_id=b, strike=110 + i,
                    parent_lot_id=a_lots[i].id,
                )
            for i in range(2):
                _seed_open_child_lot(
                    session, group_id=c, strike=120 + i,
                    parent_lot_id=a_lots[3 + i].id,
                )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            rows = {
                r.current_group_id: r.cumulative_realized_pnl
                for r in session.query(RollChainSummary).all()
            }

        modal_b = self._modal_perchain_total(db, leaf_id=b)
        modal_c = self._modal_perchain_total(db, leaf_id=c)

        assert rows[b] == modal_b, (
            f"B's chain: rollup={rows[b]}, modal={modal_b}"
        )
        assert rows[c] == modal_c, (
            f"C's chain: rollup={rows[c]}, modal={modal_c}"
        )
        # Sibling chains are disjoint — totals add up to A's full P&L.
        assert (rows[b] + rows[c]) == 500.0, (
            f"branching chain totals must be additive across siblings — "
            f"B + C = {rows[b] + rows[c]}, expected 500.0"
        )

    def test_portfolio_additivity_across_all_chains(self, db):
        """Portfolio invariant: Σ cumulative_realized_pnl across every chain summary equals Σ realized_pnl across every closing whose lot is in any chain. No lot's P&L appears in two chains; no lot in a chain group has its P&L lost."""
        # Two independent chains: linear A→B and branching C→{D,E}.
        with db.get_session() as session:
            a = _seed_group(
                session, opening_date="2025-01-01T10:00:00+00:00",
                closing_date="2025-02-01T10:00:00+00:00", status="CLOSED",
            )
            b = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=a,
            )
            c = _seed_group(
                session, opening_date="2025-01-01T10:00:00+00:00",
                closing_date="2025-02-01T10:00:00+00:00", status="CLOSED",
            )
            d = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=c,
            )
            e = _seed_group(
                session, opening_date="2025-02-01T10:00:00+00:00",
                status="OPEN", rolled_from=c,
            )
            a_lot = _seed_closed_lot(
                session, group_id=a, strike=100, realized_pnl=300.0,
            )
            _seed_open_child_lot(
                session, group_id=b, strike=105, parent_lot_id=a_lot.id,
            )
            c_lots = [
                _seed_closed_lot(session, group_id=c, strike=200 + i,
                                 realized_pnl=50.0)
                for i in range(3)
            ]
            _seed_open_child_lot(
                session, group_id=d, strike=210, parent_lot_id=c_lots[0].id,
            )
            _seed_open_child_lot(
                session, group_id=d, strike=211, parent_lot_id=c_lots[1].id,
            )
            _seed_open_child_lot(
                session, group_id=e, strike=220, parent_lot_id=c_lots[2].id,
            )

        populate_roll_chain_summaries(db)

        with db.get_session() as session:
            sum_cumulative = sum(
                r.cumulative_realized_pnl
                for r in session.query(RollChainSummary).all()
            )

        # Expected: A's 300 + C's 3×50 = 300 + 150 = 450.
        assert sum_cumulative == 450.0, (
            f"Σ chain cumulatives ({sum_cumulative}) must equal Σ realized "
            f"P&L of attributed lots (450.0). If this fails, either a lot "
            f"is in 0 chains (its P&L is being lost) or a lot is in 2+ "
            f"chains (its P&L is being double-counted)."
        )
