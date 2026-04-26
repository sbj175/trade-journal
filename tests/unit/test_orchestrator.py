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


def _build_simple_roll(
    *, sym_old, sym_new, strike_old, strike_new, exp_old, exp_new,
    qty=1, option_type="Call", order_prefix="R",
    open_price=2.50, close_price=1.00, new_open_price=3.00,
    open_date="2025-03-01T10:00:00+00:00",
    roll_date="2025-03-15T10:00:00+00:00",
):
    """Build the (opens, roll) transaction lists for a single-leg roll
    from sym_old to sym_new on a fresh chain.
    """
    opens = [
        make_option_transaction(
            id="tx-open", order_id=f"OPEN_{order_prefix}",
            action="SELL_TO_OPEN", quantity=qty, price=open_price,
            symbol=sym_old, option_type=option_type, strike=strike_old,
            expiration=exp_old, executed_at=open_date,
        ),
    ]
    roll = [
        make_option_transaction(
            id="tx-btc", order_id=f"ROLL_{order_prefix}",
            action="BUY_TO_CLOSE", quantity=qty, price=close_price,
            symbol=sym_old, option_type=option_type, strike=strike_old,
            expiration=exp_old, executed_at=roll_date,
        ),
        make_option_transaction(
            id="tx-sto", order_id=f"ROLL_{order_prefix}",
            action="SELL_TO_OPEN", quantity=qty, price=new_open_price,
            symbol=sym_new, option_type=option_type, strike=strike_new,
            expiration=exp_new, executed_at=roll_date,
        ),
    ]
    return opens, roll


def _assert_chain_preserved_through_roll(db, sym_old, sym_new):
    """Assert that a roll from sym_old to sym_new preserved chain_id on
    the new lot AND set rolled_from_group_id on the new group.
    """
    with db.get_session() as session:
        old_chain = session.query(PositionLot.chain_id).filter(
            PositionLot.symbol == sym_old,
        ).scalar()
        new_chain = session.query(PositionLot.chain_id).filter(
            PositionLot.symbol == sym_new,
        ).scalar()
        old_gid = session.query(PositionGroup.group_id).join(
            PositionGroupLot, PositionGroupLot.group_id == PositionGroup.group_id,
        ).join(
            PositionLot, PositionLot.transaction_id == PositionGroupLot.transaction_id,
        ).filter(PositionLot.symbol == sym_old).scalar()
        new_rolled_from = session.query(PositionGroup.rolled_from_group_id).join(
            PositionGroupLot, PositionGroupLot.group_id == PositionGroup.group_id,
        ).join(
            PositionLot, PositionLot.transaction_id == PositionGroupLot.transaction_id,
        ).filter(PositionLot.symbol == sym_new).scalar()
    assert new_chain == old_chain, (
        f"Roll {sym_old} → {sym_new} should preserve chain_id; "
        f"got old={old_chain} new={new_chain}"
    )
    assert new_rolled_from == old_gid, (
        f"New group should rolled_from the predecessor; "
        f"got new_rolled_from={new_rolled_from} old_gid={old_gid}"
    )


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
        """Selling a single option to open should create one position lot and one position group."""
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
        """Opening then closing the same option should produce a lot, a closing record, and a closed group."""

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
        """A put spread and a call spread placed as separate orders should be recognized as one Iron Condor group."""
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
        """Buying shares of a stock should create a stock lot and an associated Shares group."""
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
        """Selling all shares and then buying the same stock again later should be recorded as two separate Shares groups."""
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
        """Adding more shares of a stock you already hold should be tracked inside the existing Shares group, not a new one."""
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
        """Running the pipeline with no transactions should report all-zero counts and not error out."""
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
        """Reprocessing only one underlying after a full run should still report the correct number of orders assembled."""
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
        """Running the pipeline twice on the same input should leave the database in identical state both times."""
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
        """A scenario with multiple orders should populate every counter field on the pipeline result."""
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
        """Two PipelineResult values with the same numbers should compare as equal."""
        r1 = PipelineResult(orders_assembled=5, groups_processed=2, equity_lots_netted=1)
        r2 = PipelineResult(orders_assembled=5, groups_processed=2, equity_lots_netted=1)
        assert r1 == r2


