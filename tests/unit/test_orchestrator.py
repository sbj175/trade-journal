"""
Integration tests for the Pipeline Orchestrator (OPT-121).

All tests use a real temporary SQLite database via conftest fixtures.
"""

import pytest
from datetime import datetime

from src.pipeline.orchestrator import reprocess, PipelineResult
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
        """Single STO option -> lot created, group created."""
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
        assert result.groups_processed >= 1
        assert _count_lots(db) >= 1

    def test_open_close(self, db, lot_manager):
        """STO + BTC -> lots + closings, group CLOSED."""

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
        """No transactions -> PipelineResult with zeros."""
        result = reprocess(db, lot_manager, [])

        assert result == PipelineResult(
            orders_assembled=0,
            groups_processed=0,
            equity_lots_netted=0,
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
        assert result.groups_processed >= 1
        # equity_lots_netted may be 0 for option-only scenarios
        assert result.equity_lots_netted >= 0

    def test_dataclass_equality(self):
        """PipelineResult supports equality for test assertions."""
        r1 = PipelineResult(orders_assembled=5, groups_processed=2, equity_lots_netted=1)
        r2 = PipelineResult(orders_assembled=5, groups_processed=2, equity_lots_netted=1)
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


# =====================================================================
# Multi-chain rolling order — parallel ladder rung preservation
# =====================================================================

class TestParallelLadderRollPreservation:
    """When one ROLLING order rolls multiple parallel positions (e.g. a
    covered-call ladder where several rungs at the same strike are rolled
    in a single broker order), each new opening lot must inherit its
    own predecessor's chain_id.

    Regression for the same-direction multi-leg pairing gap left by
    OPT-262: when all closes share an (option_type, direction) signature
    with all opens, the splitter keeps the order intact, but
    position_ledger then collapses every new lot onto whichever chain
    it pulls first from `affected_chains` — silently merging parallel
    ladder rungs into a single chain.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known: position_ledger.py uses next(iter(affected_chains)) for "
            "ROLLING orders, collapsing parallel chains onto one arbitrary "
            "chain_id. Will pass once the chain-pairing fix lands. Tracked "
            "under OPT-272 (Tier 1 coverage backfill)."
        ),
    )
    def test_three_parallel_rungs_roll_preserves_three_chains(self, db, lot_manager):
        SYM_OLD = "AAPL  250321C00170000"
        SYM_NEW = "AAPL  250418C00175000"

        # Day 1: open three parallel rungs, each with its own order_id
        # (so position_ledger assigns three distinct chain_ids).
        opens = [
            make_option_transaction(
                id=f"tx-open-{rung}", order_id=f"OPEN_{rung}",
                action="SELL_TO_OPEN", quantity=1, price=2.50,
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            )
            for rung in ("A", "B", "C")
        ]

        # Day 2: roll all three rungs in a SINGLE broker order. Three BTC
        # transactions (one per rung) and three STO transactions at the new
        # strike, all sharing one order_id — the parallel-ladder roll shape.
        # Slight price differences across fills mirror real broker data and
        # prevent normalize_transactions() from aggregating same-price fills.
        ROLL_ORDER_ID = "ROLL_3X"
        close_prices = [1.00, 1.01, 1.02]
        open_prices = [3.00, 3.01, 3.02]
        roll = []
        for i, rung in enumerate(("A", "B", "C")):
            roll.append(make_option_transaction(
                id=f"tx-btc-{rung}", order_id=ROLL_ORDER_ID,
                action="BUY_TO_CLOSE", quantity=1, price=close_prices[i],
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ))
            roll.append(make_option_transaction(
                id=f"tx-sto-{rung}", order_id=ROLL_ORDER_ID,
                action="SELL_TO_OPEN", quantity=1, price=open_prices[i],
                symbol=SYM_NEW, option_type="Call", strike=175.0,
                expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ))

        reprocess(db, lot_manager, opens + roll)

        with db.get_session() as session:
            opening_chains = {
                row.chain_id for row in session.query(PositionLot).filter(
                    PositionLot.symbol == SYM_OLD,
                ).all()
            }
            new_chains = [
                row.chain_id for row in session.query(PositionLot).filter(
                    PositionLot.symbol == SYM_NEW,
                ).all()
            ]

        # Three distinct chains were opened on Day 1.
        assert len(opening_chains) == 3, (
            f"Expected 3 distinct opening chains, got {opening_chains}"
        )

        # Three new lots were opened by the roll.
        assert len(new_chains) == 3, (
            f"Expected 3 new lots from the rolling order, got {len(new_chains)}"
        )

        # Each new lot must inherit one of the three original chains, and
        # all three originals must be represented exactly once. This is the
        # invariant that fails today: position_ledger picks
        # `next(iter(affected_chains))` and assigns the same chain to every
        # new lot, collapsing the ladder.
        assert set(new_chains) == opening_chains, (
            f"Parallel ladder chains collapsed during roll. "
            f"Expected new lots on chains {opening_chains}, got {set(new_chains)}"
        )
        assert len(set(new_chains)) == 3, (
            f"Expected each new lot on a distinct chain, "
            f"got duplicates: {new_chains}"
        )

    def test_put_spread_roll_preserves_chain_on_both_legs(self, db, lot_manager):
        """OPT-262 regression: rolling a put spread in one broker order keeps
        both legs on the original chain.

        Pre-OPT-262, the splitter assumed every roll had exactly one closing
        leg — for a 2-leg spread roll it would pair the first close with the
        closest-strike open and orphan the remaining close+open pair onto a
        synthetic _split OPENING order with a brand-new chain_id. Half the
        spread lost its history every time you rolled it.

        OPT-262 fixed this by detecting multi-leg rolls (signatures mirror
        each other) and keeping the order intact as a single ROLLING order.
        Both new lots then inherit the original chain.

        This test pins that behavior. Tracked under OPT-272.
        """
        # Day 1: open a put spread (long 45P + short 50P) in one order.
        # Both legs share the same order_id, so they share chain_id.
        opens = [
            make_option_transaction(
                id="tx-bto-45p", order_id="OPEN_PS",
                action="BUY_TO_OPEN", quantity=1, price=0.50,
                symbol="AAPL  250321P00045000", option_type="Put",
                strike=45.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-50p", order_id="OPEN_PS",
                action="SELL_TO_OPEN", quantity=1, price=2.00,
                symbol="AAPL  250321P00050000", option_type="Put",
                strike=50.0, expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]

        # Day 2: roll the spread to 40/45 in one order.
        # 2 closes (long 45 + short 50) + 2 opens (long 40 + short 45).
        roll = [
            make_option_transaction(
                id="tx-stc-45p", order_id="ROLL_PS",
                action="SELL_TO_CLOSE", quantity=1, price=0.30,
                symbol="AAPL  250321P00045000", option_type="Put",
                strike=45.0, expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-btc-50p", order_id="ROLL_PS",
                action="BUY_TO_CLOSE", quantity=1, price=1.50,
                symbol="AAPL  250321P00050000", option_type="Put",
                strike=50.0, expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-bto-40p", order_id="ROLL_PS",
                action="BUY_TO_OPEN", quantity=1, price=0.40,
                symbol="AAPL  250418P00040000", option_type="Put",
                strike=40.0, expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-45p-new", order_id="ROLL_PS",
                action="SELL_TO_OPEN", quantity=1, price=1.80,
                symbol="AAPL  250418P00045000", option_type="Put",
                strike=45.0, expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
        ]

        reprocess(db, lot_manager, opens + roll)

        with db.get_session() as session:
            day1_chains = {
                row.chain_id for row in session.query(PositionLot).filter(
                    PositionLot.entry_date < "2025-03-15",
                ).all()
            }
            day2_chains = {
                row.chain_id for row in session.query(PositionLot).filter(
                    PositionLot.entry_date >= "2025-03-15",
                ).all()
            }

        # Day 1 opened both legs of the spread under one order — they must
        # share a single chain_id.
        assert len(day1_chains) == 1, (
            f"Day 1 spread should have one chain, got {day1_chains}"
        )

        # Day 2 must produce two new lots, both on Day 1's chain. The
        # pre-OPT-262 bug was that one leg landed on a fresh "_split" chain
        # while the other inherited the original.
        assert day2_chains == day1_chains, (
            f"Put-spread roll orphaned a leg onto a new chain. "
            f"Day 1 chains: {day1_chains}; Day 2 chains: {day2_chains}"
        )
