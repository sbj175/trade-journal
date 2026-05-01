"""Unit tests for compute_lot_fee_breakdown — the per-lot fee logic the
Ledger response uses (OPT-286).

Two pre-existing display bugs surfaced after OPT-285 collapsed
multi-fill lots into a single group:

1. Closing fees were attributed to every lot a closing touched in
   FULL — when one BTC transaction closed two lots, both lots saw the
   transaction's full fee, double-counting it on the displayed total.
2. Combined-fill open lots (lot_manager joins same-price fills into
   one lot whose `transaction_id` is comma-separated) had their open
   fees lost — the comma-separated string was looked up as a single
   key in fees_by_txn and returned 0.

These tests pin down the contract for both fixes.
"""

from dataclasses import dataclass
from typing import Optional

from src.routers.ledger import _txn_components, compute_lot_fee_breakdown


@dataclass
class _Lot:
    transaction_id: str


@dataclass
class _Closing:
    closing_id: int
    closing_transaction_id: Optional[str]
    quantity_closed: int


class TestTxnComponents:
    def test_single_id_returns_single_component(self):
        assert _txn_components("123") == ["123"]

    def test_comma_separated_splits(self):
        assert _txn_components("123,456,789") == ["123", "456", "789"]

    def test_empty_string_returns_empty_list(self):
        assert _txn_components("") == []

    def test_none_returns_empty_list(self):
        assert _txn_components(None) == []

    def test_whitespace_around_components_stripped(self):
        assert _txn_components("123, 456 , 789") == ["123", "456", "789"]


class TestClosingFeeApportionment:
    def test_one_close_one_lot_full_fee(self):
        """A closing transaction closing exactly one lot gets the full fee — no apportionment needed."""
        lot = _Lot(transaction_id="OPEN_1")
        closings = [_Closing(closing_id=1, closing_transaction_id="CLOSE_1", quantity_closed=10)]
        fees_by_txn = {"OPEN_1": 1.50, "CLOSE_1": 1.00}
        closing_txn_total_qty = {"CLOSE_1": 10}

        opening, per_closing = compute_lot_fee_breakdown(
            lot=lot, lot_closings=closings,
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty=closing_txn_total_qty,
        )

        assert opening == 1.50
        assert per_closing == [1.00]

    def test_one_close_two_lots_apportioned_by_quantity(self):
        """The IBIT bug: one BTC of 80 contracts (fee $9.84) closed two lots — 69 of A and 11 of B. Each lot's closing fee = $9.84 × (this lot's qty_closed) / 80."""
        # 69-contract lot (A)
        lot_a = _Lot(transaction_id="OPEN_A")
        closings_a = [_Closing(closing_id=1, closing_transaction_id="CLOSE", quantity_closed=69)]
        # 11-contract lot (B)
        lot_b = _Lot(transaction_id="OPEN_B")
        closings_b = [_Closing(closing_id=2, closing_transaction_id="CLOSE", quantity_closed=11)]

        fees_by_txn = {"OPEN_A": 0, "OPEN_B": 0, "CLOSE": 9.84}
        closing_txn_total_qty = {"CLOSE": 80}  # 69 + 11

        _, fees_a = compute_lot_fee_breakdown(
            lot=lot_a, lot_closings=closings_a,
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty=closing_txn_total_qty,
        )
        _, fees_b = compute_lot_fee_breakdown(
            lot=lot_b, lot_closings=closings_b,
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty=closing_txn_total_qty,
        )

        # 9.84 * 69 / 80 = 8.487; 9.84 * 11 / 80 = 1.353
        assert fees_a == [8.487]
        assert fees_b == [1.353]
        # Sum of apportioned fees equals the full transaction fee — no
        # double-counting, no loss.
        assert round(fees_a[0] + fees_b[0], 2) == 9.84

    def test_closing_with_no_transaction_id_gets_zero_fee(self):
        """A closing record without a closing_transaction_id (e.g., expiration or assignment) gets 0 fee — no transaction to look up."""
        lot = _Lot(transaction_id="OPEN_1")
        closings = [_Closing(closing_id=1, closing_transaction_id=None, quantity_closed=10)]
        fees_by_txn = {"OPEN_1": 0.50}
        closing_txn_total_qty = {}

        _, per_closing = compute_lot_fee_breakdown(
            lot=lot, lot_closings=closings,
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty=closing_txn_total_qty,
        )

        assert per_closing == [0]


class TestCombinedFillOpenFees:
    def test_combined_transaction_id_sums_component_fees(self):
        """The IBIT bug: a lot represents 3 same-price fills combined (33+16+20 contracts at $0.48). The lot's transaction_id is the comma-joined fill ids ("F1,F2,F3"). The fee lookup must decompose the string and sum each component's fee, not look up the whole compound string as a single key."""
        lot = _Lot(transaction_id="F1,F2,F3")
        fees_by_txn = {"F1": 4.169, "F2": 2.023, "F3": 2.526}

        opening, _ = compute_lot_fee_breakdown(
            lot=lot, lot_closings=[],
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty={},
        )

        # Sum = 4.169 + 2.023 + 2.526 = 8.718
        assert opening == 8.718

    def test_single_transaction_id_returns_its_fee(self):
        """Single-fill lot: fee is just that one transaction's fee. The decomposition is a no-op."""
        lot = _Lot(transaction_id="F1")
        fees_by_txn = {"F1": 11.39}

        opening, _ = compute_lot_fee_breakdown(
            lot=lot, lot_closings=[],
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty={},
        )

        assert opening == 11.39

    def test_missing_transaction_returns_zero(self):
        """Defensive: if a transaction id isn't in the fees map (e.g., the user reprocessed and the raw_transactions row was filtered out), the lookup returns 0 for that component instead of crashing."""
        lot = _Lot(transaction_id="F1,F2")
        fees_by_txn = {"F1": 5.0}  # F2 missing

        opening, _ = compute_lot_fee_breakdown(
            lot=lot, lot_closings=[],
            fees_by_txn=fees_by_txn,
            closing_txn_total_qty={},
        )

        # F1's 5.0 + F2's missing (treated as 0) = 5.0
        assert opening == 5.0
