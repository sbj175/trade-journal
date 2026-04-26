"""Golden-snapshot tests: feed a canonical fixture through the pipeline
and assert a stable, hand-curated view of the output.

These cover invariants that span every stage: chain inheritance, group
routing, rolled_from linkage, strategy-label stability across rolls,
and roll-chain summary computation. Today's pipeline-layer bugs
(OPT-270, OPT-273, OPT-274, OPT-275, OPT-276) would all have surfaced
as a diff against one well-chosen golden snapshot.

See OPT-278 for the broader test-depth strategy. The first fixture
here mirrors the user's real-world IBIT 9-roll covered call at smaller
scale — same essential shape, easier to read.
"""

from src.database.models import PositionGroup, PositionGroupLot, PositionLot, RollChainSummary
from src.pipeline.orchestrator import reprocess
from tests.fixtures import covered_call_4_roll


def _canonical_groups(db, underlying):
    """Return a stable, comparable view of all position_groups for an
    underlying — sorted, with volatile fields (UUIDs, timestamps)
    replaced by their position in the chain."""
    with db.get_session() as session:
        groups = session.query(PositionGroup).filter(
            PositionGroup.underlying == underlying,
        ).order_by(PositionGroup.opening_date).all()

        # Build a map: group_id (UUID) -> ordinal position so we can swap
        # opaque UUIDs for stable "G1, G2, ..." labels in the snapshot.
        ordinals = {g.group_id: f"G{i}" for i, g in enumerate(groups, 1)}

        snapshot = []
        for g in groups:
            # Lot composition (sorted) so order doesn't matter.
            lot_rows = session.query(
                PositionLot.symbol,
                PositionLot.quantity,
                PositionLot.chain_id,
            ).join(
                PositionGroupLot,
                (PositionGroupLot.transaction_id == PositionLot.transaction_id),
            ).filter(
                PositionGroupLot.group_id == g.group_id,
            ).all()
            lots = sorted(
                [
                    {
                        "symbol": r.symbol.strip(),
                        "quantity": r.quantity,
                        "chain_id": r.chain_id,
                    }
                    for r in lot_rows
                ],
                key=lambda x: (x["symbol"], x["quantity"]),
            )

            snapshot.append({
                "label": g.strategy_label,
                "status": g.status,
                "opening_day": (g.opening_date or "")[:10],
                "closing_day": (g.closing_date or "")[:10] if g.closing_date else None,
                "rolled_from": ordinals.get(g.rolled_from_group_id) if g.rolled_from_group_id else None,
                "lots": lots,
            })

        return snapshot


def _canonical_summaries(db, underlying):
    """Roll chain summaries — chain_length, roll_count, dates — sorted."""
    with db.get_session() as session:
        rows = session.query(RollChainSummary).filter(
            RollChainSummary.underlying == underlying,
        ).order_by(RollChainSummary.first_opened).all()
        return [
            {
                "chain_length": r.chain_length,
                "roll_count": r.roll_count,
                "first_opened": str(r.first_opened)[:10],
                "last_rolled": str(r.last_rolled)[:10] if r.last_rolled else None,
            }
            for r in rows
        ]


def test_covered_call_4_roll_golden_snapshot(db, lot_manager):
    """A 4-roll covered call ladder should produce a 5-deep position_group chain (initial open + 4 rolls), all labeled 'Short Call' (the recognizer doesn't see equity in this fixture, so it can't upgrade to 'Covered Call'), each linked to its predecessor via rolled_from_group_id, with chain identity propagated through every roll."""
    txs = covered_call_4_roll.transactions()

    reprocess(db, lot_manager, txs)

    groups = _canonical_groups(db, "ZTEST")
    summaries = _canonical_summaries(db, "ZTEST")

    # Five groups, one per generation in the chain
    assert len(groups) == 5

    # Every group on the same chain_id (chain inheritance through rolls)
    chain_ids = {lot["chain_id"] for g in groups for lot in g["lots"]}
    assert len(chain_ids) == 1, f"Chain inheritance broken — got {chain_ids}"

    # Every group is a Short Call (the recognizer's single-leg call label)
    assert [g["label"] for g in groups] == ["Short Call"] * 5

    # Statuses: first 4 closed (rolled out), 5th still open
    assert [g["status"] for g in groups] == ["CLOSED"] * 4 + ["OPEN"]

    # rolled_from forms the linked list G1←G2←G3←G4←G5
    assert [g["rolled_from"] for g in groups] == [None, "G1", "G2", "G3", "G4"]

    # Strikes per generation, in order
    expected_strikes = [38.0, 39.5, 40.0, 39.0, 39.0]
    actual_strikes = [g["lots"][0]["symbol"][-8:] for g in groups]
    # Strike encoded in symbol: last 8 chars are like "00038000" = 38.000
    decoded = [float(s) / 1000 for s in actual_strikes]
    assert decoded == expected_strikes

    # All quantities -32 (short)
    for g in groups:
        assert g["lots"][0]["quantity"] == -32

    # Roll chain summary: one chain, length 5, 4 rolls
    assert len(summaries) == 1
    assert summaries[0]["chain_length"] == 5
    assert summaries[0]["roll_count"] == 4
    assert summaries[0]["first_opened"] == "2025-02-11"
    assert summaries[0]["last_rolled"] == "2025-03-06"
