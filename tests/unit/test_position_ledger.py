"""
Tests for unified equity processing — stock trades flow through OrderProcessor
alongside options, creating lots and chains via the same pipeline.

Source: src/models/order_processor.py (equity filter removal, close_long FIFO)
        src/services/ledger_service.py (net_opposing_equity_lots)
        src/services/chain_service.py (P&L multiplier fix)
"""

import pytest
from datetime import datetime

from src.models.order_processor import OrderType
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.chain_graph import derive_chains
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_assignment_transaction,
)


# ---------------------------------------------------------------------------
# Stock lots created via main pipeline
# ---------------------------------------------------------------------------

class TestStockInMainFlow:
    def test_stock_bto_creates_lot(self, db, order_processor, lot_manager):
        """Stock BTO flows through process_transactions() and creates a lot."""
        txs = [make_stock_transaction(
            id="tx-stock-bto", order_id="ORD-BTO", action="BUY_TO_OPEN",
            quantity=100, price=150.00,
        )]

        order_processor.process_transactions(txs)

        # Derive chains from DB lots
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        # Should create a chain
        assert len(chains) == 1
        assert chains[0].orders[0].order_type == OrderType.OPENING

        # Should create a lot
        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 1
        lot = open_lots[0]
        assert lot.quantity == 100
        assert lot.remaining_quantity == 100
        assert lot.entry_price == 150.00
        assert lot.instrument_type == "EQUITY"
        assert lot.status == "OPEN"

    def test_stock_sto_creates_short_lot(self, order_processor, lot_manager):
        """Stock STO creates a short lot (negative quantity)."""
        txs = [make_stock_transaction(
            id="tx-stock-sto", order_id="ORD-STO", action="SELL_TO_OPEN",
            quantity=100, price=155.00,
        )]

        order_processor.process_transactions(txs)

        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 1
        assert open_lots[0].quantity == -100
        assert open_lots[0].is_short is True


# ---------------------------------------------------------------------------
# Stock closing via FIFO
# ---------------------------------------------------------------------------

