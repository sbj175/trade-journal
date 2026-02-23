"""
Tests for LotManager — FIFO lot creation, closing, derived lots.

Source: src/models/lot_manager.py
"""

import pytest
from datetime import datetime

from tests.conftest import make_option_transaction, make_stock_transaction


# ---------------------------------------------------------------------------
# Lot creation
# ---------------------------------------------------------------------------

class TestCreateLot:
    def test_create_lot_long(self, lot_manager):
        """BTO 5 contracts → quantity=5, remaining=5, status=OPEN"""
        tx = make_option_transaction(
            action="BUY_TO_OPEN", quantity=5, price=2.50,
        )
        lot_id = lot_manager.create_lot(tx, chain_id="chain-1")
        lot = lot_manager.get_lot_by_id(lot_id)

        assert lot.quantity == 5
        assert lot.remaining_quantity == 5
        assert lot.original_quantity == 5
        assert lot.status == "OPEN"
        assert lot.is_long is True

    def test_create_lot_short(self, lot_manager):
        """STO 3 contracts → quantity=-3, remaining=-3"""
        tx = make_option_transaction(
            action="SELL_TO_OPEN", quantity=3, price=1.50,
        )
        lot_id = lot_manager.create_lot(tx, chain_id="chain-1")
        lot = lot_manager.get_lot_by_id(lot_id)

        assert lot.quantity == -3
        assert lot.remaining_quantity == -3
        assert lot.original_quantity == 3
        assert lot.is_short is True

    def test_create_lot_parses_option_details(self, lot_manager):
        """Symbol 'AAPL 250321C00170000' → Call, strike=170.0, exp=2025-03-21"""
        tx = make_option_transaction(
            symbol="AAPL 250321C00170000",
            instrument_type="EQUITY_OPTION",
        )
        lot_id = lot_manager.create_lot(tx, chain_id="chain-1")
        lot = lot_manager.get_lot_by_id(lot_id)

        assert lot.option_type == "Call"
        assert lot.strike == 170.0
        assert lot.expiration is not None
        assert lot.expiration.year == 2025
        assert lot.expiration.month == 3
        assert lot.expiration.day == 21
        assert lot.is_option is True


# ---------------------------------------------------------------------------
# FIFO closing
# ---------------------------------------------------------------------------

class TestCloseLotFifo:
    def test_close_lot_fifo_full(self, lot_manager):
        """Open 5, close 5 → remaining=0, status=CLOSED"""
        tx = make_option_transaction(
            id="tx-open", action="BUY_TO_OPEN", quantity=5, price=2.00,
        )
        lot_id = lot_manager.create_lot(tx, chain_id="chain-1")

        total_pnl, affected = lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL  250321C00170000",
            quantity_to_close=5,
            closing_price=3.00,
            closing_order_id="close-1",
            closing_transaction_id="tx-close",
            closing_date=datetime(2025, 3, 15),
        )

        lot = lot_manager.get_lot_by_id(lot_id)
        assert lot.remaining_quantity == 0
        assert lot.status == "CLOSED"
        assert lot_id in affected

    def test_close_lot_fifo_partial(self, lot_manager):
        """Open 5, close 2 → remaining=3, status=PARTIAL"""
        tx = make_option_transaction(
            id="tx-open", action="BUY_TO_OPEN", quantity=5, price=2.00,
        )
        lot_id = lot_manager.create_lot(tx, chain_id="chain-1")

        lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL  250321C00170000",
            quantity_to_close=2,
            closing_price=3.00,
            closing_order_id="close-1",
            closing_transaction_id="tx-close",
            closing_date=datetime(2025, 3, 15),
        )

        lot = lot_manager.get_lot_by_id(lot_id)
        assert lot.remaining_quantity == 3
        assert lot.status == "PARTIAL"

    def test_close_lot_fifo_multiple_lots(self, lot_manager):
        """Open 3 + Open 2, close 4 → FIFO: first lot fully closed, second partially."""
        tx1 = make_option_transaction(
            id="tx-1", action="BUY_TO_OPEN", quantity=3, price=2.00,
            executed_at="2025-03-01T10:00:00+00:00",
        )
        tx2 = make_option_transaction(
            id="tx-2", action="BUY_TO_OPEN", quantity=2, price=2.50,
            executed_at="2025-03-02T10:00:00+00:00",
        )
        lot1 = lot_manager.create_lot(tx1, chain_id="chain-1")
        lot2 = lot_manager.create_lot(tx2, chain_id="chain-1")

        total_pnl, affected = lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL  250321C00170000",
            quantity_to_close=4,
            closing_price=3.00,
            closing_order_id="close-1",
            closing_transaction_id="tx-close",
            closing_date=datetime(2025, 3, 15),
        )

        first = lot_manager.get_lot_by_id(lot1)
        second = lot_manager.get_lot_by_id(lot2)

        assert first.remaining_quantity == 0
        assert first.status == "CLOSED"
        assert second.remaining_quantity == 1
        assert second.status == "PARTIAL"
        assert lot1 in affected
        assert lot2 in affected


