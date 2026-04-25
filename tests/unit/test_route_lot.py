"""Unit tests for _route_lot_to_group — the pure routing decision used
by both assign_lots_to_groups (Stage 5 pure) and GroupPersister (DB)."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.pipeline.group_manager import _route_lot_to_group


@dataclass
class _Lot:
    """Minimal stub matching the fields _route_lot_to_group reads."""
    chain_id: Optional[str]
    opening_order_id: Optional[str]
    account_number: str
    underlying: str
    expiration: Optional[date]
    option_type: Optional[str]
    strike: Optional[float]
    quantity: int
    remaining_quantity: int

    @property
    def is_long(self) -> bool:
        return self.quantity > 0


def _opt(strike, qty=-1, remaining=None, *, chain="C1", order="O1",
         exp=date(2026, 3, 21), option_type="C"):
    """Shorthand option lot. remaining defaults to qty (open)."""
    return _Lot(
        chain_id=chain, opening_order_id=order,
        account_number="ACCT", underlying="AAPL", expiration=exp,
        option_type=option_type, strike=strike, quantity=qty,
        remaining_quantity=qty if remaining is None else remaining,
    )


def _equity(qty=100, remaining=None):
    """Shorthand equity lot."""
    return _Lot(
        chain_id=None, opening_order_id=None,
        account_number="ACCT", underlying="AAPL", expiration=None,
        option_type=None, strike=None, quantity=qty,
        remaining_quantity=qty if remaining is None else remaining,
    )


def _route(lot, *, groups, aue=None, au=None, chains=None):
    return _route_lot_to_group(
        lot,
        groups_by_key=groups,
        aue_to_group=aue or {},
        au_to_group=au or {},
        chain_to_group=chains or {},
    )


# ---------------------------------------------------------------------------
# Rule 0 — chain-aware routing
# ---------------------------------------------------------------------------

class TestRule0ChainAware:
    def test_routes_to_existing_group_when_chain_matches_and_open(self):
        """A new lot whose chain_id is mapped to a still-open group should route to that group."""
        existing = _opt(100, qty=-1)
        groups = {"g1": [existing]}
        chains = {"C1": "g1"}
        new = _opt(105, chain="C1", order="O2")  # different strike → no Rule 1

        gk = _route(new, groups=groups, chains=chains)

        assert gk == "g1"

    def test_routes_to_closed_group_when_same_opening_order_id_present(self):
        """Even if the chained group looks closed in the routing snapshot, a new lot whose opening_order_id matches an existing lot should still merge there (multi-fill case)."""
        existing = _opt(100, qty=-1, remaining=0, order="O1")  # closed in snapshot
        groups = {"g1": [existing]}
        chains = {"C1": "g1"}
        new = _opt(100, chain="C1", order="O1")

        gk = _route(new, groups=groups, chains=chains)

        assert gk == "g1"

    def test_skips_closed_group_with_no_matching_order(self):
        """If the chained group is fully closed and no existing lot shares the new lot's order_id, Rule 0 falls through (caller will create a new group)."""
        existing = _opt(100, qty=-1, remaining=0, order="O1")
        groups = {"g1": [existing]}
        chains = {"C1": "g1"}
        new = _opt(105, chain="C1", order="O2", exp=date(2026, 4, 17))

        gk = _route(new, groups=groups, chains=chains)

        assert gk is None


# ---------------------------------------------------------------------------
# Rule 1 — option lots by (account, underlying, expiration)
# ---------------------------------------------------------------------------

class TestRule1OptionExpiration:
    def test_complementary_leg_merges(self):
        """An option lot at the same expiration as an open group should merge if it's structurally complementary (different option_type, strike, or direction)."""
        existing = _opt(100, qty=-1, option_type="P")  # short put 100
        groups = {"g1": [existing]}
        aue = {("ACCT", "AAPL", date(2026, 3, 21)): "g1"}
        new = _opt(110, qty=-1, option_type="C")  # short call — different option_type

        gk = _route(new, groups=groups, aue=aue)

        assert gk == "g1"

    def test_structural_duplicate_does_not_merge(self):
        """Two same-(option_type, strike, direction) lots at the same expiration should NOT merge — they're parallel positions, not the same one."""
        existing = _opt(100, qty=-1)  # short call 100
        groups = {"g1": [existing]}
        aue = {("ACCT", "AAPL", date(2026, 3, 21)): "g1"}
        new = _opt(100, qty=-1, chain="C2", order="O2")  # also short call 100

        gk = _route(new, groups=groups, aue=aue)

        assert gk is None

    def test_closed_group_does_not_match(self):
        """Rule 1 should not merge a new lot into a group whose lots are all already closed in the routing snapshot — that's a stale anchor."""
        existing = _opt(100, qty=-1, remaining=0)
        groups = {"g1": [existing]}
        aue = {("ACCT", "AAPL", date(2026, 3, 21)): "g1"}
        new = _opt(110, qty=-1, chain="C2", order="O2")

        gk = _route(new, groups=groups, aue=aue)

        assert gk is None


# ---------------------------------------------------------------------------
# Rule 2 — equity lots by (account, underlying)
# ---------------------------------------------------------------------------

class TestRule2Equity:
    def test_routes_to_open_equity_group(self):
        """A new equity lot should route to an existing open equity group on the same (account, underlying)."""
        existing = _equity(qty=100)
        groups = {"g1": [existing]}
        au = {("ACCT", "AAPL"): "g1"}
        new = _equity(qty=50)

        gk = _route(new, groups=groups, au=au)

        assert gk == "g1"

    def test_does_not_route_to_closed_equity_group(self):
        """A new equity lot should NOT route to a fully-closed equity group; the caller will create a new one."""
        existing = _equity(qty=100, remaining=0)
        groups = {"g1": [existing]}
        au = {("ACCT", "AAPL"): "g1"}
        new = _equity(qty=50)

        gk = _route(new, groups=groups, au=au)

        assert gk is None


# ---------------------------------------------------------------------------
# Rule 3 — fallthrough
# ---------------------------------------------------------------------------

class TestRule3NoMatch:
    def test_returns_none_when_no_indices_match(self):
        """A lot that matches none of the three rules should yield None — the caller mints a new group."""
        new = _opt(100)

        gk = _route(new, groups={})

        assert gk is None
