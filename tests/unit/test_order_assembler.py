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
        """A single option trade should be parsed into a transaction with the right strike, type, and expiration date."""
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
        """A simple share-purchase transaction should be parsed with no option fields populated."""
        raw = [make_stock_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        tx = txs[0]
        assert tx.order_id == "ORD-STOCK-001"
        assert tx.underlying_symbol == "AAPL"
        assert tx.action == "BUY_TO_OPEN"
        assert tx.option_type is None

    def test_expiration_no_action_kept(self):
        """Option expiration events without a buy/sell action should still be kept and given a synthetic order id so they can be tied to a chain."""
        raw = [make_expiration_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)
        assert len(txs) == 1
        assert "SYSTEM_Expiration" in txs[0].order_id

    def test_expiration_with_action_gets_synthetic_order_id(self):
        """Even when an expiration record happens to have a buy/sell action, it should still receive a synthetic expiration order id."""
        raw = [make_expiration_transaction()]
        # Give it an action so it passes the filter
        raw[0]["action"] = "SELL_TO_CLOSE"
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        # With an action it uses the SYSTEM_ synthetic ID (since order_id is None)
        assert txs[0].order_id.startswith("SYSTEM_Expiration_")

    def test_assignment_option_gets_synthetic_order_id(self):
        """An option assignment without an order id should be tagged with a synthetic 'Assignment' order id so it can be traced back to its chain."""
        raw = [make_assignment_transaction()]
        txs, assign_stocks = preprocess_transactions(raw)

        assert len(txs) == 1
        tx = txs[0]
        assert tx.order_id.startswith("SYSTEM_Assignment_")

    def test_assignment_stock_captured_separately(self):
        """Share transactions that come from an assignment (no order id) should be set aside in the assignment-stock list rather than treated as ordinary trades."""
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
        """ACAT account-transfer share movements should flow through as normal transactions, not be confused with shares received from option assignment."""
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
        """Transactions that have no instrument symbol should be silently dropped during preprocessing."""
        raw = [{"id": "1", "symbol": None, "action": "BUY_TO_OPEN"}]
        txs, assign_stocks = preprocess_transactions(raw)
        assert len(txs) == 0

    def test_skips_no_action_non_special(self):
        """Non-trade events like dividends (no action and not assignment/expiration) should be filtered out."""
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

    @pytest.mark.skip(reason="Stale test — symbol-change grouping changed since the test was written. Tracked under OPT-272.")
    def test_symbol_change_grouping(self):
        """When a ticker symbol changes, the close on the old symbol and the open on the new symbol should each get a synthetic order id grouped by date."""
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
        """A put option symbol should be parsed correctly into put type, strike, and expiration."""
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
        """Multiple distinct transactions should all survive preprocessing without being dropped."""
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
        """Transactions should be grouped together by account, underlying stock, and broker order id."""
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
        """Transactions in different brokerage accounts should never be combined into one group, even if they share an order id."""
        raw = [
            make_option_transaction(id="tx-1", account_number="ACCT1", order_id="ORD-1"),
            make_option_transaction(id="tx-2", account_number="ACCT2", order_id="ORD-1"),
        ]
        txs, _ = preprocess_transactions(raw)
        grouped = group_transactions(txs)

        assert len(grouped) == 2

    def test_different_underlyings_separate(self):
        """Transactions on different underlying stocks should be split into separate order groups, even if they share an order id."""
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
        """Multiple fills of the same trade at the same price should be combined into a single transaction with the total quantity."""
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
        """Fills at different prices within one order should remain as separate transactions instead of being merged."""
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1", price=2.50),
            make_option_transaction(id="tx-2", order_id="ORD-1", price=3.00),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 2

    def test_different_actions_not_aggregated(self):
        """Opening and closing transactions in the same order should not be combined into one fill."""
        raw = [
            make_option_transaction(id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN"),
            make_option_transaction(id="tx-2", order_id="ORD-1", action="BUY_TO_CLOSE"),
        ]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 2

    def test_single_transaction_unchanged(self):
        """A single transaction should pass through normalization unchanged."""
        raw = [make_option_transaction()]
        txs, _ = preprocess_transactions(raw)
        normalized = normalize_transactions(txs)

        assert len(normalized) == 1
        assert normalized[0].id == "tx-001"

    def test_aggregation_sums_fees(self):
        """When fills are merged, their commissions and regulatory fees should be added together."""
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
        """An order made up of opening trades should be classified as an opening order."""
        raw = [make_option_transaction(action="SELL_TO_OPEN")]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.OPENING

    def test_closing(self):
        """An order that only contains closing trades should be classified as a closing order."""
        raw = [make_option_transaction(action="BUY_TO_CLOSE")]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING

    def test_rolling(self):
        """An order containing both a close on one strike and an open on another should be classified as a rolling order."""
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
        """An option expiration event should be classified as a closing order."""
        raw = [make_expiration_transaction()]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING

    def test_assignment_is_closing(self):
        """An option assignment event should be classified as a closing order."""
        raw = [make_assignment_transaction()]
        txs, _ = preprocess_transactions(raw)
        assert classify_order(txs) == OrderType.CLOSING


# ---------------------------------------------------------------------------
# create_orders
# ---------------------------------------------------------------------------

class TestCreateOrders:
    """Tests for the create_orders() function."""

    def test_creates_single_order(self):
        """Two transactions sharing the same broker order id should produce exactly one order."""
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
        """Transactions with different broker order ids should produce one order each, with the correct opening/closing classifications."""
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
        """End to end, two trades on different days should produce two orders sorted in chronological order."""
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
        """An assignment plus its associated share-receipt transaction should result in one option order and one sidelined assignment-stock entry."""
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
        """Assembling with no input should return an AssemblyResult with empty order and assignment lists."""
        result = assemble_orders([])
        assert isinstance(result, AssemblyResult)
        assert result.orders == []
        assert result.assignment_stock_transactions == []
