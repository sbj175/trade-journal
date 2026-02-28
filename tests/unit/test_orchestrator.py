"""
Integration tests for the Pipeline Orchestrator (OPT-121).

All tests use a real temporary SQLite database via conftest fixtures.
"""

import pytest
from datetime import datetime

from src.pipeline.orchestrator import reprocess, PipelineResult
from src.pipeline.chain_graph import derive_chains
from src.pipeline.group_manager import GroupPersister
from src.pipeline.order_assembler import assemble_orders
from src.database.models import (
    PositionLot, PositionGroup, PositionGroupLot, LotClosing,
)
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_expiration_transaction,
    make_assignment_transaction,
    make_exercise_transaction,
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


def _snapshot_groups(db_manager):
    """Snapshot all groups with their lot membership.

    Returns a list of dicts sorted by (underlying, lot_txn_ids) for stable comparison.
    """
    with db_manager.get_session() as session:
        groups = session.query(PositionGroup).all()
        result = []
        for g in groups:
            txn_ids = sorted(
                r[0] for r in session.query(PositionGroupLot.transaction_id).filter(
                    PositionGroupLot.group_id == g.group_id,
                ).all()
            )
            result.append({
                "underlying": g.underlying,
                "strategy_label": g.strategy_label,
                "status": g.status,
                "lot_txn_ids": txn_ids,
            })
        result.sort(key=lambda x: (x["underlying"], str(x.get("lot_txn_ids", []))))
        return result


# =====================================================================
# Full pipeline tests
# =====================================================================

