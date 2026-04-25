"""Unit tests for the pure chain-queue helpers in position_ledger.py.

These cover the FIFO chain-pairing primitives that OPT-273 introduced:
- _build_chain_queue: walk closing tx's, build (chain_id, qty_taken) queue
- _assign_opens_to_chains: walk the queue, pair each opening tx with a chain
"""

from dataclasses import dataclass
from typing import Optional

from src.pipeline.position_ledger import (
    _build_chain_queue,
    _assign_opens_to_chains,
)


@dataclass
class _Tx:
    id: str
    account_number: str
    symbol: str
    quantity: int


@dataclass
class _Lot:
    id: int
    chain_id: Optional[str]
    remaining_quantity: int


def _stub_get_open_lots(lot_index):
    """Return a stub callable mimicking LotManager.get_open_lots, returning
    lots from a precomputed dict keyed by (account, symbol).
    """
    def fn(*, account_number, symbol):
        return list(lot_index.get((account_number, symbol), []))
    return fn


# ---------------------------------------------------------------------------
# _build_chain_queue
# ---------------------------------------------------------------------------

class TestBuildChainQueue:
    def test_single_close_single_chain(self):
        """One close transaction against one open lot should produce one queue entry covering the close's full quantity."""
        lots = _stub_get_open_lots({
            ("ACCT", "OPT"): [_Lot(id=1, chain_id="C1", remaining_quantity=-10)],
        })
        closes = [_Tx(id="t1", account_number="ACCT", symbol="OPT", quantity=10)]

        queue, chains = _build_chain_queue(closes, lots)

        assert queue == [("C1", 10)]
        assert chains == {"C1"}

    def test_single_close_spans_multiple_chains(self):
        """A single 30-contract close that walks two open lots (20 on chain C1, 10 on C2) should emit two queue entries reflecting the FIFO order, totaling 30."""
        lots = _stub_get_open_lots({
            ("ACCT", "OPT"): [
                _Lot(id=1, chain_id="C1", remaining_quantity=-20),
                _Lot(id=2, chain_id="C2", remaining_quantity=-10),
            ],
        })
        closes = [_Tx(id="t1", account_number="ACCT", symbol="OPT", quantity=30)]

        queue, chains = _build_chain_queue(closes, lots)

        assert queue == [("C1", 20), ("C2", 10)]
        assert chains == {"C1", "C2"}

    def test_multiple_closes_dont_double_claim(self):
        """Two closing transactions for the same symbol should not both claim the same lot — each claimed lot is taken off the table for subsequent transactions."""
        lots = _stub_get_open_lots({
            ("ACCT", "OPT"): [
                _Lot(id=1, chain_id="C1", remaining_quantity=-20),
                _Lot(id=2, chain_id="C2", remaining_quantity=-10),
            ],
        })
        closes = [
            _Tx(id="close-1", account_number="ACCT", symbol="OPT", quantity=20),
            _Tx(id="close-2", account_number="ACCT", symbol="OPT", quantity=10),
        ]

        queue, chains = _build_chain_queue(closes, lots)

        # First close consumes lot 1; second close consumes lot 2 (lot 1 is claimed)
        assert queue == [("C1", 20), ("C2", 10)]
        assert chains == {"C1", "C2"}

    def test_lot_without_chain_id_skipped(self):
        """Open lots that have no chain_id should be skipped entirely — they can't contribute to a roll's lineage."""
        lots = _stub_get_open_lots({
            ("ACCT", "OPT"): [
                _Lot(id=1, chain_id=None, remaining_quantity=-10),
                _Lot(id=2, chain_id="C1", remaining_quantity=-10),
            ],
        })
        closes = [_Tx(id="t1", account_number="ACCT", symbol="OPT", quantity=10)]

        queue, chains = _build_chain_queue(closes, lots)

        assert queue == [("C1", 10)]
        assert chains == {"C1"}

    def test_zero_remaining_lot_skipped(self):
        """A lot whose remaining_quantity is already 0 should not contribute to the queue — there's nothing left to close."""
        lots = _stub_get_open_lots({
            ("ACCT", "OPT"): [
                _Lot(id=1, chain_id="C1", remaining_quantity=0),
                _Lot(id=2, chain_id="C2", remaining_quantity=-5),
            ],
        })
        closes = [_Tx(id="t1", account_number="ACCT", symbol="OPT", quantity=5)]

        queue, chains = _build_chain_queue(closes, lots)

        assert queue == [("C2", 5)]
        assert chains == {"C2"}

    def test_no_open_lots_yields_empty(self):
        """If get_open_lots returns nothing, the queue and affected_chains are both empty."""
        lots = _stub_get_open_lots({})
        closes = [_Tx(id="t1", account_number="ACCT", symbol="OPT", quantity=10)]

        queue, chains = _build_chain_queue(closes, lots)

        assert queue == []
        assert chains == set()


