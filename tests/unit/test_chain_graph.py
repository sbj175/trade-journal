"""
Unit tests for the chain_graph module (OPT-121 Stage 4).

Tests the pure ``build_order_graph()`` function and the DB-aware
``derive_chains()`` entry point.
"""

import pytest
from datetime import datetime

from src.pipeline.chain_graph import UnionFind, build_order_graph, derive_chains
from src.pipeline.order_assembler import assemble_orders
from src.models.order_processor import OrderProcessor
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_assignment_transaction,
)


# =====================================================================
# UnionFind unit tests
# =====================================================================

class TestUnionFind:
    def test_single_element(self):
        uf = UnionFind()
        uf.add("A")
        assert uf.find("A") == "A"
        comps = uf.components()
        assert len(comps) == 1
        assert {"A"} in comps.values()

    def test_union_two(self):
        uf = UnionFind()
        uf.add("A")
        uf.add("B")
        uf.union("A", "B")
        assert uf.find("A") == uf.find("B")
        comps = uf.components()
        assert len(comps) == 1
        assert {"A", "B"} in comps.values()

    def test_three_separate(self):
        uf = UnionFind()
        for x in ("A", "B", "C"):
            uf.add(x)
        comps = uf.components()
        assert len(comps) == 3

    def test_transitive_union(self):
        uf = UnionFind()
        for x in ("A", "B", "C"):
            uf.add(x)
        uf.union("A", "B")
        uf.union("B", "C")
        assert uf.find("A") == uf.find("C")
        comps = uf.components()
        assert len(comps) == 1
        assert {"A", "B", "C"} in comps.values()

    def test_duplicate_add_is_noop(self):
        uf = UnionFind()
        uf.add("A")
        uf.add("A")
        comps = uf.components()
        assert len(comps) == 1


# =====================================================================
# build_order_graph() — pure function tests
# =====================================================================

class TestBuildOrderGraph:
    def test_simple_open_close(self):
        """Single lot edge: opening -> closing → one component."""
        edges = [("ORD-OPEN", "ORD-CLOSE")]
        comps = build_order_graph(edges, [])
        assert len(comps) == 1
        vals = list(comps.values())
        assert vals[0] == {"ORD-OPEN", "ORD-CLOSE"}

    def test_roll_chain_three_orders(self):
        """Open → roll (close old + open new) → close: 3 orders in one chain."""
        lot_edges = [
            ("ORD-1", "ORD-2"),   # lot from ORD-1 closed by ORD-2
            ("ORD-2", "ORD-3"),   # lot from ORD-2 closed by ORD-3
        ]
        comps = build_order_graph(lot_edges, [])
        assert len(comps) == 1
        assert {"ORD-1", "ORD-2", "ORD-3"} in comps.values()

    def test_multi_leg_same_order(self):
        """4 lots with the same opening_order_id closed by same closing → single component."""
        lot_edges = [
            ("ORD-IC", "ORD-IC-CLOSE"),
            ("ORD-IC", "ORD-IC-CLOSE"),
            ("ORD-IC", "ORD-IC-CLOSE"),
            ("ORD-IC", "ORD-IC-CLOSE"),
        ]
        comps = build_order_graph(lot_edges, [])
        assert len(comps) == 1
        assert {"ORD-IC", "ORD-IC-CLOSE"} in comps.values()

    def test_chain_merge_via_closing(self):
        """A closing order connects two separate opening orders → merged component."""
        lot_edges = [
            ("ORD-OPEN-A", "ORD-CLOSE-BOTH"),
            ("ORD-OPEN-B", "ORD-CLOSE-BOTH"),
        ]
        comps = build_order_graph(lot_edges, [])
        assert len(comps) == 1
        assert {"ORD-OPEN-A", "ORD-OPEN-B", "ORD-CLOSE-BOTH"} in comps.values()

    def test_two_independent_chains(self):
        """Two separate open/close pairs → two components."""
        lot_edges = [
            ("ORD-A-OPEN", "ORD-A-CLOSE"),
            ("ORD-B-OPEN", "ORD-B-CLOSE"),
        ]
        comps = build_order_graph(lot_edges, [])
        assert len(comps) == 2
        sets = list(comps.values())
        assert {"ORD-A-OPEN", "ORD-A-CLOSE"} in sets
        assert {"ORD-B-OPEN", "ORD-B-CLOSE"} in sets

    def test_derived_lot_connection(self):
        """Derived edge bridges an assignment order to the parent chain."""
        lot_edges = [
            ("ORD-OPEN", "ORD-ASSIGN"),  # option closed by assignment
        ]
        derived_edges = [
            ("ORD-ASSIGN", "ORD-OPEN"),  # stock derived from option
        ]
        comps = build_order_graph(lot_edges, derived_edges)
        assert len(comps) == 1
        assert {"ORD-OPEN", "ORD-ASSIGN"} in comps.values()

    def test_derived_lot_with_stock_close(self):
        """Assignment bridges option chain to stock chain via derived edge."""
        lot_edges = [
            ("ORD-OPTION-OPEN", "ORD-ASSIGN"),   # option closed by assignment
            ("ORD-STOCK-OPEN", "ORD-STOCK-CLOSE"),  # stock lot closed separately
        ]
        derived_edges = [
            ("ORD-ASSIGN", "ORD-OPTION-OPEN"),  # derived stock -> parent option
        ]
        # ORD-STOCK-OPEN is a separate stock-only chain unless
        # ORD-STOCK-OPEN is actually ORD-ASSIGN (same order). In this test
        # they're different, so we get 2 components.
        comps = build_order_graph(lot_edges, derived_edges)
        assert len(comps) == 2

    def test_no_edges_empty(self):
        """No edges → no components."""
        comps = build_order_graph([], [])
        assert len(comps) == 0

    def test_orphan_not_in_edges(self):
        """Orders not referenced in any edge are not present in components."""
        lot_edges = [("ORD-A", "ORD-B")]
        comps = build_order_graph(lot_edges, [])
        all_ids = set()
        for s in comps.values():
            all_ids.update(s)
        assert "ORD-ORPHAN" not in all_ids

    def test_derived_only_edges(self):
        """Components can form from derived edges alone."""
        derived_edges = [
            ("ORD-STOCK", "ORD-OPTION"),
        ]
        comps = build_order_graph([], derived_edges)
        assert len(comps) == 1
        assert {"ORD-STOCK", "ORD-OPTION"} in comps.values()