# ---------------------------------------------------------------------------
# P&L correctness
# ---------------------------------------------------------------------------

class TestCloseLotPnl:
    def test_close_lot_pnl_long(self, lot_manager):
        """BTO at $2.50, STC at $3.00, qty=1 → P&L = $50.00"""
        tx = make_option_transaction(
            id="tx-open", action="BUY_TO_OPEN", quantity=1, price=2.50,
        )
        lot_manager.create_lot(tx, chain_id="chain-1")

        total_pnl, _ = lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL  250321C00170000",
            quantity_to_close=1,
            closing_price=3.00,
            closing_order_id="close-1",
            closing_transaction_id="tx-close",
            closing_date=datetime(2025, 3, 15),
        )

        assert total_pnl == pytest.approx(50.00)

    def test_close_lot_pnl_short(self, lot_manager):
        """STO at $1.50, BTC at $1.00, qty=1 → P&L = $50.00"""
        tx = make_option_transaction(
            id="tx-open", action="SELL_TO_OPEN", quantity=1, price=1.50,
        )
        lot_manager.create_lot(tx, chain_id="chain-1")

        total_pnl, _ = lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL  250321C00170000",
            quantity_to_close=1,
            closing_price=1.00,
            closing_order_id="close-1",
            closing_transaction_id="tx-close",
            closing_date=datetime(2025, 3, 15),
        )

        assert total_pnl == pytest.approx(50.00)

    def test_close_lot_pnl_stock(self, lot_manager):
        """Buy 100 shares at $50, sell at $55 → P&L = $500.00 (multiplier=1)."""
        tx = make_stock_transaction(
            id="tx-stock", action="BUY_TO_OPEN", quantity=100, price=50.00,
            symbol="AAPL", instrument_type="EQUITY",
        )
        lot_manager.create_lot(tx, chain_id="chain-stock")

        total_pnl, _ = lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL",
            quantity_to_close=100,
            closing_price=55.00,
            closing_order_id="close-stock",
            closing_transaction_id="tx-close-stock",
            closing_date=datetime(2025, 3, 15),
        )

        assert total_pnl == pytest.approx(500.00)


# ---------------------------------------------------------------------------
# Derived lots (assignment)
# ---------------------------------------------------------------------------

class TestDerivedLot:
    def test_create_derived_lot_put_assignment(self, lot_manager):
        """Short put at $50 strike → assignment → stock lot: qty=+100, entry=50.0"""
        # Create and close the source option lot
        tx = make_option_transaction(
            id="tx-put", action="SELL_TO_OPEN", quantity=1, price=1.50,
            symbol="AAPL 250321P00050000",
            instrument_type="EQUITY_OPTION",
        )
        source_lot_id = lot_manager.create_lot(tx, chain_id="chain-assign")

        # Close it via assignment
        lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL 250321P00050000",
            quantity_to_close=1,
            closing_price=0.0,
            closing_order_id="assign-1",
            closing_transaction_id="tx-assign",
            closing_date=datetime(2025, 3, 21),
            closing_type="ASSIGNMENT",
        )

        # Create derived stock lot
        stock_tx = make_stock_transaction(
            id="tx-stock-derived", symbol="AAPL", quantity=100, price=50.00,
        )
        derived_id = lot_manager.create_derived_lot(
            source_lot_id=source_lot_id,
            stock_transaction=stock_tx,
            derivation_type="ASSIGNMENT",
            chain_id="chain-assign",
        )

        derived = lot_manager.get_lot_by_id(derived_id)
        assert derived.quantity == 100  # Positive = bought shares (put assignment)
        assert derived.entry_price == 50.0
        assert derived.derivation_type == "ASSIGNMENT"
        assert derived.derived_from_lot_id == source_lot_id

    def test_create_derived_lot_call_assignment(self, lot_manager):
        """Short call at $60 strike → assignment → stock lot: qty=-100 (sells shares)."""
        tx = make_option_transaction(
            id="tx-call", action="SELL_TO_OPEN", quantity=1, price=2.00,
            symbol="AAPL 250321C00060000",
            instrument_type="EQUITY_OPTION",
        )
        source_lot_id = lot_manager.create_lot(tx, chain_id="chain-assign-call")

        lot_manager.close_lot_fifo(
            account_number="ACCT1",
            symbol="AAPL 250321C00060000",
            quantity_to_close=1,
            closing_price=0.0,
            closing_order_id="assign-call",
            closing_transaction_id="tx-assign-call",
            closing_date=datetime(2025, 3, 21),
            closing_type="ASSIGNMENT",
        )

        stock_tx = make_stock_transaction(
            id="tx-stock-call", symbol="AAPL", quantity=100, price=60.00,
        )
        derived_id = lot_manager.create_derived_lot(
            source_lot_id=source_lot_id,
            stock_transaction=stock_tx,
            derivation_type="ASSIGNMENT",
            chain_id="chain-assign-call",
        )

        derived = lot_manager.get_lot_by_id(derived_id)
        assert derived.quantity == -100  # Negative = sold/delivered shares


