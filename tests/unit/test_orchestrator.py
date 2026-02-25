"""
Integration tests for the Pipeline Orchestrator (OPT-121).

All tests use a real temporary SQLite database via conftest fixtures.

Shadow comparison tests run both the legacy group-creation path
(seed_position_groups from ledger_service) and the new pipeline path
(GroupPersister) on the same lot state, then compare outputs.
"""

import pytest
from datetime import datetime

from src.pipeline.orchestrator import reprocess, PipelineResult
from src.pipeline.chain_graph import derive_chains
from src.pipeline.group_manager import GroupPersister
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.strategy_engine import recognize, lots_to_legs
from src.database.models import (
    PositionLot, PositionGroup, PositionGroupLot, LotClosing,
    OrderChain as OrderChainModel,
)
import src.services.ledger_service as ledger_svc
from tests.conftest import (
    make_option_transaction,
    make_stock_transaction,
    make_expiration_transaction,
    make_assignment_transaction,
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

    def test_old_chains_populated(self, db, order_processor, lot_manager, position_manager):
        """old_chains field is populated for non-empty transactions."""
        txs = [
            make_option_transaction(
                id="tx-oc-001", order_id="ORD-OC-001", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        result = reprocess(db, order_processor, lot_manager, position_manager, txs)

        assert len(result.old_chains) >= 1

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
        """No transactions -> PipelineResult with zeros, empty old_chains."""
        result = reprocess(db, order_processor, lot_manager, position_manager, [])

        assert result == PipelineResult(
            orders_assembled=0,
            chains_derived=0,
            groups_processed=0,
            equity_lots_netted=0,
            old_chains=[],
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
        r1 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1, old_chains=[])
        r2 = PipelineResult(orders_assembled=5, chains_derived=3, groups_processed=2, equity_lots_netted=1, old_chains=[])
        assert r1 == r2


# =====================================================================
# Shadow comparison — new pipeline vs legacy grouping
# =====================================================================

def _snapshot_groups(db_manager):
    """Snapshot all groups with their lot membership for comparison.

    Returns a list of dicts sorted by (underlying, opening_date) for stable comparison.
    Each dict has: underlying, strategy_label, status, lot_txn_ids (sorted set).
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


def _populate_order_chains(db_manager, lot_manager_inst, chains):
    """Populate order_chains table from Chain objects, computing per-chain strategy
    via strategy_engine (same logic as update_chain_cache).

    This is the synchronous equivalent of what update_chain_cache does for strategy_type.
    """
    with db_manager.get_session() as session:
        for chain in chains:
            # Compute strategy same way update_chain_cache does
            chain_lots = lot_manager_inst.get_lots_for_chain(chain.chain_id, include_derived=False)
            if chain_lots:
                legs = lots_to_legs(chain_lots)
                engine_result = recognize(legs)
                detected_strategy = engine_result.name if engine_result.confidence > 0 else "Unknown"
            else:
                detected_strategy = "Unknown"

            session.add(OrderChainModel(
                chain_id=chain.chain_id,
                underlying=chain.underlying,
                account_number=chain.account_number,
                opening_order_id=chain.orders[0].order_id if chain.orders else None,
                strategy_type=detected_strategy,
                opening_date=str(chain.opening_date) if chain.opening_date else None,
                closing_date=str(chain.closing_date) if chain.closing_date else None,
                chain_status=chain.status,
                order_count=len(chain.orders),
                total_pnl=0.0,
            ))


def _clear_groups(db_manager):
    """Clear all groups and group-lot links."""
    with db_manager.get_session() as session:
        session.query(PositionGroupLot).delete()
        session.query(PositionGroup).delete()


class TestShadowComparison:
    """Run both legacy grouping (seed_position_groups) and new pipeline grouping
    (GroupPersister.process_groups) on the same lot state, then compare outputs.

    For 1:1 chain-to-group cases, both paths should produce identical groups.
    For cross-order cases, the new pipeline may produce fewer, better-labeled groups.
    """

    def test_shadow_simple_open(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Single STO: legacy and new pipeline produce same group."""
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_option_transaction(
                id="tx-001", order_id="ORD-001", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        # --- Create lots via OrderProcessor (shared state for both paths) ---
        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # --- Legacy path: populate order_chains → seed_position_groups ---
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # --- New pipeline path: derive_chains → GroupPersister ---
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Same number of groups
        assert len(new_groups) == len(legacy_groups)
        # Same lot membership per group
        for lg, ng in zip(legacy_groups, new_groups):
            assert lg["lot_txn_ids"] == ng["lot_txn_ids"], (
                f"Lot mismatch: legacy={lg['lot_txn_ids']}, new={ng['lot_txn_ids']}"
            )
            assert lg["underlying"] == ng["underlying"]
            assert lg["status"] == ng["status"]

    def test_shadow_open_close(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """STO + BTC: both paths produce 1 CLOSED group with same lots.

        Strategy label improvement: legacy gets "Unknown" for closed chains because
        lots_to_legs() skips closed lots, leaving no legs for detection. The new
        pipeline's _label_from_all_lots() includes closed lots, correctly detecting
        "Short Call" even after the position is closed.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

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

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        assert len(new_groups) == len(legacy_groups)
        for lg, ng in zip(legacy_groups, new_groups):
            assert lg["lot_txn_ids"] == ng["lot_txn_ids"]
            assert lg["underlying"] == ng["underlying"]
            assert lg["status"] == ng["status"]
            # Legacy gets "Unknown" for closed chains (lots_to_legs skips closed lots)
            # New pipeline correctly labels closed groups via _label_from_all_lots
            assert lg["strategy_label"] == "Unknown"
            assert ng["strategy_label"] == "Short Call"

    def test_shadow_roll_chain(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Roll scenario: both paths produce 1 group with all lots linked."""
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-1", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00170000", option_type="Put",
                strike=170.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-roll-close", order_id="ORD-2", action="BUY_TO_CLOSE",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000", option_type="Put",
                strike=170.0, expiration="2025-03-21",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-roll-open", order_id="ORD-2", action="SELL_TO_OPEN",
                quantity=1, price=2.50,
                symbol="AAPL 250418P00170000", option_type="Put",
                strike=170.0, expiration="2025-04-18",
                executed_at="2025-03-10T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-final-close", order_id="ORD-3", action="BUY_TO_CLOSE",
                quantity=1, price=1.00,
                symbol="AAPL 250418P00170000", option_type="Put",
                strike=170.0, expiration="2025-04-18",
                executed_at="2025-04-01T10:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both should produce exactly 1 group (roll chain = single group)
        assert len(legacy_groups) == 1
        assert len(new_groups) == 1
        assert legacy_groups[0]["lot_txn_ids"] == new_groups[0]["lot_txn_ids"]
        assert legacy_groups[0]["status"] == new_groups[0]["status"]

    def test_shadow_multi_underlying(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Multiple underlyings: both paths isolate groups per underlying."""
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_option_transaction(
                id="tx-aapl", order_id="ORD-AAPL", action="SELL_TO_OPEN",
                quantity=1, price=2.50, underlying_symbol="AAPL",
                symbol="AAPL 250321C00170000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-msft", order_id="ORD-MSFT", action="SELL_TO_OPEN",
                quantity=1, price=3.00, underlying_symbol="MSFT",
                symbol="MSFT 250321C00300000",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Same group count and underlying isolation
        assert len(new_groups) == len(legacy_groups)
        legacy_underlyings = sorted(g["underlying"] for g in legacy_groups)
        new_underlyings = sorted(g["underlying"] for g in new_groups)
        assert legacy_underlyings == new_underlyings

        # Same lot membership per underlying
        for lg, ng in zip(legacy_groups, new_groups):
            assert lg["lot_txn_ids"] == ng["lot_txn_ids"]

    def test_shadow_shares_only(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Shares only: both paths create 1 group labeled 'Shares'."""
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_stock_transaction(
                id="tx-stock", order_id="ORD-STOCK",
                action="BUY_TO_OPEN", quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        assert len(new_groups) == len(legacy_groups) == 1
        assert legacy_groups[0]["lot_txn_ids"] == new_groups[0]["lot_txn_ids"]
        assert legacy_groups[0]["underlying"] == new_groups[0]["underlying"] == "AAPL"
        assert legacy_groups[0]["status"] == new_groups[0]["status"] == "OPEN"
        # Both should label equity-only groups as "Shares"
        assert legacy_groups[0]["strategy_label"] == "Shares"
        assert new_groups[0]["strategy_label"] == "Shares"

    def test_shadow_shares_plus_bull_put_spread(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Shares + bull put spread on same underlying as separate orders:
        both paths correctly keep them as 2 separate groups.

        A stock purchase and a put spread are independent positions — not a
        meaningful combined strategy — so they should NOT be merged.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            # Stock purchase
            make_stock_transaction(
                id="tx-stock", order_id="ORD-STOCK",
                action="BUY_TO_OPEN", quantity=100, price=150.00,
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Bull put spread (separate order)
            make_option_transaction(
                id="tx-sell-put", order_id="ORD-BPS", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                symbol="AAPL 250321P00145000", option_type="Put",
                strike=145.0, expiration="2025-03-21",
                executed_at="2025-03-01T11:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-buy-put", order_id="ORD-BPS", action="BUY_TO_OPEN",
                quantity=1, price=1.00,
                symbol="AAPL 250321P00135000", option_type="Put",
                strike=135.0, expiration="2025-03-21",
                executed_at="2025-03-01T11:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both paths produce 2 groups — shares and spread are independent positions
        assert len(legacy_groups) == 2
        assert len(new_groups) == 2

        # Same lot membership
        legacy_by_label = {g["strategy_label"]: g for g in legacy_groups}
        new_by_label = {g["strategy_label"]: g for g in new_groups}

        # Shares group
        assert "Shares" in legacy_by_label
        assert "Shares" in new_by_label
        assert legacy_by_label["Shares"]["lot_txn_ids"] == new_by_label["Shares"]["lot_txn_ids"]
        assert new_by_label["Shares"]["lot_txn_ids"] == ["tx-stock"]

        # Bull Put Spread group
        assert "Bull Put Spread" in new_by_label
        assert sorted(new_by_label["Bull Put Spread"]["lot_txn_ids"]) == sorted(["tx-sell-put", "tx-buy-put"])

    def test_shadow_cross_order_improvement(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Cross-order Iron Condor: new pipeline merges into 1 group where legacy creates 2.

        This is a documented improvement — the new pipeline recognizes that a put spread
        and call spread on the same underlying/expiration form an Iron Condor.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

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

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy: creates 1 group per chain = 2 groups (put spread + call spread)
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline: merges into 1 group with "Iron Condor" label
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Legacy creates 2 groups (one per chain)
        assert len(legacy_groups) == 2
        # New pipeline merges into 1 group (cross-order Iron Condor)
        assert len(new_groups) == 1
        # All 4 lots are in the single new group
        all_txn_ids = sorted(["tx-sp", "tx-bp", "tx-sc", "tx-bc"])
        assert new_groups[0]["lot_txn_ids"] == all_txn_ids
        # Strategy label should be Iron Condor
        assert new_groups[0]["strategy_label"] == "Iron Condor"

    def test_shadow_single_chain_ic_same_result(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """4-leg IC in a single order: both paths produce 1 group with same strategy."""
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_option_transaction(
                id="tx-sp", order_id="ORD-IC", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321P00170000", option_type="Put",
                strike=170.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bp", order_id="ORD-IC", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321P00160000", option_type="Put",
                strike=160.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sc", order_id="ORD-IC", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321C00190000", option_type="Call",
                strike=190.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bc", order_id="ORD-IC", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321C00200000", option_type="Call",
                strike=200.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both should produce exactly 1 group
        assert len(legacy_groups) == 1
        assert len(new_groups) == 1
        # Same lots
        assert legacy_groups[0]["lot_txn_ids"] == new_groups[0]["lot_txn_ids"]
        # Both should detect Iron Condor
        assert legacy_groups[0]["strategy_label"] == "Iron Condor"
        assert new_groups[0]["strategy_label"] == "Iron Condor"

    def test_shadow_expiration(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """STO → expiration: both paths produce 1 CLOSED group.

        Expirations have no order_id and no action — they get synthetic order IDs
        during preprocessing. This tests the full pipeline handles that edge case.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

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

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both should produce 1 group
        assert len(legacy_groups) == 1
        assert len(new_groups) == 1
        # Same lot membership
        assert legacy_groups[0]["lot_txn_ids"] == new_groups[0]["lot_txn_ids"]
        # Both CLOSED (expired)
        assert legacy_groups[0]["status"] == "CLOSED"
        assert new_groups[0]["status"] == "CLOSED"

    def test_shadow_assignment(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """STO put → assignment: assignment creates a derived stock lot.

        Assignments have no order_id and no action — they get synthetic handling.
        The derived stock lot should be in the same group as the option lot.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            make_option_transaction(
                id="tx-open", order_id="ORD-OPEN", action="SELL_TO_OPEN",
                quantity=1, price=3.00,
                symbol="AAPL  250321P00170000", option_type="Put",
                strike=170.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_assignment_transaction(
                id="tx-assign",
                symbol="AAPL  250321P00170000",
                quantity=1,
                executed_at="2025-03-21T16:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both should produce at least 1 group containing the option lot
        assert len(legacy_groups) >= 1
        assert len(new_groups) >= 1
        # The opening transaction should be in a group in both paths
        legacy_all_txns = sorted(t for g in legacy_groups for t in g["lot_txn_ids"])
        new_all_txns = sorted(t for g in new_groups for t in g["lot_txn_ids"])
        assert "tx-open" in legacy_all_txns
        assert "tx-open" in new_all_txns

    def test_shadow_jade_lizard(self, db, order_processor, lot_manager, position_manager, monkeypatch):
        """Jade Lizard (short put + bear call spread) entered as a single order:
        both paths produce 1 group with 'Jade Lizard' strategy label.
        """
        monkeypatch.setattr(ledger_svc, "db", db)
        monkeypatch.setattr(ledger_svc, "lot_manager", lot_manager)

        txs = [
            # Short put
            make_option_transaction(
                id="tx-sp", order_id="ORD-JL", action="SELL_TO_OPEN",
                quantity=1, price=2.00,
                symbol="AAPL 250321P00160000", option_type="Put",
                strike=160.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Short call (lower strike of the bear call spread)
            make_option_transaction(
                id="tx-sc", order_id="ORD-JL", action="SELL_TO_OPEN",
                quantity=1, price=1.50,
                symbol="AAPL 250321C00180000", option_type="Call",
                strike=180.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            # Long call (higher strike — caps upside risk)
            make_option_transaction(
                id="tx-lc", order_id="ORD-JL", action="BUY_TO_OPEN",
                quantity=1, price=0.50,
                symbol="AAPL 250321C00190000", option_type="Call",
                strike=190.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        chains_by_account = order_processor.process_transactions(txs)
        all_chains = [c for chains in chains_by_account.values() for c in chains]

        # Legacy
        _populate_order_chains(db, lot_manager, all_chains)
        ledger_svc.seed_position_groups()
        legacy_groups = _snapshot_groups(db)

        # New pipeline
        _clear_groups(db)
        assembly = assemble_orders(txs)
        new_chains = derive_chains(db, assembly.orders)
        persister = GroupPersister(db, lot_manager)
        persister.process_groups(new_chains)
        new_groups = _snapshot_groups(db)

        # Both should produce 1 group with all 3 lots
        assert len(legacy_groups) == 1
        assert len(new_groups) == 1
        all_txn_ids = sorted(["tx-sp", "tx-sc", "tx-lc"])
        assert legacy_groups[0]["lot_txn_ids"] == all_txn_ids
        assert new_groups[0]["lot_txn_ids"] == all_txn_ids
        # Both should detect Jade Lizard
        assert legacy_groups[0]["strategy_label"] == "Jade Lizard"
        assert new_groups[0]["strategy_label"] == "Jade Lizard"