# =====================================================================
# derive_chains() — integration tests (uses temp DB)
# =====================================================================

class TestDeriveChainsIntegration:
    """Process transactions via OrderProcessor, then call derive_chains()
    on the same DB state and verify outputs are consistent."""

    def test_simple_open_close(self, order_processor, db):
        """BTO → STC produces one chain with 2 orders."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="BUY_TO_OPEN",
                quantity=2, price=1.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="SELL_TO_CLOSE",
                quantity=2, price=3.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        assert len(new_chains) == 1
        assert new_chains[0].status == "CLOSED"
        new_ids = sorted(o.order_id for o in new_chains[0].orders)
        assert new_ids == ["ORD-CLOSE", "ORD-OPEN"]

    def test_roll_chain(self, order_processor, db):
        """Roll scenario: 3 orders should form a single chain."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-roll-close", order_id="ORD-2", action="BUY_TO_CLOSE",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-roll-open", order_id="ORD-2", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                symbol="AAPL 250418P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-final-close", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                symbol="AAPL 250418P00170000",
                executed_at="2025-04-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        assert len(new_chains) == 1
        assert new_chains[0].status == "CLOSED"
        new_ids = sorted(o.order_id for o in new_chains[0].orders)
        assert new_ids == ["ORD-1", "ORD-2", "ORD-3"]

    def test_iron_condor(self, order_processor, db):
        """4-leg IC open + close → single chain."""
        txs = [
            make_option_transaction(
                id="tx-sp", order_id="ORD-IC", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bp", order_id="ORD-IC", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321P00160000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sc", order_id="ORD-IC", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321C00190000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bc", order_id="ORD-IC", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321C00200000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-csp", order_id="ORD-IC-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=0.50,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-cbp", order_id="ORD-IC-CLOSE", action="SELL_TO_CLOSE",
                quantity=1, price=0.10,
                symbol="AAPL 250321P00160000",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-csc", order_id="ORD-IC-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=0.50,
                symbol="AAPL 250321C00190000",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-cbc", order_id="ORD-IC-CLOSE", action="SELL_TO_CLOSE",
                quantity=1, price=0.10,
                symbol="AAPL 250321C00200000",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        assert len(new_chains) == 1
        assert new_chains[0].status == "CLOSED"
        new_ids = sorted(o.order_id for o in new_chains[0].orders)
        assert new_ids == ["ORD-IC", "ORD-IC-CLOSE"]

    def test_partial_close_open_status(self, order_processor, db):
        """Partial close: chain stays OPEN with remaining lots."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=4, price=2.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=2, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        assert len(new_chains) == 1
        assert new_chains[0].status == "OPEN"

    def test_multi_account_isolation(self, order_processor, db):
        """Different accounts → separate chains."""
        txs = [
            make_option_transaction(
                id="tx-a1", order_id="ORD-A1", action="SELL_TO_OPEN",
                quantity=1, price=2.00, account_number="ACCT1",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-a2", order_id="ORD-A2", action="SELL_TO_OPEN",
                quantity=1, price=3.00, account_number="ACCT2",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        # Each account should have its own chain (orphan chains)
        assert len(new_chains) == 2
        accts = {c.account_number for c in new_chains}
        assert accts == {"ACCT1", "ACCT2"}

    def test_orphan_opening_only(self, order_processor, db):
        """An opening order with no closings → single-order orphan chain."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)

        assert len(new_chains) == 1
        assert len(new_chains[0].orders) == 1
        assert new_chains[0].status == "OPEN"

    def test_account_filter(self, order_processor, db):
        """account_number parameter restricts results to that account."""
        txs = [
            make_option_transaction(
                id="tx-a1", order_id="ORD-A1", action="SELL_TO_OPEN",
                quantity=1, price=2.00, account_number="ACCT1",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-a2", order_id="ORD-A2", action="SELL_TO_OPEN",
                quantity=1, price=3.00, account_number="ACCT2",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)  # creates lots in DB
        assembly = assemble_orders(txs)

        acct1_chains = derive_chains(db, assembly.orders, account_number="ACCT1")
        assert len(acct1_chains) == 1
        assert acct1_chains[0].account_number == "ACCT1"