# ---------------------------------------------------------------------------
# _assign_opens_to_chains
# ---------------------------------------------------------------------------

class TestAssignOpensToChains:
    def test_one_to_one_pairing(self):
        """Three opens with quantity 1 each, paired against three single-contract chains, should each inherit their own chain in queue order."""
        queue = [("A", 1), ("B", 1), ("C", 1)]
        opens = [
            _Tx(id="op-1", account_number="ACCT", symbol="OPT", quantity=1),
            _Tx(id="op-2", account_number="ACCT", symbol="OPT", quantity=1),
            _Tx(id="op-3", account_number="ACCT", symbol="OPT", quantity=1),
        ]

        result = _assign_opens_to_chains(opens, queue)

        assert result == {"op-1": "A", "op-2": "B", "op-3": "C"}

    def test_open_consumes_multiple_queue_entries(self):
        """A single 25-contract open against a queue of [(A, 10), (B, 5), (C, 20)] should advance through A and B and land on C — and a follow-on 5-contract open then takes the remainder of C."""
        queue = [("A", 10), ("B", 5), ("C", 20)]
        opens = [
            _Tx(id="op-25", account_number="ACCT", symbol="OPT", quantity=25),
            _Tx(id="op-5", account_number="ACCT", symbol="OPT", quantity=5),
        ]

        result = _assign_opens_to_chains(opens, queue)

        # First open inherits A (the head at start); the queue advances
        # past A and B (10+5=15 consumed, 25-15=10 left over) into C.
        # The second open arrives with the queue head at C.
        assert result["op-25"] == "A"
        assert result["op-5"] == "C"

    def test_mixed_quantity_alignment(self):
        """When opens are 30 then 10 against a queue of [(A, 30), (B, 10)], each open inherits the chain whose queue capacity covered it."""
        queue = [("A", 30), ("B", 10)]
        opens = [
            _Tx(id="op-30", account_number="ACCT", symbol="OPT", quantity=30),
            _Tx(id="op-10", account_number="ACCT", symbol="OPT", quantity=10),
        ]

        result = _assign_opens_to_chains(opens, queue)

        assert result == {"op-30": "A", "op-10": "B"}

    def test_asymmetric_excess_open_falls_back_to_last_chain(self):
        """When opens exceed the queue's total capacity, the extra opens inherit the last chain (a documented fallback for asymmetric rolls)."""
        queue = [("A", 5)]
        opens = [
            _Tx(id="op-5", account_number="ACCT", symbol="OPT", quantity=5),
            _Tx(id="op-extra", account_number="ACCT", symbol="OPT", quantity=3),
        ]

        result = _assign_opens_to_chains(opens, queue)

        assert result["op-5"] == "A"
        assert result["op-extra"] == "A"  # fallback

    def test_empty_queue_yields_empty_map(self):
        """An empty queue produces no chain assignments — callers fall back to the prior broadcast logic in that case."""
        queue = []
        opens = [_Tx(id="op-1", account_number="ACCT", symbol="OPT", quantity=1)]

        result = _assign_opens_to_chains(opens, queue)

        assert result == {}
