"""
Graph-derived chain tests — verifies that ``chain_graph.derive_chains()``
produces correct chains from lots created by ``process_transactions()``.

Part of OPT-121 Stage 4.
"""

import pytest
from datetime import datetime

from src.pipeline.order_assembler import assemble_orders
from src.pipeline.chain_graph import derive_chains
from src.models.order_processor import OrderProcessor
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_assignment_transaction,
    make_expiration_transaction,
)


# =====================================================================
# Helpers
# =====================================================================

def _chain_order_ids(chain):
    """Sorted order IDs from a chain."""
    return sorted(o.order_id for o in chain.orders)


def _find_chain_with_order(order_id, chains):
    """Find a chain containing the given order ID."""
    for chain in chains:
        if order_id in {o.order_id for o in chain.orders}:
            return chain
    return None


# =====================================================================
# Graph chain tests
# =====================================================================

class TestGraphSimpleClose:
    def test_simple_open_close(self, order_processor, db):
        """BTO -> STC: graph produces a single CLOSED chain with both orders."""
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
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"
        assert set(o.order_id for o in chain.orders) == {"ORD-OPEN", "ORD-CLOSE"}


class TestGraphRollChain:
    def test_roll_chain(self, order_processor, db):
        """STO -> roll -> close: single chain with 3 orders."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
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
            make_option_transaction(
                id="tx-final-close", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                symbol="AAPL 250418P00170000",
                executed_at="2025-04-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"
        assert set(o.order_id for o in chain.orders) == {"ORD-1", "ORD-2", "ORD-3"}


class TestGraphIronCondor:
    def test_iron_condor_lifecycle(self, order_processor, db):
        """4-leg IC open + close: single chain with both orders."""
        txs = [
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
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"
        assert set(o.order_id for o in chain.orders) == {"ORD-IC", "ORD-IC-CLOSE"}


class TestGraphPartialClose:
    def test_partial_close(self, order_processor, db):
        """Open 4, close 2: chain should be OPEN."""
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
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "OPEN"
        assert set(o.order_id for o in chain.orders) == {"ORD-OPEN", "ORD-CLOSE"}


class TestGraphMultiAccount:
    def test_multi_account_isolation(self, order_processor, db):
        """Same underlying in two accounts: separate chains."""
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
            make_option_transaction(
                id="tx-c1", order_id="ORD-C1", action="BUY_TO_CLOSE",
                quantity=1, price=1.00, account_number="ACCT1",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 2

        acct1_chain = _find_chain_with_order("ORD-A1", chains)
        acct2_chain = _find_chain_with_order("ORD-A2", chains)

        assert acct1_chain is not None
        assert acct2_chain is not None

        assert acct1_chain.status == "CLOSED"
        assert acct1_chain.account_number == "ACCT1"

        assert acct2_chain.status == "OPEN"
        assert acct2_chain.account_number == "ACCT2"


class TestGraphExpiration:
    def test_expiration_close(self, order_processor, db):
        """STO -> expiration: chain should be CLOSED."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL  250321C00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_expiration_transaction(
                id="tx-exp",
                symbol="AAPL  250321C00170000",
                quantity=1,
                executed_at="2025-03-21T16:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) >= 1
        # Find the chain containing the opening order
        chain = _find_chain_with_order("ORD-OPEN", chains)
        assert chain is not None
        assert chain.status == "CLOSED"


class TestGraphDoubleRoll:
    def test_double_roll(self, order_processor, db):
        """Open -> roll -> roll -> close: single chain with 4 orders."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # First roll
            make_option_transaction(
                id="tx-r1-close", order_id="ORD-2", action="BUY_TO_CLOSE",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-r1-open", order_id="ORD-2", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                symbol="AAPL 250418P00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            # Second roll
            make_option_transaction(
                id="tx-r2-close", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=2.00,
                symbol="AAPL 250418P00170000",
                executed_at="2025-04-05T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-r2-open", order_id="ORD-3", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                symbol="AAPL 250516P00170000",
                executed_at="2025-04-05T10:00:00+00:00",
            ),
            # Final close
            make_option_transaction(
                id="tx-final-close", order_id="ORD-4", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                symbol="AAPL 250516P00170000",
                executed_at="2025-05-01T10:00:00+00:00",
            ),
        ]
        order_processor.process_transactions(txs)
        assembly = assemble_orders(txs)
        chains = derive_chains(db, assembly.orders)

        assert len(chains) == 1
        chain = chains[0]
        assert chain.status == "CLOSED"
        assert set(o.order_id for o in chain.orders) == {"ORD-1", "ORD-2", "ORD-3", "ORD-4"}