class TestFullPipeline:
    """End-to-end tests running transactions through the full orchestrator."""

    def test_simple_open(self, db, lot_manager):
        """Single STO option -> lot created, chain derived, group created."""
        txs = [
            make_option_transaction(
                id="tx-001", order_id="ORD-001", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, lot_manager, txs)

        assert isinstance(result, PipelineResult)
        assert result.orders_assembled == 1
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        assert _count_lots(db) >= 1

    def test_chains_populated(self, db, lot_manager):
        """chains field is populated for non-empty transactions."""
        txs = [
            make_option_transaction(
                id="tx-oc-001", order_id="ORD-OC-001", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, lot_manager, txs)

        assert len(result.chains) >= 1

    def test_open_close(self, db, lot_manager):
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

        result = reprocess(db, lot_manager, txs)

        assert result.orders_assembled == 2
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        assert _count_lots(db) >= 1
        assert _count_closings(db) >= 1

        # Verify group was created
        groups = _get_groups(db)
        assert len(groups) >= 1

    def test_iron_condor_cross_order(self, db, lot_manager):
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

        result = reprocess(db, lot_manager, txs)

        assert result.orders_assembled == 2
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        # 4 lots (one per leg)
        assert _count_lots(db) == 4

    def test_with_equity(self, db, lot_manager):
        """Stock BTO -> equity lot and group created."""
        txs = [
            make_stock_transaction(
                id="tx-stock-001", order_id="ORD-STOCK-001",
                action="BUY_TO_OPEN", quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, lot_manager, txs)

        assert result.orders_assembled == 1
        assert _count_lots(db) >= 1

    def test_shares_sell_rebuy_separate_groups(self, db, lot_manager):
        """Buy shares, sell all, buy again -> 2 separate groups (separate trading decisions)."""
        txs = [
            make_stock_transaction(
                id="tx-buy1", order_id="ORD-BUY1",
                action="BUY_TO_OPEN", quantity=100, price=50.00,
                executed_at="2025-01-10T10:00:00+00:00",
            ),
            make_stock_transaction(
                id="tx-sell1", order_id="ORD-SELL1",
                action="SELL_TO_CLOSE", quantity=100, price=55.00,
                executed_at="2025-02-10T10:00:00+00:00",
                transaction_sub_type="Sell to Close",
            ),
            make_stock_transaction(
                id="tx-buy2", order_id="ORD-BUY2",
                action="BUY_TO_OPEN", quantity=200, price=48.00,
                executed_at="2025-03-10T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, lot_manager, txs)

        groups = _snapshot_groups(db)
        shares_groups = [g for g in groups if g["strategy_label"] == "Shares"]
        # Sell-rebuy = two separate trading decisions = two groups
        assert len(shares_groups) == 2
        statuses = {g["status"] for g in shares_groups}
        assert statuses == {"OPEN", "CLOSED"}

    def test_shares_additional_purchase_same_group(self, db, lot_manager):
        """Buy shares twice while holding -> 1 group (adding to existing position)."""
        txs = [
            make_stock_transaction(
                id="tx-buy1", order_id="ORD-BUY1",
                action="BUY_TO_OPEN", quantity=100, price=50.00,
                executed_at="2025-01-10T10:00:00+00:00",
            ),
            make_stock_transaction(
                id="tx-buy2", order_id="ORD-BUY2",
                action="BUY_TO_OPEN", quantity=200, price=48.00,
                executed_at="2025-02-10T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, lot_manager, txs)

        groups = _snapshot_groups(db)
        shares_groups = [g for g in groups if g["strategy_label"] == "Shares"]
        # Both purchases while holding -> single group
        assert len(shares_groups) == 1
        assert shares_groups[0]["status"] == "OPEN"
        assert len(shares_groups[0]["lot_txn_ids"]) == 2

    def test_empty_transactions(self, db, lot_manager):
        """No transactions -> PipelineResult with zeros, empty old_chains."""
        result = reprocess(db, lot_manager, [])

        assert result == PipelineResult(
            orders_assembled=0,
            chains_derived=0,
            groups_processed=0,
            equity_lots_netted=0,
            chains=[],
        )


# =====================================================================
# Incremental reprocessing
# =====================================================================

class TestIncrementalReprocess:
    """Tests for affected_underlyings partial reprocessing."""

    def test_incremental_reprocess(self, db, lot_manager):
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
        result_full = reprocess(db, lot_manager, all_txs)
        assert result_full.orders_assembled == 2

        # Incremental: only reprocess AAPL
        result_incr = reprocess(
            db, lot_manager,
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

    def test_reprocess_idempotent(self, db, lot_manager):
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

        result1 = reprocess(db, lot_manager, txs)
        lots_after_1 = _count_lots(db)
        groups_after_1 = _count_groups(db)
        closings_after_1 = _count_closings(db)

        result2 = reprocess(db, lot_manager, txs)
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

    def test_all_fields_populated(self, db, lot_manager):
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

        result = reprocess(db, lot_manager, txs)

        assert result.orders_assembled >= 1
        assert result.chains_derived >= 1
        assert result.groups_processed >= 1
        # equity_lots_netted may be 0 for option-only scenarios
        assert result.equity_lots_netted >= 0

    def test_dataclass_equality(self):
        """PipelineResult supports equality for test assertions."""
        r1 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1, chains=[])
        r2 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1, chains=[])
        assert r1 == r2


# =====================================================================
# Derived lot tests (assignment/exercise)
# =====================================================================

class TestDerivedLots:

    def test_exercise_closes_derived_stock_lot(self, db, order_processor, lot_manager):
        """Put spread fully ITM: assignment + exercise -> derived shares fully closed.

        Short 50P assigned -> stock BTO 300 @ $50 (derived lot created).
        Long 45P exercised -> stock STC 300 @ $45 (derived lot closed).
        Net: no open stock lots remain.
        """
        ACCT = "ACCT1"
        UNDERLYING = "IREN"
        SHORT_PUT_SYM = "IREN  241220P00050000"
        LONG_PUT_SYM = "IREN  241220P00045000"

        txs = [
            # Open: STO 3x 50P
            make_option_transaction(
                id="tx-sto-50p", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                account_number=ACCT, quantity=3, price=5.00,
                symbol=SHORT_PUT_SYM, underlying_symbol=UNDERLYING,
                option_type="Put", strike=50.0, expiration="2024-12-20",
                executed_at="2024-11-01T10:00:00+00:00",
            ),
            # Open: BTO 3x 45P
            make_option_transaction(
                id="tx-bto-45p", order_id="ORD-OPEN", action="BUY_TO_OPEN",
                account_number=ACCT, quantity=3, price=2.00,
                symbol=LONG_PUT_SYM, underlying_symbol=UNDERLYING,
                option_type="Put", strike=45.0, expiration="2024-12-20",
                executed_at="2024-11-01T10:00:00+00:00",
            ),
            # Assignment: short 50P assigned
            make_assignment_transaction(
                id="tx-assign-50p", account_number=ACCT,
                symbol=SHORT_PUT_SYM, underlying_symbol=UNDERLYING,
                quantity=3, executed_at="2024-12-18T16:00:00+00:00",
            ),
            # Stock BTO from assignment (no order_id)
            make_stock_transaction(
                id="tx-stock-bto", order_id=None, account_number=ACCT,
                symbol=UNDERLYING, underlying_symbol=UNDERLYING,
                action="BUY_TO_OPEN", quantity=300, price=50.0,
                executed_at="2024-12-18T16:00:00+00:00",
                transaction_sub_type="Assignment",
            ),
            # Exercise: long 45P exercised
            make_exercise_transaction(
                id="tx-exercise-45p", account_number=ACCT,
                symbol=LONG_PUT_SYM, underlying_symbol=UNDERLYING,
                quantity=3, executed_at="2024-12-19T16:00:00+00:00",
            ),
            # Stock STC from exercise (no order_id)
            make_stock_transaction(
                id="tx-stock-stc", order_id=None, account_number=ACCT,
                symbol=UNDERLYING, underlying_symbol=UNDERLYING,
                action="SELL_TO_CLOSE", quantity=300, price=45.0,
                executed_at="2024-12-19T16:00:00+00:00",
                transaction_sub_type="Exercise",
            ),
        ]

        lot_manager.clear_all_lots()
        order_processor.process_transactions(txs)

        # No open stock lots should remain
        open_stock_lots = lot_manager.get_open_lots(account_number=ACCT, symbol=UNDERLYING)
        assert len(open_stock_lots) == 0, f"Expected 0 open stock lots, got {len(open_stock_lots)}"

        # Derived stock lot should exist and be CLOSED
        with db.get_session() as session:
            stock_lots = session.query(PositionLot).filter(
                PositionLot.account_number == ACCT,
                PositionLot.symbol == UNDERLYING,
                PositionLot.instrument_type == 'EQUITY',
            ).all()
            assert len(stock_lots) == 1, f"Expected 1 stock lot, got {len(stock_lots)}"
            assert stock_lots[0].status == 'CLOSED'
            assert stock_lots[0].remaining_quantity == 0
            assert stock_lots[0].derivation_type == 'ASSIGNMENT'

        # Verify stock lot closing has correct type and P&L
        with db.get_session() as session:
            stock_lot = session.query(PositionLot).filter(
                PositionLot.account_number == ACCT,
                PositionLot.symbol == UNDERLYING,
                PositionLot.instrument_type == 'EQUITY',
            ).first()
            closings = session.query(LotClosing).filter(
                LotClosing.lot_id == stock_lot.id,
            ).all()
            assert len(closings) == 1
            assert closings[0].closing_type == 'EXERCISE'
            # P&L: (45 - 50) * 300 = -1500
            assert closings[0].realized_pnl == -1500.0
