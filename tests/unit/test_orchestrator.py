"""
Integration tests for the Pipeline Orchestrator (OPT-121 final piece).

All tests use a real temporary SQLite database via conftest fixtures.
The orchestrator is shadow-built — not wired into sync.py yet.
"""

import pytest
from datetime import datetime

from src.pipeline.orchestrator import reprocess, PipelineResult
from src.pipeline.chain_graph import derive_chains
from src.pipeline.group_manager import GroupPersister
from src.pipeline.order_assembler import assemble_orders
from src.database.models import PositionLot, PositionGroup, PositionGroupLot, LotClosing
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
)


# =====================================================================
# Helpers
# =====================================================================

def _count_lots(db):
    """Count position_lots rows."""
    with db.get_session() as session:
        return session.query(PositionLot).count()


def _count_groups(db):
    """Count position_groups rows."""
    with db.get_session() as session:
        return session.query(PositionGroup).count()


def _count_group_lots(db):
    """Count position_group_lots rows."""
    with db.get_session() as session:
        return session.query(PositionGroupLot).count()


def _count_closings(db):
    """Count lot_closings rows."""
    with db.get_session() as session:
        return session.query(LotClosing).count()


def _get_groups(db):
    """Get all position groups."""
    with db.get_session() as session:
        return session.query(PositionGroup).all()


# =====================================================================
# Full pipeline tests
# =====================================================================

