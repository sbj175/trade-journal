"""
Tests for PnLCalculator — realized/unrealized P&L, chain P&L, lot-level P&L.

Source: src/models/pnl_calculator.py
"""

import pytest
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Set
from enum import Enum

from tests.conftest import make_option_transaction, make_stock_transaction


# ---------------------------------------------------------------------------
# Lightweight stub for Chain used by lot-based path
# ---------------------------------------------------------------------------

@dataclass
class _FakeChain:
    chain_id: str
    account_number: str


# ---------------------------------------------------------------------------
# Chain P&L — lot-based (V3)
# ---------------------------------------------------------------------------

class TestChainPnlLots:
    def test_chain_pnl_v3_lots(self, pnl_calculator, lot_manager):
        """Lot-based chain P&L: realized from closings + unrealized from open lots."""
        tx_open = make_option_transaction(
            id="tx-o", action="SELL_TO_OPEN", quantity=3, price=2.00,
        )
        lot_manager.create_lot(tx_open, chain_id="chain-v3")

        # Close 2 at $1.00 → realized = (2.00-1.00)*2*100 = $200
        lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=2, closing_price=1.00,
            closing_order_id="co-1", closing_transaction_id="tx-c1",
            closing_date=datetime(2025, 3, 10),
            chain_id="chain-v3",
        )

        chain = _FakeChain(chain_id="chain-v3", account_number="ACCT1")
        # 1 lot still open at 2.00, current price 0.50
        result = pnl_calculator.calculate_chain_pnl(
            chain, {"AAPL  250321C00170000": 0.50}
        )

        assert result.realized_pnl == pytest.approx(200.00)
        # Unrealized: (2.00 - 0.50) * 1 * 100 = $150
        assert result.unrealized_pnl == pytest.approx(150.00)
        assert result.total_pnl == pytest.approx(350.00)

    def test_chain_pnl_multiple_symbols(self, pnl_calculator, lot_manager):
        """Chain with 2 option legs, each with different current prices."""
        tx1 = make_option_transaction(
            id="tx-leg1", action="SELL_TO_OPEN", quantity=1, price=1.50,
            symbol="AAPL 250321P00160000",
        )
        tx2 = make_option_transaction(
            id="tx-leg2", action="SELL_TO_OPEN", quantity=1, price=2.00,
            symbol="AAPL 250321C00180000",
        )
        lot_manager.create_lot(tx1, chain_id="chain-multi", leg_index=0)
        lot_manager.create_lot(tx2, chain_id="chain-multi", leg_index=1)

        chain = _FakeChain(chain_id="chain-multi", account_number="ACCT1")
        result = pnl_calculator.calculate_chain_pnl(chain, {
            "AAPL 250321P00160000": 1.00,
            "AAPL 250321C00180000": 1.50,
        })

        # Put: (1.50 - 1.00) * 1 * 100 = $50
        # Call: (2.00 - 1.50) * 1 * 100 = $50
        assert result.unrealized_pnl == pytest.approx(100.00)

    def test_pnl_with_no_current_price(self, pnl_calculator, lot_manager):
        """Falls back to entry price when current_price missing → unrealized = 0."""
        tx = make_option_transaction(
            id="tx-no-price", action="BUY_TO_OPEN", quantity=1, price=2.00,
        )
        lot_manager.create_lot(tx, chain_id="chain-no-price")

        chain = _FakeChain(chain_id="chain-no-price", account_number="ACCT1")
        result = pnl_calculator.calculate_chain_pnl(chain, {})

        assert result.unrealized_pnl == pytest.approx(0.0)

    def test_chain_pnl_mixed_realized_unrealized(self, pnl_calculator, lot_manager):
        """Partially closed chain: some realized, some unrealized."""
        tx1 = make_option_transaction(
            id="tx-m1", action="SELL_TO_OPEN", quantity=2, price=3.00,
            executed_at="2025-03-01T10:00:00+00:00",
        )
        tx2 = make_option_transaction(
            id="tx-m2", action="SELL_TO_OPEN", quantity=2, price=2.50,
            executed_at="2025-03-02T10:00:00+00:00",
        )
        lot_manager.create_lot(tx1, chain_id="chain-mix")
        lot_manager.create_lot(tx2, chain_id="chain-mix")

        # Close 3 at $1.00 → FIFO: all of lot1 (2) + 1 of lot2
        # Lot1 P&L: (3.00-1.00)*2*100 = $400
        # Lot2 partial P&L: (2.50-1.00)*1*100 = $150
        lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=3, closing_price=1.00,
            closing_order_id="co-mix", closing_transaction_id="tx-cmix",
            closing_date=datetime(2025, 3, 10),
            chain_id="chain-mix",
        )

        chain = _FakeChain(chain_id="chain-mix", account_number="ACCT1")
        result = pnl_calculator.calculate_chain_pnl(
            chain, {"AAPL  250321C00170000": 0.50}
        )

        assert result.realized_pnl == pytest.approx(550.00)
        # 1 lot open: (2.50 - 0.50) * 1 * 100 = $200
        assert result.unrealized_pnl == pytest.approx(200.00)
        assert result.total_pnl == pytest.approx(750.00)


# ---------------------------------------------------------------------------
# Lot-level P&L breakdown
# ---------------------------------------------------------------------------

class TestLotLevelPnl:
    def test_lot_level_pnl_breakdown(self, pnl_calculator, lot_manager):
        """get_lot_level_pnl() returns per-lot details with closings."""
        tx = make_option_transaction(
            id="tx-ll", action="SELL_TO_OPEN", quantity=2, price=2.00,
        )
        lot_manager.create_lot(tx, chain_id="chain-ll")
        lot_manager.close_lot_fifo(
            account_number="ACCT1", symbol="AAPL  250321C00170000",
            quantity_to_close=1, closing_price=1.00,
            closing_order_id="co-ll", closing_transaction_id="tx-cll",
            closing_date=datetime(2025, 3, 10),
            chain_id="chain-ll",
        )

        breakdown = pnl_calculator.get_lot_level_pnl(
            "chain-ll", {"AAPL  250321C00170000": 0.50}
        )

        assert len(breakdown) == 1
        lot_info = breakdown[0]
        assert lot_info["realized_pnl"] == pytest.approx(100.00)
        # Remaining 1 lot short at 2.00, current 0.50: (2.00-0.50)*1*100 = $150
        assert lot_info["unrealized_pnl"] == pytest.approx(150.00)
        assert len(lot_info["closings"]) == 1
