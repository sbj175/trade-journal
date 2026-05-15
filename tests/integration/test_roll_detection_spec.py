"""Parametrized spec test for roll detection.

One test function, one fixture module per spec scenario. Each fixture
declares what raw transactions to feed the pipeline and the expected
post-pipeline state. The runner builds a canonical view of the DB
state and compares it against `expected()`.

Adding a new spec branch is now: write a fixture module exposing
`SPEC_SECTION`, `DESCRIPTION`, `transactions()`, and `expected()`, then
append it to ``ALL_FIXTURES`` below. No new test class needed.

See ``docs/roll-detection-spec.md`` for the rules being tested and
OPT-281 for the discipline this enforces.
"""

import pytest

from src.database.models import (
    PositionGroup,
    PositionGroupLot,
    PositionLot,
    RollChainSummary,
)
from src.pipeline.orchestrator import reprocess

from tests.fixtures import covered_call_4_roll, roll_same_exp_diff_strike


# ---------------------------------------------------------------------------
# Fixture registry. To add a new scenario:
#   1. Write tests/fixtures/<scenario>.py exposing SPEC_SECTION,
#      DESCRIPTION, transactions(), expected().
#   2. Import it above.
#   3. Append (test_id, module) to ALL_FIXTURES.
# ---------------------------------------------------------------------------

ALL_FIXTURES = [
    ("covered_call_4_roll", covered_call_4_roll),
    ("roll_same_exp_diff_strike", roll_same_exp_diff_strike),
]


# ---------------------------------------------------------------------------
# Canonical view: a stable, comparable snapshot of post-pipeline DB state.
# Group UUIDs are replaced with ordinals (G1, G2, ...) sorted by
# (opening_date, first_lot_signature) so fixtures can reference rolled_from
# links by position rather than UUID, and so the ordering is deterministic
# even when two groups share an opening_date.
# ---------------------------------------------------------------------------

def _lot_view(row):
    """Stable, comparable view of one lot."""
    return {
        "option_type": row.option_type,
        "strike": row.strike,
        "expiration": str(row.expiration)[:10] if row.expiration else None,
        "quantity": row.quantity,
    }


def _first_lot_signature(lot_views):
    """Tie-break key when two groups share an opening_date."""
    if not lot_views:
        return ("", "", 0.0, 0)
    first = lot_views[0]
    return (
        first.get("expiration") or "",
        first.get("option_type") or "",
        first.get("strike") or 0.0,
        first.get("quantity") or 0,
    )


def _canonical_view(db, underlying):
    """Return ``{"groups": [...], "roll_chains": [...]}`` for an underlying."""
    with db.get_session() as session:
        groups = session.query(PositionGroup).filter(
            PositionGroup.underlying == underlying,
        ).all()

        # Build each group's lot list first so we can sort by lot signature.
        group_records = []
        for g in groups:
            lot_rows = session.query(
                PositionLot.symbol,
                PositionLot.quantity,
                PositionLot.option_type,
                PositionLot.strike,
                PositionLot.expiration,
            ).join(
                PositionGroupLot,
                (PositionGroupLot.transaction_id == PositionLot.transaction_id),
            ).filter(
                PositionGroupLot.group_id == g.group_id,
            ).all()

            lots = sorted(
                [_lot_view(r) for r in lot_rows],
                key=lambda l: (
                    l.get("expiration") or "",
                    l.get("option_type") or "",
                    l.get("strike") or 0.0,
                    l.get("quantity") or 0,
                ),
            )
            group_records.append((g, lots))

        # Sort groups by (opening_date, first-lot signature) for determinism.
        group_records.sort(
            key=lambda gl: (
                str(gl[0].opening_date or ""),
                _first_lot_signature(gl[1]),
            )
        )

        ordinals = {g.group_id: f"G{i}" for i, (g, _) in enumerate(group_records, 1)}

        snapshot_groups = [
            {
                "strategy_label": g.strategy_label,
                "status": g.status,
                "rolled_from": ordinals[g.rolled_from_group_id]
                    if g.rolled_from_group_id and g.rolled_from_group_id in ordinals
                    else None,
                "lots": lots,
            }
            for g, lots in group_records
        ]

        chain_rows = session.query(RollChainSummary).filter(
            RollChainSummary.underlying == underlying,
        ).order_by(RollChainSummary.first_opened, RollChainSummary.chain_length).all()
        snapshot_chains = [
            {"chain_length": c.chain_length, "roll_count": c.roll_count}
            for c in chain_rows
        ]

    return {"groups": snapshot_groups, "roll_chains": snapshot_chains}


# ---------------------------------------------------------------------------
# The single parametrized test.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fixture_module",
    [pytest.param(mod, id=name) for name, mod in ALL_FIXTURES],
)
def test_roll_spec_scenario(db, lot_manager, fixture_module):
    expected = fixture_module.expected()
    underlying = expected["underlying"]

    reprocess(db, lot_manager, fixture_module.transactions())

    actual = _canonical_view(db, underlying)

    spec_ref = getattr(fixture_module, "SPEC_SECTION", "(no spec ref)")
    description = getattr(fixture_module, "DESCRIPTION", "")

    assert actual["groups"] == expected["groups"], (
        f"\n--- Spec ref: {spec_ref} ---\n"
        f"{description}\n"
        f"\nExpected groups:\n{expected['groups']}\n"
        f"\nActual groups:\n{actual['groups']}"
    )
    assert actual["roll_chains"] == expected["roll_chains"], (
        f"\n--- Spec ref: {spec_ref} ---\n"
        f"{description}\n"
        f"\nExpected chains:\n{expected['roll_chains']}\n"
        f"\nActual chains:\n{actual['roll_chains']}"
    )