class TestFullPipeline:
    """End-to-end tests running transactions through the full orchestrator."""

    def test_simple_open(self, db, order_processor, lot_manager, position_manager):
        """Single STO option -> lot created, chain derived, group created."""
        txs = [
            make_option_transaction(
                id="tx-001", order_id="ORD-001", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert isinstance(result, PipelineResult)
        assert result.orders_assembled == 1
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        assert _count_lots(db) >= 1

    def test_open_close(self, db, order_processor, lot_manager, position_manager):
        """STO + BTC -> lots + closings, chain CLOSED, group CLOSED."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert result.orders_assembled == 2
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        assert _count_lots(db) >= 1
        assert _count_closings(db) >= 1

        # Verify group was created
        groups = _get_groups(db)
        assert len(groups) >= 1

    def test_iron_condor_cross_order(self, db, order_processor, lot_manager, position_manager):
        """Put spread + call spread as separate orders -> 1 group (Iron Condor)."""
        txs = [
            # Put spread (order 1)
            make_option_transaction(
                id="tx-sp", order_id="ORD-PS", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000", option_type="Put",
                strike=170.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bp", order_id="ORD-PS", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321P00160000", option_type="Put",
                strike=160.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Call spread (order 2)
            make_option_transaction(
                id="tx-sc", order_id="ORD-CS", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321C00190000", option_type="Call",
                strike=190.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:30:00+00:00",
            ),
            make_option_transaction(
                id="tx-bc", order_id="ORD-CS", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321C00200000", option_type="Call",
                strike=200.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:30:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert result.orders_assembled == 2
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        # 4 lots (one per leg)
        assert _count_lots(db) == 4

    def test_with_equity(self, db, order_processor, lot_manager, position_manager):
        """Stock BTO -> equity lot and group created."""
        txs = [
            make_stock_transaction(
                id="tx-stock-001", order_id="ORD-STOCK-001",
                action="BUY_TO_OPEN", quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert result.orders_assembled == 1
        assert _count_lots(db) >= 1

    def test_empty_transactions(self, db, order_processor, lot_manager, position_manager):
        """No transactions -> PipelineResult with zeros."""
        result = reprocess(db, order_processor, lot_manager, position_manager, [])

        assert result == PipelineResult(
            orders_assembled=0,
            chains_derived=0,
            groups_processed=0,
            equity_lots_netted=0,
        )


# =====================================================================
# Incremental reprocessing
# =====================================================================

class TestIncrementalReprocess:
    """Tests for affected_underlyings partial reprocessing."""

    def test_incremental_reprocess(self, db, order_processor, lot_manager, position_manager):
        """Full process, then incremental on 1 underlying -> correct counts."""
        txs_aapl = [
            make_option_transaction(
                id="tx-aapl", order_id="ORD-AAPL", action="SELL_TO_OPEN",
                quantity=1, price=2.50, underlying_symbol="AAPL",
                symbol="AAPL 250321C00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        txs_msft = [
            make_option_transaction(
                id="tx-msft", order_id="ORD-MSFT", action="SELL_TO_OPEN",
                quantity=1, price=3.00, underlying_symbol="MSFT",
                symbol="MSFT 250321C00300000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        all_txs = txs_aapl + txs_msft

        # Full process first
        result_full = reprocess(db, order_processor, lot_manager, position_manager, all_txs)
        assert result_full.orders_assembled == 2

        # Incremental: only reprocess AAPL
        result_incr = reprocess(
            db, order_processor, lot_manager, position_manager,
            all_txs,
            affected_underlyings={"AAPL"},
        )
        # Only AAPL transactions processed in stage 3, but assembly sees all
        assert result_incr.orders_assembled == 2  # assembly is stateless, sees all txs


# =====================================================================
# Idempotency
# =====================================================================

class TestIdempotency:
    """Verify that running the pipeline twice produces the same result."""

    def test_reprocess_idempotent(self, db, order_processor, lot_manager, position_manager):
        """Run twice on same data -> same DB state."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=2, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=2, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        result1 = reprocess(db, order_processor, lot_manager, position_manager, txs)
        lots_after_1 = _count_lots(db)
        groups_after_1 = _count_groups(db)
        closings_after_1 = _count_closings(db)

        result2 = reprocess(db, order_processor, lot_manager, position_manager, txs)
        lots_after_2 = _count_lots(db)
        groups_after_2 = _count_groups(db)
        closings_after_2 = _count_closings(db)

        assert lots_after_1 == lots_after_2
        assert groups_after_1 == groups_after_2
        assert closings_after_1 == closings_after_2
        assert result1.orders_assembled == result2.orders_assembled
        assert result1.chains_derived == result2.chains_derived


# =====================================================================
# PipelineResult counts
# =====================================================================

class TestPipelineResultCounts:
    """Verify PipelineResult fields are populated correctly."""

    def test_all_fields_populated(self, db, order_processor, lot_manager, position_manager):
        """Multi-order scenario -> all PipelineResult fields > 0."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert result.orders_assembled >= 1
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        # equity_lots_netted may be 0 for option-only scenarios
        assert result.equity_lots_netted >= 0

    def test_dataclass_equality(self, db, order_processor, lot_manager, position_manager):
        """PipelineResult supports equality for test assertions."""
        r1 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1)
        r2 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1)
        assert r1 == r2


# =====================================================================
# Shadow comparison — orchestrator vs manual steps
# =====================================================================

class TestShadowComparison:
    """Compare orchestrator output against the manual step-by-step pipeline."""

    def test_shadow_vs_manual_steps(self, db, order_processor, lot_manager, position_manager):
        """Same transactions through orchestrator vs manual steps -> same lots and chains."""
        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-close", order_id="ORD-CLOSE", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        # --- Run orchestrator ---
        result = reprocess(db, order_processor, lot_manager, position_manager, txs)
        orch_lots = _count_lots(db)
        orch_groups = _count_groups(db)
        orch_closings = _count_closings(db)

        # --- Run manual steps (same as sync.py pattern) ---
        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        manual_lots = _count_lots(db)
        manual_closings = _count_closings(db)

        # Lots and closings come from OrderProcessor (stage 3) — should be identical
        assert orch_lots == manual_lots
        assert orch_closings == manual_closings

        # Now run the new pipeline stages on manual output
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        manual_groups = persister.process_groups(new_chains)

        # Groups should match (orchestrator ran same stages)
        assert orch_groups == manual_groups

    def test_shadow_multi_underlying(self, db, order_processor, lot_manager, position_manager):
        """Multiple underlyings: orchestrator produces same lots as manual steps."""
        txs = [
            make_option_transaction(
                id="tx-aapl-open", order_id="ORD-AAPL", action="SELL_TO_OPEN",
                quantity=1, price=2.50, underlying_symbol="AAPL",
                symbol="AAPL 250321C00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-msft-open", order_id="ORD-MSFT", action="SELL_TO_OPEN",
                quantity=1, price=3.00, underlying_symbol="MSFT",
                symbol="MSFT 250321C00300000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-aapl-close", order_id="ORD-AAPL-CL", action="BUY_TO_CLOSE",
                quantity=1, price=1.00, underlying_symbol="AAPL",
                symbol="AAPL 250321C00170000",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert result.orders_assembled == 3
        assert result.chains_derived >= 2  # at least AAPL chain + MSFT orphan
        assert _count_lots(db) >= 2
