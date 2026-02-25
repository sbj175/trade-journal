"""
Shadow comparison tests — runs old ``_derive_chains()`` and new
``chain_graph.derive_chains()`` on the same scenarios and diffs results.

Part of OPT-121 Stage 4.
"""

import pytest
from datetime import datetime

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

def _collect_unique_orders(chains_by_acct):
    """Extract unique Order objects from process_transactions output."""
    seen = set()
    orders = []
    for chains in chains_by_acct.values():
        for chain in chains:
            for order in chain.orders:
                if order.order_id not in seen:
                    orders.append(order)
                    seen.add(order.order_id)
    return orders


def _chain_order_ids(chain):
    """Sorted order IDs from a chain."""
    return sorted(o.order_id for o in chain.orders)


def _find_matching_chain(target_ids, chains):
    """Find a chain whose order IDs match the target set."""
    target_set = set(target_ids)
    for chain in chains:
        if set(o.order_id for o in chain.orders) == target_set:
            return chain
    return None


def _compare_chains(old_chains_by_acct, new_chains, label=""):
    """Compare old and new chain derivation results.

    Returns a list of divergence descriptions (empty = perfect match).
    """
    divergences = []
    prefix = f"[{label}] " if label else ""

    # Flatten old chains
    old_chains = []
    for chains in old_chains_by_acct.values():
        old_chains.extend(chains)

    # Compare chain count
    if len(old_chains) != len(new_chains):
        divergences.append(
            f"{prefix}Chain count: old={len(old_chains)}, new={len(new_chains)}"
        )

    # For each old chain, find matching new chain by order IDs
    for old_chain in old_chains:
        old_ids = _chain_order_ids(old_chain)
        new_chain = _find_matching_chain(old_ids, new_chains)

        if not new_chain:
            divergences.append(
                f"{prefix}Old chain {old_chain.chain_id} with orders {old_ids} "
                f"has no matching new chain"
            )
            continue

        # Compare status
        if old_chain.status != new_chain.status:
            divergences.append(
                f"{prefix}Status mismatch for orders {old_ids}: "
                f"old={old_chain.status}, new={new_chain.status}"
            )

        # Compare underlying
        if old_chain.underlying != new_chain.underlying:
            divergences.append(
                f"{prefix}Underlying mismatch for orders {old_ids}: "
                f"old={old_chain.underlying}, new={new_chain.underlying}"
            )

        # Compare account
        if old_chain.account_number != new_chain.account_number:
            divergences.append(
                f"{prefix}Account mismatch for orders {old_ids}: "
                f"old={old_chain.account_number}, new={new_chain.account_number}"
            )

    return divergences


# =====================================================================
# Shadow tests
# =====================================================================

class TestShadowSimpleClose:
    def test_simple_open_close(self, order_processor, db):
        """BTO → STC: both systems produce identical chain."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "simple_close")
        assert not divergences, "\n".join(divergences)


class TestShadowRollChain:
    def test_roll_chain(self, order_processor, db):
        """STO → roll → close: both systems produce single chain with 3 orders."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "roll_chain")
        assert not divergences, "\n".join(divergences)


class TestShadowIronCondor:
    def test_iron_condor_lifecycle(self, order_processor, db):
        """4-leg IC open + close: both systems produce identical chain."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "iron_condor")
        assert not divergences, "\n".join(divergences)


class TestShadowPartialClose:
    def test_partial_close(self, order_processor, db):
        """Open 4, close 2: both systems show OPEN status."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "partial_close")
        assert not divergences, "\n".join(divergences)


class TestShadowMultiAccount:
    def test_multi_account_isolation(self, order_processor, db):
        """Same underlying in two accounts: separate chains, both match."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "multi_account")
        assert not divergences, "\n".join(divergences)


class TestShadowExpiration:
    def test_expiration_close(self, order_processor, db):
        """STO → expiration: both systems close the chain."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "expiration")
        assert not divergences, "\n".join(divergences)


class TestShadowDoubleRoll:
    def test_double_roll(self, order_processor, db):
        """Open → roll → roll → close: single chain with 4 orders."""
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
        old_chains_by_acct = order_processor.process_transactions(txs)
        all_orders = _collect_unique_orders(old_chains_by_acct)
        new_chains = derive_chains(db, all_orders)

        divergences = _compare_chains(old_chains_by_acct, new_chains, "double_roll")
        assert not divergences, "\n".join(divergences)
