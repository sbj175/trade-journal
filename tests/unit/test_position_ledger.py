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
    make_exercise_transaction,
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


# ---------------------------------------------------------------------------
# Assignment-derived stock lots closed by subsequent orders
# ---------------------------------------------------------------------------

class TestAssignmentDerivedStockClosing:
    """Validates that stock closing transactions can close assignment-derived
    stock lots, even though the derived lots are created after the first pass
    of lot processing.

    Scenario (modeled after OKLO Roth account):
      1. STO 1 call option
      2. Assignment: BTC option (Receive Deliver) + STO 100 shares
      3. Later trade: BTC 100 shares (closes the assigned short stock)
    """

    def test_subsequent_order_closes_assignment_derived_shares(
        self, db, order_processor, lot_manager, position_manager,
    ):
        """BTC stock in a later order should close assignment-derived short shares."""
        txs = [
            # 1) Open short call
            make_option_transaction(
                id="tx-sto", order_id="ORD-STO", action="SELL_TO_OPEN",
                quantity=1, price=5.00,
                symbol="OKLO  251128C00086000",
                underlying_symbol="OKLO",
                option_type="Call", strike=86.0, expiration="2025-11-28",
                executed_at="2025-11-21T18:00:00+00:00",
            ),
            # 2) Assignment: option side (Receive Deliver — no order_id)
            make_assignment_transaction(
                id="tx-assign-opt",
                symbol="OKLO  251128C00086000",
                underlying_symbol="OKLO",
                quantity=1,
                executed_at="2025-11-28T22:00:00+00:00",
            ),
            # 3) Later trade order: BTC 100 shares to close the assigned short
            make_stock_transaction(
                id="tx-btc-shares", order_id="ORD-CLOSE-SHARES",
                symbol="OKLO", underlying_symbol="OKLO",
                action="BUY_TO_CLOSE", quantity=100, price=90.19,
                executed_at="2025-12-01T14:56:50+00:00",
                transaction_sub_type="Buy to Close",
            ),
        ]

        # Assignment stock side (STO shares — sidelined during preprocessing)
        assignment_stock = make_stock_transaction(
            id="tx-assign-stock", order_id=None,
            symbol="OKLO", underlying_symbol="OKLO",
            action="SELL_TO_OPEN", quantity=100, price=86.00,
            executed_at="2025-11-28T22:00:00+00:00",
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Open",
        )

        from src.pipeline.order_assembler import assemble_orders
        from src.pipeline.position_ledger import process_lots

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()

        assembly = assemble_orders(txs)
        process_lots(
            assembly.orders,
            [assignment_stock],
            lot_manager,
            position_manager,
            db,
        )

        # The assignment-derived short stock lot should be CLOSED
        open_stock_lots = lot_manager.get_open_lots("ACCT1", symbol="OKLO")
        assert len(open_stock_lots) == 0, (
            f"Expected 0 open stock lots, got {len(open_stock_lots)}: "
            f"{[(l.symbol, l.remaining_quantity) for l in open_stock_lots]}"
        )

    def test_multi_fill_closes_assignment_derived_shares(
        self, db, order_processor, lot_manager, position_manager,
    ):
        """Multiple stock BTC fills in one order close assignment-derived shares."""
        txs = [
            # 1) Open short call (16 contracts)
            make_option_transaction(
                id="tx-sto", order_id="ORD-STO", action="SELL_TO_OPEN",
                quantity=16, price=5.10,
                symbol="OKLO  251128C00086000",
                underlying_symbol="OKLO",
                option_type="Call", strike=86.0, expiration="2025-11-28",
                executed_at="2025-11-21T18:00:00+00:00",
            ),
            # 2) Assignment: option side (Receive Deliver)
            make_assignment_transaction(
                id="tx-assign-opt",
                symbol="OKLO  251128C00086000",
                underlying_symbol="OKLO",
                quantity=16,
                executed_at="2025-11-28T22:00:00+00:00",
            ),
            # 3) Later order: BTC 800 + BTC 800 shares (two fills in same order)
            make_stock_transaction(
                id="tx-btc-1", order_id="ORD-CLOSE-SHARES",
                symbol="OKLO", underlying_symbol="OKLO",
                action="BUY_TO_CLOSE", quantity=800, price=90.19,
                executed_at="2025-12-01T14:56:50+00:00",
                transaction_sub_type="Buy to Close",
            ),
            make_stock_transaction(
                id="tx-btc-2", order_id="ORD-CLOSE-SHARES",
                symbol="OKLO", underlying_symbol="OKLO",
                action="BUY_TO_CLOSE", quantity=800, price=90.19,
                executed_at="2025-12-01T14:56:50+00:00",
                transaction_sub_type="Buy to Close",
            ),
        ]

        # Assignment stock side (STO 1600 shares)
        assignment_stock = make_stock_transaction(
            id="tx-assign-stock", order_id=None,
            symbol="OKLO", underlying_symbol="OKLO",
            action="SELL_TO_OPEN", quantity=1600, price=86.00,
            executed_at="2025-11-28T22:00:00+00:00",
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Open",
        )

        from src.pipeline.order_assembler import assemble_orders
        from src.pipeline.position_ledger import process_lots

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()

        assembly = assemble_orders(txs)
        process_lots(
            assembly.orders,
            [assignment_stock],
            lot_manager,
            position_manager,
            db,
        )

        # All 1600 shares should be closed
        open_stock_lots = lot_manager.get_open_lots("ACCT1", symbol="OKLO")
        assert len(open_stock_lots) == 0, (
            f"Expected 0 open stock lots, got {len(open_stock_lots)}: "
            f"{[(l.symbol, l.remaining_quantity) for l in open_stock_lots]}"
        )