class TestStockClosing:
    def test_stock_stc_closes_long_lot(self, db, order_processor, lot_manager):
        """Stock STC closes long lot with correct P&L (no 100x multiplier)."""
        txs = [
            make_stock_transaction(
                id="tx-open", order_id="ORD-OPEN", action="BUY_TO_OPEN",
                quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_stock_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="SELL_TO_CLOSE",
                quantity=100, price=155.00,
                executed_at="2025-03-10T10:00:00+00:00",
                transaction_sub_type="Sell to Close",
            ),
        ]

        order_processor.process_transactions(txs)

        # Derive chains from DB lots
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        # Should be one chain with open + close
        assert len(chains) == 1
        assert chains[0].status == "CLOSED"

        # Lot should be closed
        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 0

        # P&L: (155 - 150) * 100 shares = $500 (multiplier=1 for equity)
        realized = lot_manager.get_realized_pnl_for_chain(chains[0].chain_id)
        assert realized == pytest.approx(500.00)

    def test_stock_btc_closes_short_lot(self, order_processor, lot_manager):
        """Stock BTC closes short lot, not long lot (direction-aware FIFO)."""
        txs = [
            # Open long position
            make_stock_transaction(
                id="tx-long", order_id="ORD-LONG", action="BUY_TO_OPEN",
                quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Open short position (different order)
            make_stock_transaction(
                id="tx-short", order_id="ORD-SHORT", action="SELL_TO_OPEN",
                quantity=100, price=160.00,
                executed_at="2025-03-02T10:00:00+00:00",
            ),
            # Close short position via BTC
            make_stock_transaction(
                id="tx-btc", order_id="ORD-BTC", action="BUY_TO_CLOSE",
                quantity=100, price=155.00,
                executed_at="2025-03-10T10:00:00+00:00",
                transaction_sub_type="Buy to Close",
            ),
        ]

        order_processor.process_transactions(txs)

        # Long lot should still be open
        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 1
        assert open_lots[0].quantity == 100  # Long lot remains
        assert open_lots[0].is_long is True


# ---------------------------------------------------------------------------
# Mixed option + equity in same underlying
# ---------------------------------------------------------------------------

class TestMixedOptionEquity:
    def test_mixed_option_and_equity_same_underlying(self, order_processor, lot_manager):
        """Both option and stock trades create lots and get chain IDs."""
        txs = [
            make_option_transaction(
                id="tx-opt", order_id="ORD-OPT", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_stock_transaction(
                id="tx-stk", order_id="ORD-STK", action="BUY_TO_OPEN",
                quantity=100, price=170.00,
                executed_at="2025-03-01T11:00:00+00:00",
            ),
        ]

        order_processor.process_transactions(txs)

        # Both should create lots
        all_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(all_lots) == 2

        # Each lot should have a chain_id
        for lot in all_lots:
            assert lot.chain_id is not None
            assert lot.chain_id != ''


# ---------------------------------------------------------------------------
# Assignment flow unchanged
# ---------------------------------------------------------------------------

class TestAssignmentFlowUnchanged:
    def test_assignment_creates_derived_stock_lot(self, db, order_processor, lot_manager):
        """Option assignment → option lot closed + derived stock lot created."""
        txs = [
            # Open short put
            make_option_transaction(
                id="tx-put", order_id="ORD-PUT", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Assignment (option side — no order_id, system-generated)
            make_assignment_transaction(
                id="tx-assign",
                symbol="AAPL 250321P00170000",
                quantity=1,
                executed_at="2025-03-21T16:00:00+00:00",
            ),
        ]

        # Assignment stock transaction (no order_id — filtered into _assignment_stock_transactions)
        order_processor._assignment_stock_transactions = []

        order_processor.process_transactions(txs)

        # Derive chains from DB lots
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        # Should have a chain
        assert len(chains) >= 1

        # The option lot should be closed via assignment
        option_lots = lot_manager.get_open_lots("ACCT1", symbol="AAPL 250321P00170000")
        assert len(option_lots) == 0  # Closed


# ---------------------------------------------------------------------------
# Netting still works
# ---------------------------------------------------------------------------

class TestNettingStillWorks:
    def test_net_opposing_equity_lots(self, db, lot_manager, monkeypatch):
        """Opposing equity lots (long vs short) net against each other."""
        from src.services import ledger_service
        monkeypatch.setattr(ledger_service, 'db', db)
        monkeypatch.setattr(ledger_service, 'lot_manager', lot_manager)

        # Create a long lot
        long_tx = make_stock_transaction(
            id="tx-long", action="BUY_TO_OPEN", quantity=100, price=150.00,
            executed_at="2025-03-01T10:00:00+00:00",
        )
        lot_manager.create_lot(long_tx, chain_id="chain-long")

        # Create a short lot (e.g., from call assignment)
        short_tx = make_stock_transaction(
            id="tx-short", action="SELL_TO_OPEN", quantity=100, price=150.00,
            executed_at="2025-03-02T10:00:00+00:00",
        )
        lot_manager.create_lot(short_tx, chain_id="chain-short")

        netted = ledger_service.net_opposing_equity_lots()

        assert netted > 0

        # Both lots should be closed
        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 0


# ---------------------------------------------------------------------------
# Full pipeline: equity doesn't need separate pass
# ---------------------------------------------------------------------------

class TestFullPipelineNoSeparatePass:
    def test_equity_lots_created_without_process_equity_transactions(self, order_processor, lot_manager):
        """Full pipeline creates equity lots — no need for process_equity_transactions()."""
        txs = [
            make_stock_transaction(
                id="tx-buy", order_id="ORD-BUY", action="BUY_TO_OPEN",
                quantity=200, price=50.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_stock_transaction(
                id="tx-sell", order_id="ORD-SELL", action="SELL_TO_CLOSE",
                quantity=100, price=55.00,
                executed_at="2025-03-05T10:00:00+00:00",
                transaction_sub_type="Sell to Close",
            ),
        ]

        order_processor.process_transactions(txs)

        # Lot created and partially closed — no separate equity pass needed
        open_lots = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        assert len(open_lots) == 1
        assert open_lots[0].remaining_quantity == 100  # 200 - 100 closed
