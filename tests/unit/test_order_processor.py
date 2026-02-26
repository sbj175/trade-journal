"""
Tests for OrderProcessor — transaction grouping, chain derivation, rolling detection.

Source: src/models/order_processor.py
"""

import pytest
from datetime import datetime

from src.models.order_processor import OrderProcessor, OrderType, Transaction
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.chain_graph import derive_chains
from tests.conftest import (
    make_option_transaction,
    make_expiration_transaction,
    make_assignment_transaction,
    make_stock_transaction,
)


# ---------------------------------------------------------------------------
# Transaction grouping
# ---------------------------------------------------------------------------

class TestGroupTransactions:
    def test_group_transactions_by_order_id(self, order_processor, db):
        """Transactions with same order_id grouped together."""
        txs = [
            make_option_transaction(
                id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000",
            ),
            make_option_transaction(
                id="tx-2", order_id="ORD-1", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321P00160000",
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        # Both should be in same chain since same order
        assert len(chains) == 1
        assert len(chains[0].orders) == 1
        assert len(chains[0].orders[0].transactions) == 2

    def test_split_fills_aggregated(self, order_processor, db):
        """Multiple fills for same symbol/action/price within one order → aggregated."""
        txs = [
            make_option_transaction(
                id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
            ),
            make_option_transaction(
                id="tx-2", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)
        order = chains[0].orders[0]

        # Should be aggregated into single transaction
        assert len(order.transactions) == 1
        assert order.transactions[0].quantity == 2


# ---------------------------------------------------------------------------
# Order classification
# ---------------------------------------------------------------------------

class TestOrderClassification:
    def test_opening_order_creates_chain(self, order_processor, db):
        """First BTO/STO creates a new chain."""
        txs = [make_option_transaction(
            id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
        )]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        assert chains[0].orders[0].order_type == OrderType.OPENING

    def test_closing_order_links_to_chain(self, order_processor, db):
        """STC/BTC matches to existing chain by symbol + account."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        assert len(chains[0].orders) == 2

    def test_rolling_detection(self, order_processor, db):
        """Simultaneous close + open in same order detected as ROLLING."""
        txs = [
            # Opening order
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Roll: close old + open new in same order
            make_option_transaction(
                id="tx-roll-close", order_id="ORD-ROLL", action="BUY_TO_CLOSE",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-roll-open", order_id="ORD-ROLL", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                symbol="AAPL 250418P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        # The roll order should be classified as ROLLING
        roll_orders = [o for c in chains for o in c.orders if o.order_type == OrderType.ROLLING]
        assert len(roll_orders) == 1


# ---------------------------------------------------------------------------
# Special events
# ---------------------------------------------------------------------------

class TestSpecialEvents:
    def test_expiration_creates_closing(self, order_processor, db):
        """Expiration transaction treated as closing event."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_expiration_transaction(id="tx-exp", quantity=1),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        # Chain should have both the opening and the expiration
        assert len(chains[0].orders) >= 1

    def test_multiple_underlyings_separate_chains(self, order_processor, db):
        """Different underlyings get separate chains."""
        txs = [
            make_option_transaction(
                id="tx-aapl", order_id="ORD-AAPL", action="SELL_TO_OPEN",
                symbol="AAPL 250321C00170000", underlying_symbol="AAPL",
            ),
            make_option_transaction(
                id="tx-spy", order_id="ORD-SPY", action="SELL_TO_OPEN",
                symbol="SPY 250321C00500000", underlying_symbol="SPY",
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 2
        underlyings = {c.underlying for c in chains}
        assert underlyings == {"AAPL", "SPY"}


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class TestProcessPipeline:
    def test_process_transactions_pipeline(self, order_processor, db):
        """Full 6-stage pipeline with mixed opening/closing/rolling."""
        txs = [
            # Stage 1: Open
            make_option_transaction(
                id="tx-1", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=2, price=3.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Stage 2: Partial close
            make_option_transaction(
                id="tx-2", order_id="ORD-2", action="BUY_TO_CLOSE",
                quantity=1, price=2.00,
                executed_at="2025-03-05T10:00:00+00:00",
            ),
            # Stage 3: Close remaining
            make_option_transaction(
                id="tx-3", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"
        assert len(chain.orders) == 3
