"""
Integration tests — end-to-end: transactions → chains → P&L.

Exercises the full OrderProcessor pipeline with realistic multi-step scenarios.
"""

import pytest
from datetime import datetime

from src.models.order_processor import OrderType
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_expiration_transaction,
    make_assignment_transaction,
)


# ---------------------------------------------------------------------------
# Simple open → close
# ---------------------------------------------------------------------------

class TestSimpleOpenClose:
    def test_simple_open_close_chain(self, order_processor, lot_manager):
        """BTO → STC: full lifecycle with correct P&L."""
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

        chains_by_acct = order_processor.process_transactions(txs)
        chains = chains_by_acct["ACCT1"]

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"

        # Verify lot-based P&L
        realized = lot_manager.get_realized_pnl_for_chain(chain.chain_id)
        # (3.00 - 1.50) * 2 * 100 = $300
        assert realized == pytest.approx(300.00)


# ---------------------------------------------------------------------------
# Roll chain
# ---------------------------------------------------------------------------

class TestRollChain:
    def test_roll_chain(self, order_processor, lot_manager):
        """STO put → BTC + STO new put: chain links 3 orders, cumulative P&L correct."""
        txs = [
            # Open initial position
            make_option_transaction(
                id="tx-open", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Roll: close old, open new (same order)
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
            # Close rolled position
            make_option_transaction(
                id="tx-final-close", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                symbol="AAPL 250418P00170000",
                executed_at="2025-04-01T10:00:00+00:00",
            ),
        ]

        chains_by_acct = order_processor.process_transactions(txs)
        chains = chains_by_acct["ACCT1"]

        # All orders should be in a single chain
        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"

        # Total realized P&L across the chain:
        # Leg 1: STO at 2.00, BTC at 1.50 → (2.00-1.50)*1*100 = $50
        # Leg 2: STO at 2.50, BTC at 1.00 → (2.50-1.00)*1*100 = $150
        realized = lot_manager.get_realized_pnl_for_chain(chain.chain_id)
        assert realized == pytest.approx(200.00)


# ---------------------------------------------------------------------------
# Iron Condor lifecycle
# ---------------------------------------------------------------------------

class TestIronCondorLifecycle:
    def test_iron_condor_lifecycle(self, order_processor, lot_manager):
        """Open 4-leg IC → close at different times → verify total P&L."""
        txs = [
            # Open IC (4 legs in one order)
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
            # Close all 4 legs
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

        chains_by_acct = order_processor.process_transactions(txs)
        chains = chains_by_acct["ACCT1"]

        assert len(chains) == 1
        assert chains[0].status == "CLOSED"

        realized = lot_manager.get_realized_pnl_for_chain(chains[0].chain_id)
        # Short put: (1.50-0.50)*100 = $100
        # Long put:  (0.10-0.50)*100 = -$40
        # Short call: (1.50-0.50)*100 = $100
        # Long call: (0.10-0.50)*100 = -$40
        # Total = $120
        assert realized == pytest.approx(120.00)


# ---------------------------------------------------------------------------
# Partial close
# ---------------------------------------------------------------------------

class TestPartialClose:
    def test_partial_close_proportional(self, order_processor, lot_manager):
        """Open 4 contracts, close 2: verify 50% realized."""
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

        chains_by_acct = order_processor.process_transactions(txs)
        chains = chains_by_acct["ACCT1"]

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "OPEN"  # Still has 2 open contracts

        # Realized P&L from lot closings: (2.00 - 1.00) * 2 * 100 = $200
        realized = lot_manager.get_realized_pnl_for_chain(chain.chain_id)
        assert realized == pytest.approx(200.00)

        # 2 contracts still open
        open_lots = lot_manager.get_open_lots("ACCT1", chain_id=chain.chain_id)
        total_remaining = sum(abs(lot.remaining_quantity) for lot in open_lots)
        assert total_remaining == 2


# ---------------------------------------------------------------------------
# Multiple accounts isolation
# ---------------------------------------------------------------------------

class TestMultipleAccountsIsolated:
    def test_multiple_accounts_isolated(self, order_processor, lot_manager):
        """Same underlying in two accounts: separate chains, no cross-contamination."""
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
            # Close ACCT1 only
            make_option_transaction(
                id="tx-c1", order_id="ORD-C1", action="BUY_TO_CLOSE",
                quantity=1, price=1.00, account_number="ACCT1",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        chains_by_acct = order_processor.process_transactions(txs)

        acct1_chains = chains_by_acct.get("ACCT1", [])
        acct2_chains = chains_by_acct.get("ACCT2", [])

        assert len(acct1_chains) == 1
        assert len(acct2_chains) == 1

        # ACCT1 chain should be closed
        assert acct1_chains[0].status == "CLOSED"
        # ACCT2 chain should still be open
        assert acct2_chains[0].status == "OPEN"

        # Verify realized P&L is only on ACCT1
        acct1_pnl = lot_manager.get_realized_pnl_for_chain(acct1_chains[0].chain_id)
        assert acct1_pnl == pytest.approx(100.00)  # (2.00-1.00)*1*100

        # ACCT2 should have no realized P&L
        acct2_pnl = lot_manager.get_realized_pnl_for_chain(acct2_chains[0].chain_id)
        assert acct2_pnl == pytest.approx(0.0)