# ---------------------------------------------------------------------------
# Filtering and queries
# ---------------------------------------------------------------------------

class TestLotQueries:
    def test_get_open_lots_filters(self, lot_manager):
        """Open lots filtered by chain_id and underlying."""
        tx1 = make_option_transaction(id="tx-a1", action="BUY_TO_OPEN", quantity=1)
        tx2 = make_option_transaction(
            id="tx-a2", action="BUY_TO_OPEN", quantity=1,
            symbol="SPY 250321C00500000", underlying_symbol="SPY",
        )
        lot_manager.create_lot(tx1, chain_id="chain-aapl")
        lot_manager.create_lot(tx2, chain_id="chain-spy")

        aapl_lots = lot_manager.get_open_lots("ACCT1", chain_id="chain-aapl")
        assert len(aapl_lots) == 1
        assert aapl_lots[0].underlying == "AAPL"

        spy_lots = lot_manager.get_open_lots("ACCT1", underlying="SPY")
        assert len(spy_lots) == 1

    def test_get_realized_pnl_for_chain(self, lot_manager):
        """Realized P&L summed across multiple closings in a chain."""
        tx1 = make_option_transaction(
            id="tx-1", action="SELL_TO_OPEN", quantity=2, price=3.00,
            executed_at="2025-03-01T10:00:00+00:00",
        )
        tx2 = make_option_transaction(
            id="tx-2", action="SELL_TO_OPEN", quantity=1, price=2.00,
            executed_at="2025-03-02T10:00:00+00:00",
        )
        lot_manager.create_lot(tx1, chain_id="chain-pnl")
        lot_manager.create_lot(tx2, chain_id="chain-pnl")

        # Close 2 at $1.00 → P&L = (3.00 - 1.00) * 2 * 100 = $400
        lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=2, closing_price=1.00,
            closing_order_id="close-a", closing_transaction_id="tx-ca",
            closing_date=datetime(2025, 3, 10),
            chain_id="chain-pnl",
        )
        # Close 1 at $0.50 → P&L = (2.00 - 0.50) * 1 * 100 = $150
        lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=1, closing_price=0.50,
            closing_order_id="close-b", closing_transaction_id="tx-cb",
            closing_date=datetime(2025, 3, 12),
            chain_id="chain-pnl",
        )

        realized = lot_manager.get_realized_pnl_for_chain("chain-pnl")
        assert realized == pytest.approx(550.00)

    def test_clear_all_lots(self, lot_manager):
        """Clearing by underlying only removes matching lots/closings."""
        tx_aapl = make_option_transaction(id="tx-aapl", action="BUY_TO_OPEN", quantity=1)
        tx_spy = make_option_transaction(
            id="tx-spy", action="BUY_TO_OPEN", quantity=1,
            symbol="SPY 250321C00500000", underlying_symbol="SPY",
        )
        lot_manager.create_lot(tx_aapl, chain_id="c-aapl")
        lot_manager.create_lot(tx_spy, chain_id="c-spy")

        lot_manager.clear_all_lots(underlyings={"AAPL"})

        aapl = lot_manager.get_open_lots("ACCT1", underlying="AAPL")
        spy = lot_manager.get_open_lots("ACCT1", underlying="SPY")
        assert len(aapl) == 0
        assert len(spy) == 1

    def test_close_lot_direction_filter(self, lot_manager):
        """close_long=True only matches long lots; False only matches short lots."""
        tx_long = make_option_transaction(
            id="tx-long", action="BUY_TO_OPEN", quantity=2, price=2.00,
            executed_at="2025-03-01T10:00:00+00:00",
        )
        tx_short = make_option_transaction(
            id="tx-short", action="SELL_TO_OPEN", quantity=2, price=3.00,
            executed_at="2025-03-02T10:00:00+00:00",
        )
        lot_long = lot_manager.create_lot(tx_long, chain_id="chain-dir")
        lot_short = lot_manager.create_lot(tx_short, chain_id="chain-dir")

        # Try closing short direction — should only hit the short lot
        pnl, affected = lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=1, closing_price=2.00,
            closing_order_id="close-dir", closing_transaction_id="tx-cdir",
            closing_date=datetime(2025, 3, 15),
            close_long=False,
        )

        assert lot_short in affected
        assert lot_long not in affected
        # Short P&L: (3.00 - 2.00) * 1 * 100 = $100
        assert pnl == pytest.approx(100.00)