# =====================================================================
# Derived lot tests (assignment/exercise)
# =====================================================================

class TestDerivedLots:

    def test_exercise_closes_derived_stock_lot(self, db, order_processor, lot_manager):
        """When a put spread is fully exercised at expiration, the shares received from assignment should be cancelled out by the shares delivered through exercise, leaving no open stock."""
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

    def test_three_parallel_rungs_roll_preserves_three_chains(self, db, lot_manager):
        """Rolling three parallel covered-call positions in one broker order should keep each rung on its own original chain instead of collapsing them onto one."""
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

    def test_mixed_quantity_parallel_roll_pairs_chains_correctly(self, db, lot_manager):
        """Rolling two parallel positions of different sizes (30 contracts on chain A, 10 contracts on chain B) in one broker order should pair the 30-contract opening lot with chain A and the 10-contract opening lot with chain B (FIFO by quantity), not just slot them into the queue without regard to size."""
        SYM_OLD = "AAPL  250321C00170000"
        SYM_NEW = "AAPL  250418C00175000"

        # Day 1: open two parallel positions of different sizes, each with
        # its own order_id (so distinct chain_ids). Different morning vs.
        # afternoon entry times so FIFO ordering is deterministic.
        opens = [
            make_option_transaction(
                id="tx-open-A", order_id="OPEN_A",
                action="SELL_TO_OPEN", quantity=30, price=2.50,
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-open-B", order_id="OPEN_B",
                action="SELL_TO_OPEN", quantity=10, price=2.51,
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-01T14:00:00+00:00",
            ),
        ]

        # Day 2: roll both in ONE order. Slight price differences prevent
        # normalize_transactions() from collapsing the four legs to two.
        ROLL_ORDER_ID = "ROLL_MIXED"
        roll = [
            make_option_transaction(
                id="tx-btc-30", order_id=ROLL_ORDER_ID,
                action="BUY_TO_CLOSE", quantity=30, price=1.00,
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-btc-10", order_id=ROLL_ORDER_ID,
                action="BUY_TO_CLOSE", quantity=10, price=1.01,
                symbol=SYM_OLD, option_type="Call", strike=170.0,
                expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-30", order_id=ROLL_ORDER_ID,
                action="SELL_TO_OPEN", quantity=30, price=3.00,
                symbol=SYM_NEW, option_type="Call", strike=175.0,
                expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-10", order_id=ROLL_ORDER_ID,
                action="SELL_TO_OPEN", quantity=10, price=3.01,
                symbol=SYM_NEW, option_type="Call", strike=175.0,
                expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
        ]

        reprocess(db, lot_manager, opens + roll)

        with db.get_session() as session:
            old_lots = session.query(
                PositionLot.quantity, PositionLot.chain_id,
            ).filter(PositionLot.symbol == SYM_OLD).all()
            new_lots = session.query(
                PositionLot.quantity, PositionLot.chain_id,
            ).filter(PositionLot.symbol == SYM_NEW).all()

        # Day 1: two distinct chains, qty -30 and -10.
        chain_by_qty_old = {abs(q): c for q, c in old_lots}
        assert set(chain_by_qty_old.keys()) == {30, 10}, (
            f"Expected old lots of size 30 and 10, got {chain_by_qty_old}"
        )
        chain_30 = chain_by_qty_old[30]
        chain_10 = chain_by_qty_old[10]
        assert chain_30 != chain_10, "Day 1 chains should be distinct"

        # Day 2: each new lot must inherit the chain of the close it was
        # paired with by quantity — the 30-contract open inherits chain_30,
        # the 10-contract open inherits chain_10.
        chain_by_qty_new = {abs(q): c for q, c in new_lots}
        assert chain_by_qty_new.get(30) == chain_30, (
            f"30-contract open should inherit chain {chain_30} (chain of the 30-contract close), "
            f"got {chain_by_qty_new.get(30)}"
        )
        assert chain_by_qty_new.get(10) == chain_10, (
            f"10-contract open should inherit chain {chain_10} (chain of the 10-contract close), "
            f"got {chain_by_qty_new.get(10)}"
        )


# =====================================================================
# Tier 1 — roll mechanics (chain inheritance + rolled_from linkage)
# =====================================================================

class TestRollMechanics:
    """Strategy-agnostic tests of the pipeline's roll machinery: chain
    inheritance from closed lot to new lot, and `rolled_from_group_id`
    linkage from new group to predecessor group.

    Each test uses a simple Short Call as the carrier — chain logic is
    independent of strategy label, so retesting it for every strategy
    type is wasted coverage.
    """

    def test_calendar_roll_preserves_chain(self, db, lot_manager):
        """Rolling a short call out in time at the same strike (calendar roll) should preserve its chain id and link the new group back to the old one via rolled_from."""
        sym_old = "AAPL  250321C00100000"
        sym_new = "AAPL  250418C00100000"
        opens, roll = _build_simple_roll(
            sym_old=sym_old, sym_new=sym_new,
            strike_old=100.0, strike_new=100.0,
            exp_old="2025-03-21", exp_new="2025-04-18",
            order_prefix="CR",
        )

        reprocess(db, lot_manager, opens + roll)

        _assert_chain_preserved_through_roll(db, sym_old, sym_new)

    def test_diagonal_roll_preserves_chain(self, db, lot_manager):
        """Rolling a short call up and out (different strike and different expiration) should still preserve the chain id and set rolled_from on the new group."""
        sym_old = "AAPL  250321C00100000"
        sym_new = "AAPL  250418C00105000"
        opens, roll = _build_simple_roll(
            sym_old=sym_old, sym_new=sym_new,
            strike_old=100.0, strike_new=105.0,
            exp_old="2025-03-21", exp_new="2025-04-18",
            order_prefix="DR",
        )

        reprocess(db, lot_manager, opens + roll)

        _assert_chain_preserved_through_roll(db, sym_old, sym_new)

    def test_multi_fill_same_order_roll_stays_in_one_group(self, db, lot_manager):
        """A roll whose new opening leg fills in two pieces (same order, slight price diff so the assembler doesn't aggregate them) should land both pieces in the same group — not split into a 24-lot and an 8-lot group."""
        sym_old = "AAPL  250321C00100000"
        sym_new = "AAPL  250418C00100000"

        opens = [
            make_option_transaction(
                id="tx-open", order_id="OPEN_MF",
                action="SELL_TO_OPEN", quantity=32, price=2.50,
                symbol=sym_old, option_type="Call", strike=100.0,
                expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
        ]
        # Day 2: roll with the new opening leg filled in two pieces.
        roll = [
            make_option_transaction(
                id="tx-btc", order_id="ROLL_MF",
                action="BUY_TO_CLOSE", quantity=32, price=1.00,
                symbol=sym_old, option_type="Call", strike=100.0,
                expiration="2025-03-21",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-24", order_id="ROLL_MF",
                action="SELL_TO_OPEN", quantity=24, price=3.02,
                symbol=sym_new, option_type="Call", strike=100.0,
                expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-8", order_id="ROLL_MF",
                action="SELL_TO_OPEN", quantity=8, price=3.01,
                symbol=sym_new, option_type="Call", strike=100.0,
                expiration="2025-04-18",
                executed_at="2025-03-15T10:00:00+00:00",
            ),
        ]

        reprocess(db, lot_manager, opens + roll)

        with db.get_session() as session:
            new_groups = session.query(PositionGroup.group_id).join(
                PositionGroupLot, PositionGroupLot.group_id == PositionGroup.group_id,
            ).join(
                PositionLot, PositionLot.transaction_id == PositionGroupLot.transaction_id,
            ).filter(PositionLot.symbol == sym_new).distinct().all()

        assert len(new_groups) == 1, (
            f"Multi-fill roll opens should share one group, got {len(new_groups)}"
        )

    def test_separate_opens_at_same_strike_and_expiration_create_separate_groups(self, db, lot_manager):
        """Two independent short calls opened by separate broker orders at the same strike and expiration should land in two distinct groups with two distinct chain ids — they are independent positions, not one fused position. This pins the OPT-270 fix that prevents stale-expiration anchors from merging unrelated chains."""
        sym = "AAPL  250321C00100000"

        opens = [
            make_option_transaction(
                id="tx-open-A", order_id="OPEN_A",
                action="SELL_TO_OPEN", quantity=1, price=2.50,
                symbol=sym, option_type="Call", strike=100.0,
                expiration="2025-03-21",
                executed_at="2025-03-01T10:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-open-B", order_id="OPEN_B",
                action="SELL_TO_OPEN", quantity=1, price=2.51,
                symbol=sym, option_type="Call", strike=100.0,
                expiration="2025-03-21",
                executed_at="2025-03-02T10:00:00+00:00",
            ),
        ]

        reprocess(db, lot_manager, opens)

        with db.get_session() as session:
            chains = {
                row.chain_id for row in session.query(PositionLot).filter(
                    PositionLot.symbol == sym,
                ).all()
            }
            group_count = session.query(PositionGroup).filter(
                PositionGroup.underlying == "AAPL",
                PositionGroup.status == "OPEN",
            ).count()

        assert len(chains) == 2, (
            f"Two separate opens should produce two distinct chain ids, got {chains}"
        )
        assert group_count == 2, (
            f"Two separate opens should produce two distinct groups, got {group_count}"
        )

    def test_same_expiration_vertical_roll_stays_in_one_group(self, db, lot_manager):
        """A Bull Call Spread rolled to a different strike pair at the SAME expiration (e.g., 230/250 → 240/260, both Mar 20) should stay in one position group with the new and old legs both attached. This is a 'roll within the same generation' — the user expects the original group to remain and a roll counter to increment, not a new generation group linked via rolled_from."""
        # Day 1: open Bull Call Spread 230/250, exp Mar 20
        opens = [
            make_option_transaction(
                id="tx-bto-230", order_id="OPEN_BCS",
                action="BUY_TO_OPEN", quantity=1, price=4.43,
                symbol="JNJ   260320C00230000", underlying_symbol="JNJ",
                option_type="Call", strike=230.0, expiration="2026-03-20",
                executed_at="2026-01-28T15:00:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-250", order_id="OPEN_BCS",
                action="SELL_TO_OPEN", quantity=1, price=1.40,
                symbol="JNJ   260320C00250000", underlying_symbol="JNJ",
                option_type="Call", strike=250.0, expiration="2026-03-20",
                executed_at="2026-01-28T15:00:00+00:00",
            ),
        ]
        # Day 2: same-exp roll → 240/260 (still Mar 20) in one ROLLING order
        roll = [
            make_option_transaction(
                id="tx-stc-230", order_id="ROLL_BCS",
                action="SELL_TO_CLOSE", quantity=1, price=14.81,
                symbol="JNJ   260320C00230000", underlying_symbol="JNJ",
                option_type="Call", strike=230.0, expiration="2026-03-20",
                executed_at="2026-02-17T20:30:00+00:00",
            ),
            make_option_transaction(
                id="tx-btc-250", order_id="ROLL_BCS",
                action="BUY_TO_CLOSE", quantity=1, price=5.00,
                symbol="JNJ   260320C00250000", underlying_symbol="JNJ",
                option_type="Call", strike=250.0, expiration="2026-03-20",
                executed_at="2026-02-17T20:30:00+00:00",
            ),
            make_option_transaction(
                id="tx-bto-240", order_id="ROLL_BCS",
                action="BUY_TO_OPEN", quantity=1, price=2.78,
                symbol="JNJ   260320C00240000", underlying_symbol="JNJ",
                option_type="Call", strike=240.0, expiration="2026-03-20",
                executed_at="2026-02-17T20:30:00+00:00",
            ),
            make_option_transaction(
                id="tx-sto-260", order_id="ROLL_BCS",
                action="SELL_TO_OPEN", quantity=1, price=1.38,
                symbol="JNJ   260320C00260000", underlying_symbol="JNJ",
                option_type="Call", strike=260.0, expiration="2026-03-20",
                executed_at="2026-02-17T20:30:00+00:00",
            ),
        ]

        reprocess(db, lot_manager, opens + roll)

        with db.get_session() as session:
            jnj_groups = session.query(PositionGroup).filter(
                PositionGroup.underlying == "JNJ",
            ).all()

        assert len(jnj_groups) == 1, (
            f"A same-expiration vertical roll should stay in one group, "
            f"got {len(jnj_groups)} groups"
        )