# ---------------------------------------------------------------------------
# Assignment / Exercise — full test matrix
# ---------------------------------------------------------------------------

# Helper that drives process_lots directly (avoids OrderProcessor
# side-effects and keeps the test focused on position_ledger logic).

def _run_process_lots(db, lot_manager, position_manager, txs, assignment_stocks):
    from src.pipeline.order_assembler import assemble_orders
    from src.pipeline.position_ledger import process_lots

    position_manager.clear_all_positions()
    lot_manager.clear_all_lots()

    assembly = assemble_orders(txs)
    process_lots(
        assembly.orders,
        assignment_stocks,
        lot_manager,
        position_manager,
        db,
    )


# Shared constants for HUT-style spread tests
_SETTLE_TIME = "2025-06-20T22:00:00+00:00"


class TestAssignmentExerciseMatrix:
    """Full matrix of assignment/exercise scenarios including TO_CLOSE handling."""

    # ------------------------------------------------------------------
    # 1. Short Put assignment → BTO shares (opens long stock)
    # ------------------------------------------------------------------
    def test_short_put_assignment_opens_long_shares(
        self, db, lot_manager, position_manager,
    ):
        txs = [
            make_option_transaction(
                id="tx-stp", order_id="ORD-STP", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="HUT   250620P00014000",
                underlying_symbol="HUT",
                option_type="Put", strike=14.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            make_assignment_transaction(
                id="tx-assign",
                symbol="HUT   250620P00014000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        assignment_stock = make_stock_transaction(
            id="tx-stock-assign", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="BUY_TO_OPEN", quantity=100, price=14.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Buy to Open",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [assignment_stock])

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 1
        assert lots[0].quantity == 100  # long
        assert lots[0].entry_price == 14.0

    # ------------------------------------------------------------------
    # 2. Short Call assignment → STO shares (opens short stock)
    # ------------------------------------------------------------------
    def test_short_call_assignment_opens_short_shares(
        self, db, lot_manager, position_manager,
    ):
        txs = [
            make_option_transaction(
                id="tx-stc", order_id="ORD-STC", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                option_type="Call", strike=14.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            make_assignment_transaction(
                id="tx-assign",
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        assignment_stock = make_stock_transaction(
            id="tx-stock-assign", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_OPEN", quantity=100, price=14.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Open",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [assignment_stock])

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 1
        assert lots[0].quantity == -100  # short
        assert lots[0].entry_price == 14.0

    # ------------------------------------------------------------------
    # 3. Short Call assignment closes existing long shares (STC)
    # ------------------------------------------------------------------
    def test_short_call_assignment_closes_existing_shares(
        self, db, lot_manager, position_manager,
    ):
        """Short call assigned while holding long shares → STC closes them."""
        txs = [
            # First: buy 100 shares
            make_stock_transaction(
                id="tx-bto-shares", order_id="ORD-BTO",
                symbol="HUT", underlying_symbol="HUT",
                action="BUY_TO_OPEN", quantity=100, price=12.00,
                executed_at="2025-05-01T10:00:00+00:00",
            ),
            # Then: sell short call
            make_option_transaction(
                id="tx-stc", order_id="ORD-STC", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                option_type="Call", strike=14.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Assignment closes the call
            make_assignment_transaction(
                id="tx-assign",
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        # Stock side: SELL_TO_CLOSE (closing existing long shares)
        assignment_stock = make_stock_transaction(
            id="tx-stock-assign", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_CLOSE", quantity=100, price=14.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Close",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [assignment_stock])

        # All stock lots should be closed — no phantom position
        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 0, (
            f"Expected 0 open HUT lots, got {len(lots)}: "
            f"{[(l.symbol, l.quantity, l.remaining_quantity) for l in lots]}"
        )

    # ------------------------------------------------------------------
    # 4. Long Call exercise → BTO shares (opens long stock)
    # ------------------------------------------------------------------
    def test_long_call_exercise_opens_long_shares(
        self, db, lot_manager, position_manager,
    ):
        txs = [
            make_option_transaction(
                id="tx-btc", order_id="ORD-BTC", action="BUY_TO_OPEN",
                quantity=1, price=1.00,
                symbol="HUT   250620C00015000",
                underlying_symbol="HUT",
                option_type="Call", strike=15.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            make_exercise_transaction(
                id="tx-exercise",
                symbol="HUT   250620C00015000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        exercise_stock = make_stock_transaction(
            id="tx-stock-exercise", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="BUY_TO_OPEN", quantity=100, price=15.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Buy to Open",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [exercise_stock])

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 1
        assert lots[0].quantity == 100  # long
        assert lots[0].entry_price == 15.0

    # ------------------------------------------------------------------
    # 5. Long Put exercise closes existing long shares (STC)
    # ------------------------------------------------------------------
    def test_long_put_exercise_closes_long_shares(
        self, db, lot_manager, position_manager,
    ):
        """Long put exercised while holding shares → STC closes them."""
        txs = [
            # Buy shares first
            make_stock_transaction(
                id="tx-bto-shares", order_id="ORD-BTO",
                symbol="HUT", underlying_symbol="HUT",
                action="BUY_TO_OPEN", quantity=100, price=16.00,
                executed_at="2025-05-01T10:00:00+00:00",
            ),
            # Buy protective put
            make_option_transaction(
                id="tx-btp", order_id="ORD-BTP", action="BUY_TO_OPEN",
                quantity=1, price=1.00,
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                option_type="Put", strike=15.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Exercise the put
            make_exercise_transaction(
                id="tx-exercise",
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        exercise_stock = make_stock_transaction(
            id="tx-stock-exercise", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_CLOSE", quantity=100, price=15.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Close",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [exercise_stock])

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 0

    # ------------------------------------------------------------------
    # 6. Long Put exercise opens short shares (STO — no existing shares)
    # ------------------------------------------------------------------
    def test_long_put_exercise_opens_short_shares(
        self, db, lot_manager, position_manager,
    ):
        """Long put exercised without existing shares → STO creates short stock."""
        txs = [
            make_option_transaction(
                id="tx-btp", order_id="ORD-BTP", action="BUY_TO_OPEN",
                quantity=1, price=1.00,
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                option_type="Put", strike=15.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            make_exercise_transaction(
                id="tx-exercise",
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        exercise_stock = make_stock_transaction(
            id="tx-stock-exercise", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_OPEN", quantity=100, price=15.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Open",
        )

        _run_process_lots(db, lot_manager, position_manager, txs, [exercise_stock])

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 1
        assert lots[0].quantity == -100  # short
        assert lots[0].entry_price == 15.0

    # ------------------------------------------------------------------
    # 7. Call spread settlement: short $14 call assigned (STC) +
    #    long $15 call exercised (BTO) → net zero stock
    # ------------------------------------------------------------------
    def test_call_spread_settlement(
        self, db, lot_manager, position_manager,
    ):
        """HUT 14/15 call spread expires ITM.

        Short $14 call → assigned → STC 100 @ $14 (closes shares)
        Long  $15 call → exercised → BTO 100 @ $15 (opens shares)

        The exercise creates 100 long shares; the assignment closes them.
        Net result: 0 open stock lots.
        """
        txs = [
            # Open the short $14 call
            make_option_transaction(
                id="tx-sto-14", order_id="ORD-SPREAD", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                option_type="Call", strike=14.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Open the long $15 call
            make_option_transaction(
                id="tx-bto-15", order_id="ORD-SPREAD", action="BUY_TO_OPEN",
                quantity=1, price=1.50,
                symbol="HUT   250620C00015000",
                underlying_symbol="HUT",
                option_type="Call", strike=15.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Assignment on the short call
            make_assignment_transaction(
                id="tx-assign",
                symbol="HUT   250620C00014000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
            # Exercise the long call
            make_exercise_transaction(
                id="tx-exercise",
                symbol="HUT   250620C00015000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        # Stock sides — same underlying, same time, same quantity, different prices
        assign_stock = make_stock_transaction(
            id="tx-stock-assign", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_CLOSE", quantity=100, price=14.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Close",
        )
        exercise_stock = make_stock_transaction(
            id="tx-stock-exercise", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="BUY_TO_OPEN", quantity=100, price=15.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Buy to Open",
        )

        _run_process_lots(
            db, lot_manager, position_manager, txs,
            [assign_stock, exercise_stock],
        )

        # Net zero — no open stock lots
        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 0, (
            f"Expected 0 open HUT lots (call spread net zero), got {len(lots)}: "
            f"{[(l.symbol, l.quantity, l.remaining_quantity) for l in lots]}"
        )

    # ------------------------------------------------------------------
    # 8. Put spread settlement: short $15 put assigned (BTO) +
    #    long $14 put exercised (STC) → net zero stock
    # ------------------------------------------------------------------
    def test_put_spread_settlement(
        self, db, lot_manager, position_manager,
    ):
        """PUT spread: short $15 put / long $14 put expires ITM.

        Short $15 put → assigned → BTO 100 @ $15 (opens shares)
        Long  $14 put → exercised → STC 100 @ $14 (closes shares)

        Net result: 0 open stock lots.
        """
        txs = [
            # Open the short $15 put
            make_option_transaction(
                id="tx-sto-15", order_id="ORD-SPREAD", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                option_type="Put", strike=15.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Open the long $14 put
            make_option_transaction(
                id="tx-bto-14", order_id="ORD-SPREAD", action="BUY_TO_OPEN",
                quantity=1, price=1.00,
                symbol="HUT   250620P00014000",
                underlying_symbol="HUT",
                option_type="Put", strike=14.0, expiration="2025-06-20",
                executed_at="2025-06-01T10:00:00+00:00",
            ),
            # Assignment on the short put
            make_assignment_transaction(
                id="tx-assign",
                symbol="HUT   250620P00015000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
            # Exercise the long put
            make_exercise_transaction(
                id="tx-exercise",
                symbol="HUT   250620P00014000",
                underlying_symbol="HUT",
                quantity=1,
                executed_at=_SETTLE_TIME,
            ),
        ]

        assign_stock = make_stock_transaction(
            id="tx-stock-assign", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="BUY_TO_OPEN", quantity=100, price=15.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Buy to Open",
        )
        exercise_stock = make_stock_transaction(
            id="tx-stock-exercise", order_id=None,
            symbol="HUT", underlying_symbol="HUT",
            action="SELL_TO_CLOSE", quantity=100, price=14.00,
            executed_at=_SETTLE_TIME,
            transaction_type="Receive Deliver",
            transaction_sub_type="Sell to Close",
        )

        _run_process_lots(
            db, lot_manager, position_manager, txs,
            [assign_stock, exercise_stock],
        )

        lots = lot_manager.get_open_lots("ACCT1", symbol="HUT")
        assert len(lots) == 0, (
            f"Expected 0 open HUT lots (put spread net zero), got {len(lots)}: "
            f"{[(l.symbol, l.quantity, l.remaining_quantity) for l in lots]}"
        )
