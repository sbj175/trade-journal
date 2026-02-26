"""
Tests for src/pipeline/order_assembler — Stage 2 of OPT-121.

Verifies that the standalone order assembly functions (preprocess, group,
normalize, classify, create_orders, assemble_orders) work correctly.
"""

import pytest
from datetime import date

from src.pipeline.order_assembler import (
    AssemblyResult,
    Transaction,
    Order,
    OrderType,
    preprocess_transactions,
    group_transactions,
    normalize_transactions,
    classify_order,
    create_orders,
    assemble_orders,
)
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_expiration_transaction,
    make_assignment_transaction,
)


# ---------------------------------------------------------------------------
# preprocess_transactions
# ---------------------------------------------------------------------------

class TestPreprocessTransactions:
    """Tests for the preprocess_transactions() function."""

    def test_basic_option_transaction(self):
        raw = [make_option_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        assert len(assign_stocks) == 0
        tx = txs[0]
        assert tx.order_id == "ORD-001"
        assert tx.underlying_symbol == "AAPL"
        assert tx.action == "SELL_TO_OPEN"
        assert tx.option_type == "Call"
        assert tx.strike == 170.0
        assert tx.expiration == date(2025, 3, 21)

    def test_basic_stock_transaction(self):
        raw = [make_stock_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        tx = txs[0]
        assert tx.order_id == "ORD-STOCK-001"
        assert tx.underlying_symbol == "AAPL"
        assert tx.action == "BUY_TO_OPEN"
        assert tx.option_type is None

    def test_expiration_no_action_kept(self):
        """Expirations with action=None are kept (same as assignments/exercises).
        They get a synthetic order ID for chain derivation."""
        raw = [make_expiration_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)
        assert len(txs) == 1
        assert "SYSTEM_Expiration" in txs[0].order_id

    def test_expiration_with_action_gets_synthetic_order_id(self):
        """Expirations that have an action (rare edge case) get a synthetic ID."""
        raw = [make_expiration_transaction()]
        # Give it an action so it passes the filter
        raw[0]["action"] = "SELL_TO_CLOSE"
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        # With an action it uses the SYSTEM_ synthetic ID (since order_id is None)
        assert txs[0].order_id.startswith("SYSTEM_Expiration_")

    def test_assignment_option_gets_synthetic_order_id(self):
        raw = [make_assignment_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        tx = txs[0]
        assert tx.order_id.startswith("SYSTEM_Assignment_")

    def test_assignment_stock_captured_separately(self):
        """Stock transactions from assignment (no order_id) go to assign_stocks."""
        raw = [
            make_stock_transaction(
                id="tx-assign-stock",
                order_id=None,
                action="BUY_TO_OPEN",
                instrument_type="EQUITY",
            )
        ]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 0
        assert len(assign_stocks) == 1
        assert assign_stocks[0]["id"] == "tx-assign-stock"

    def test_acat_not_sidelined_as_assignment_stock(self):
        """ACAT transfers (no order_id, sub_type=ACAT) flow through normal
        processing and are NOT captured as assignment_stock_transactions."""
        raw = [
            make_stock_transaction(
                id="tx-acat",
                order_id=None,
                action="BUY_TO_OPEN",
                instrument_type="EQUITY",
                quantity=900,
                price=300.00,
                transaction_sub_type="ACAT",
                description="ACAT transfer",
            )
        ]
        txs, assign_stocks = preprocess_transactions(raw)

        # ACAT should NOT be sidelined
        assert len(assign_stocks) == 0
        # It should pass through as a normal transaction with a synthetic order ID
        assert len(txs) == 1
        assert "SYSTEM_ACAT" in txs[0].order_id

    def test_skips_no_symbol(self):
        raw = [{"id": "1", "symbol": None, "action": "BUY_TO_OPEN"}]
        txs, assign_stocks = preprocess_transactions(raw)
        assert len(txs) == 0

    def test_skips_no_action_non_special(self):
        raw = [
            {
                "id": "1",
                "symbol": "AAPL",
                "action": None,
                "transaction_sub_type": "Dividend",
                "instrument_type": "EQUITY",
            }
        ]
        txs, assign_stocks = preprocess_transactions(raw)
        assert len(txs) == 0

    def test_symbol_change_grouping(self):
        """Symbol Change transactions get synthetic order IDs grouped by date."""
        raw = [
            {
                "id": "sc-close-1",
                "account_number": "ACCT1",
                "order_id": None,
                "symbol": "OLD  250321C00100000",
                "underlying_symbol": "OLD",
                "action": "BUY_TO_CLOSE",
                "quantity": 1,
                "price": 0.0,
                "executed_at": "2025-03-15T10:00:00+00:00",
                "instrument_type": "EQUITY_OPTION",
                "transaction_type": "Trade",
                "transaction_sub_type": "Symbol Change",
                "description": "Symbol change close",
                "value": 0.0,
                "net_value": 0.0,
                "commission": 0.0,
                "regulatory_fees": 0.0,
                "clearing_fees": 0.0,
            },
            {
                "id": "sc-open-1",
                "account_number": "ACCT1",
                "order_id": None,
                "symbol": "NEW  250321C00100000",
                "underlying_symbol": "OLD",
                "action": "SELL_TO_OPEN",
                "quantity": 1,
                "price": 0.0,
                "executed_at": "2025-03-15T10:00:00+00:00",
                "instrument_type": "EQUITY_OPTION",
                "transaction_type": "Trade",
                "transaction_sub_type": "Symbol Change",
                "description": "Symbol change open",
                "value": 0.0,
                "net_value": 0.0,
                "commission": 0.0,
                "regulatory_fees": 0.0,
                "clearing_fees": 0.0,
            },
        ]
        txs, _ = preprocess_transactions(raw)

        assert len(txs) == 2
        close_tx = [t for t in txs if "TO_CLOSE" in t.action][0]
        open_tx = [t for t in txs if "TO_OPEN" in t.action][0]

        assert close_tx.order_id == "SYMCHG_CLOSE_ACCT1_OLD_2025-03-15"
        assert close_tx.underlying_symbol == "OLD"
        assert open_tx.order_id == "SYMCHG_OPEN_ACCT1_NEW_2025-03-15"
        assert open_tx.underlying_symbol == "NEW"

    def test_option_parsing_put(self):
        raw = [
            make_option_transaction(
                symbol="SPY  250418P00550000",
                option_type="Put",
                strike=550.0,
                expiration="2025-04-18",
            )
        ]
        txs, _ = preprocess_transactions(raw)

        tx = txs[0]
        assert tx.option_type == "Put"
        assert tx.strike == 550.0
        assert tx.expiration == date(2025, 4, 18)

    def test_multiple_transactions(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", order_id="ORD-2", action="BUY_TO_CLOSE"),
        ]
        txs, _ = preprocess_transactions(raw)
        assert len(txs) == 2


# ---------------------------------------------------------------------------
# group_transactions
# ---------------------------------------------------------------------------

class TestGroupTransactions:
    """Tests for the group_transactions() function."""

    def test_groups_by_account_underlying_order(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", order_id="ORD-1"),
            make_option_transaction(id="tx-3", order_id="ORD-2"),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)

        assert len(grouped) == 2
        assert len(grouped[("ACCT1", "AAPL", "ORD-1")]) == 2
        assert len(grouped[("ACCT1", "AAPL", "ORD-2")]) == 1

    def test_different_accounts_separate(self):
        raw = [
            make_option_transaction(id="tx-1", account_number="ACCT1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", account_number="ACCT2", order_id="ORD-1"),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)

        assert len(grouped) == 2

    def test_different_underlyings_separate(self):
        raw = [
            make_option_transaction(
                id="tx-1",
                order_id="ORD-1",
                symbol="AAPL  250321C00170000",
                underlying_symbol="AAPL",
            ),
            make_option_transaction(
                id="tx-2",
                order_id="ORD-1",
                symbol="SPY  250321C00550000",
                underlying_symbol="SPY",
            ),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)

        assert len(grouped) == 2


# ---------------------------------------------------------------------------
# normalize_transactions
# ---------------------------------------------------------------------------

class TestNormalizeTransactions:
    """Tests for the normalize_transactions() function."""

    def test_aggregates_same_fills(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1", quantity=1),
            make_option_transaction(id="tx-2", order_id="ORD-1", quantity=2),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 1
        assert normalized[0].quantity == 3
        assert "tx-1" in normalized[0].id
        assert "tx-2" in normalized[0].id

    def test_different_prices_not_aggregated(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1", price=2.50),
            make_option_transaction(id="tx-2", order_id="ORD-1", price=3.00),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 2

    def test_different_actions_not_aggregated(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN"),
            make_option_transaction(id="tx-2", order_id="ORD-1", action="BUY_TO_CLOSE"),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 2

    def test_single_transaction_unchanged(self):
        raw = [make_option_transaction()]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 1
        assert normalized[0].id == "tx-001"

    def test_aggregation_sums_fees(self):
        raw = [
            make_option_transaction(
                id="tx-1", order_id="ORD-1", quantity=1,
                commission=1.0, regulatory_fees=0.05, clearing_fees=0.10,
            ),
            make_option_transaction(
                id="tx-2", order_id="ORD-1", quantity=1,
                commission=1.0, regulatory_fees=0.05, clearing_fees=0.10,
            ),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 1
        assert normalized[0].commission == 2.0
        assert normalized[0].regulatory_fees == pytest.approx(0.10)
        assert normalized[0].clearing_fees == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# classify_order
# ---------------------------------------------------------------------------

class TestClassifyOrder:
    """Tests for the classify_order() function."""

    def test_opening(self):
        raw = [make_option_transaction(action="SELL_TO_OPEN")]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.OPENING

    def test_closing(self):
        raw = [make_option_transaction(action="BUY_TO_CLOSE")]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING

    def test_rolling(self):
        raw = [
            make_option_transaction(id="tx-1", action="BUY_TO_CLOSE"),
            make_option_transaction(
                id="tx-2",
                action="SELL_TO_OPEN",
                symbol="AAPL  250418C00175000",
                strike=175.0,
                expiration="2025-04-18",
            ),
        ]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.ROLLING

    def test_expiration_is_closing(self):
        raw = [make_expiration_transaction()]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING

    def test_assignment_is_closing(self):
        raw = [make_assignment_transaction()]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING


# ---------------------------------------------------------------------------
# create_orders
# ---------------------------------------------------------------------------

class TestCreateOrders:
    """Tests for the create_orders() function."""

    def test_creates_single_order(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", order_id="ORD-1"),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)
        orders = create_orders(grouped)

        assert len(orders) == 1
        assert orders[0].order_id == "ORD-1"
        assert orders[0].underlying == "AAPL"
        assert orders[0].order_type == OrderType.OPENING

    def test_creates_multiple_orders(self):
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", order_id="ORD-2", action="BUY_TO_CLOSE"),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)
        orders = create_orders(grouped)

        assert len(orders) == 2
        types = {o.order_type for o in orders}
        assert OrderType.OPENING in types
        assert OrderType.CLOSING in types


# ---------------------------------------------------------------------------
# assemble_orders (end-to-end)
# ---------------------------------------------------------------------------

class TestAssembleOrders:
    """Tests for the top-level assemble_orders() function."""

    def test_end_to_end_basic(self):
        raw = [
            make_option_transaction(
                id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-2", order_id="ORD-2", action="BUY_TO_CLOSE",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]
        result = assemble_orders(raw)

        assert isinstance(result, AssemblyResult)
        assert len(result.orders) == 2
        assert len(result.assignment_stock_transactions) == 0
        # Orders should be sorted chronologically
        assert result.orders[0].executed_at <= result.orders[1].executed_at

    def test_end_to_end_with_assignment_stock(self):
        raw = [
            make_assignment_transaction(id="tx-assign"),
            make_stock_transaction(
                id="tx-stock",
                order_id=None,
                action="BUY_TO_OPEN",
                instrument_type="EQUITY",
            ),
        ]
        result = assemble_orders(raw)

        assert len(result.orders) == 1  # The assignment option
        assert len(result.assignment_stock_transactions) == 1  # The stock

    def test_returns_assembly_result(self):
        result = assemble_orders([])
        assert isinstance(result, AssemblyResult)
        assert result.orders == []
        assert result.assignment_stock_transactions == []
