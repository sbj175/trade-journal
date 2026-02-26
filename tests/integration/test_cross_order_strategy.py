"""
Integration test: cross-order strategy evolution through the full pipeline.

Verifies that the strategy engine correctly detects strategy label changes as
orders are added across separate transactions:
  1. Bull Put Spread (single order, 2 legs)
  2. Iron Condor (two separate orders merged by same expiration)
  3. Back to Bull Put Spread (after closing one wing)

Uses the real pipeline via ``reprocess()`` from ``src.pipeline.orchestrator``.
"""

import pytest
from unittest.mock import patch

from src.database.models import PositionGroup, PositionGroupLot, PositionLot
from src.pipeline.orchestrator import reprocess
from tests.conftest import make_option_transaction


# ── Constants ──────────────────────────────────────────────────────────────

ACCOUNT = "TESTACCT"
UNDERLYING = "ZTEST"
EXPIRATION = "2026-09-18"


# ── Transaction factories ─────────────────────────────────────────────────

def _bull_put_spread_txns():
    """Short $50 put + long $45 put → Bull Put Spread (credit)."""
    return [
        make_option_transaction(
            id="tx-bps-short",
            account_number=ACCOUNT,
            order_id="ORD-BPS-001",
            symbol="ZTEST  260918P00050000",
            underlying_symbol=UNDERLYING,
            action="SELL_TO_OPEN",
            quantity=1,
            price=2.00,
            executed_at="2026-06-01T10:00:00+00:00",
            option_type="Put",
            strike=50.0,
            expiration=EXPIRATION,
            transaction_sub_type="Sell to Open",
            description="Sold 1 ZTEST 09/18/26 Put 50.00",
        ),
        make_option_transaction(
            id="tx-bps-long",
            account_number=ACCOUNT,
            order_id="ORD-BPS-001",
            symbol="ZTEST  260918P00045000",
            underlying_symbol=UNDERLYING,
            action="BUY_TO_OPEN",
            quantity=1,
            price=1.00,
            executed_at="2026-06-01T10:00:00+00:00",
            option_type="Put",
            strike=45.0,
            expiration=EXPIRATION,
            transaction_sub_type="Buy to Open",
            description="Bought 1 ZTEST 09/18/26 Put 45.00",
        ),
    ]


def _bear_call_spread_txns():
    """Short $55 call + long $60 call → Bear Call Spread (credit)."""
    return [
        make_option_transaction(
            id="tx-bcs-short",
            account_number=ACCOUNT,
            order_id="ORD-BCS-001",
            symbol="ZTEST  260918C00055000",
            underlying_symbol=UNDERLYING,
            action="SELL_TO_OPEN",
            quantity=1,
            price=2.00,
            executed_at="2026-06-02T10:00:00+00:00",
            option_type="Call",
            strike=55.0,
            expiration=EXPIRATION,
            transaction_sub_type="Sell to Open",
            description="Sold 1 ZTEST 09/18/26 Call 55.00",
        ),
        make_option_transaction(
            id="tx-bcs-long",
            account_number=ACCOUNT,
            order_id="ORD-BCS-001",
            symbol="ZTEST  260918C00060000",
            underlying_symbol=UNDERLYING,
            action="BUY_TO_OPEN",
            quantity=1,
            price=1.00,
            executed_at="2026-06-02T10:00:00+00:00",
            option_type="Call",
            strike=60.0,
            expiration=EXPIRATION,
            transaction_sub_type="Buy to Open",
            description="Bought 1 ZTEST 09/18/26 Call 60.00",
        ),
    ]


def _close_call_wing_txns():
    """BTC short call + STC long call → close the Bear Call Spread wing."""
    return [
        make_option_transaction(
            id="tx-close-call-short",
            account_number=ACCOUNT,
            order_id="ORD-CLOSE-001",
            symbol="ZTEST  260918C00055000",
            underlying_symbol=UNDERLYING,
            action="BUY_TO_CLOSE",
            quantity=1,
            price=1.50,
            executed_at="2026-07-01T10:00:00+00:00",
            option_type="Call",
            strike=55.0,
            expiration=EXPIRATION,
            transaction_sub_type="Buy to Close",
            description="Bought 1 ZTEST 09/18/26 Call 55.00",
        ),
        make_option_transaction(
            id="tx-close-call-long",
            account_number=ACCOUNT,
            order_id="ORD-CLOSE-001",
            symbol="ZTEST  260918C00060000",
            underlying_symbol=UNDERLYING,
            action="SELL_TO_CLOSE",
            quantity=1,
            price=0.50,
            executed_at="2026-07-01T10:00:00+00:00",
            option_type="Call",
            strike=60.0,
            expiration=EXPIRATION,
            transaction_sub_type="Sell to Close",
            description="Sold 1 ZTEST 09/18/26 Call 60.00",
        ),
    ]


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_ztest_groups(db_manager):
    """Return list of (group_id, strategy_label, status) for ZTEST groups."""
    with db_manager.get_session() as session:
        groups = session.query(PositionGroup).filter(
            PositionGroup.underlying == UNDERLYING,
        ).all()
        return [(g.group_id, g.strategy_label, g.status) for g in groups]


def _get_group_lot_count(db_manager, group_id):
    """Return the number of lots linked to a group."""
    with db_manager.get_session() as session:
        return session.query(PositionGroupLot).filter(
            PositionGroupLot.group_id == group_id,
        ).count()


def _get_lot_statuses(db_manager):
    """Return dict of {transaction_id: status} for all ZTEST lots."""
    with db_manager.get_session() as session:
        rows = session.query(
            PositionLot.transaction_id, PositionLot.status,
        ).filter(
            PositionLot.underlying == UNDERLYING,
        ).all()
        return {r[0]: r[1] for r in rows}


# ── Tests ──────────────────────────────────────────────────────────────────

@patch("src.pipeline.orchestrator.net_opposing_equity_lots", return_value=0)
class TestCrossOrderStrategyEvolution:
    """End-to-end: strategy label evolves as orders are added/closed."""

    def test_bull_put_spread_detected(self, _mock_net, db, lot_manager):
        """Single order with short put + long put → Bull Put Spread."""
        txs = _bull_put_spread_txns()
        result = reprocess(db, lot_manager, txs, {UNDERLYING})

        assert result.groups_processed == 1
        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        _, label, status = groups[0]
        assert label == "Bull Put Spread"
        assert status == "OPEN"

    def test_iron_condor_after_adding_call_wing(self, _mock_net, db, lot_manager):
        """Bull Put Spread + Bear Call Spread (same expiry) → Iron Condor."""
        bps = _bull_put_spread_txns()

        # First: just the bull put spread
        reprocess(db, lot_manager, bps, {UNDERLYING})

        # Second: add bear call spread, reprocess all transactions
        all_txs = bps + _bear_call_spread_txns()
        result = reprocess(db, lot_manager, all_txs, {UNDERLYING})

        assert result.groups_processed == 1
        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        _, label, status = groups[0]
        assert label == "Iron Condor"
        assert status == "OPEN"

    def test_back_to_spread_after_closing_wing(self, _mock_net, db, lot_manager):
        """Iron Condor → close call wing → Bull Put Spread remains."""
        bps = _bull_put_spread_txns()
        bcs = _bear_call_spread_txns()
        close = _close_call_wing_txns()

        # Build up to Iron Condor
        all_open = bps + bcs
        reprocess(db, lot_manager, all_open, {UNDERLYING})

        # Close the call wing and reprocess
        all_txs = all_open + close
        result = reprocess(db, lot_manager, all_txs, {UNDERLYING})

        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        _, label, status = groups[0]
        assert label == "Bull Put Spread"
        assert status == "OPEN"

    def test_lot_count_progression(self, _mock_net, db, lot_manager):
        """2 lots (spread) → 4 lots (condor) → 4 lots (2 open + 2 closed)."""
        bps = _bull_put_spread_txns()
        bcs = _bear_call_spread_txns()
        close = _close_call_wing_txns()

        # Step 1: Bull Put Spread → 2 lots in 1 group
        reprocess(db, lot_manager, bps, {UNDERLYING})
        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        group_id = groups[0][0]
        assert _get_group_lot_count(db, group_id) == 2

        # Step 2: Iron Condor → 4 lots in 1 group
        reprocess(db, lot_manager, bps + bcs, {UNDERLYING})
        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        group_id = groups[0][0]
        assert _get_group_lot_count(db, group_id) == 4

        # Step 3: Close call wing → still 4 lots (2 open, 2 closed)
        reprocess(db, lot_manager, bps + bcs + close, {UNDERLYING})
        groups = _get_ztest_groups(db)
        assert len(groups) == 1
        group_id = groups[0][0]
        assert _get_group_lot_count(db, group_id) == 4

        lot_statuses = _get_lot_statuses(db)
        assert sum(1 for s in lot_statuses.values() if s == "OPEN") == 2
        assert sum(1 for s in lot_statuses.values() if s == "CLOSED") == 2

    def test_fully_closed_splits_into_wing_groups(self, _mock_net, db, lot_manager):
        """Closing all legs from scratch → 2 CLOSED groups (one per wing).

        When all lots are closed, the group manager won't merge into an
        already-closed group.  Each wing becomes its own CLOSED group with
        the correct spread label.  (Future: strategy_history will preserve
        the Iron Condor label for historical reporting.)
        """
        bps = _bull_put_spread_txns()
        bcs = _bear_call_spread_txns()
        close_calls = _close_call_wing_txns()

        close_puts = [
            make_option_transaction(
                id="tx-close-put-short",
                account_number=ACCOUNT,
                order_id="ORD-CLOSE-002",
                symbol="ZTEST  260918P00050000",
                underlying_symbol=UNDERLYING,
                action="BUY_TO_CLOSE",
                quantity=1,
                price=0.50,
                executed_at="2026-07-02T10:00:00+00:00",
                option_type="Put",
                strike=50.0,
                expiration=EXPIRATION,
                transaction_sub_type="Buy to Close",
                description="Bought 1 ZTEST 09/18/26 Put 50.00",
            ),
            make_option_transaction(
                id="tx-close-put-long",
                account_number=ACCOUNT,
                order_id="ORD-CLOSE-002",
                symbol="ZTEST  260918P00045000",
                underlying_symbol=UNDERLYING,
                action="SELL_TO_CLOSE",
                quantity=1,
                price=0.20,
                executed_at="2026-07-02T10:00:00+00:00",
                option_type="Put",
                strike=45.0,
                expiration=EXPIRATION,
                transaction_sub_type="Sell to Close",
                description="Sold 1 ZTEST 09/18/26 Put 45.00",
            ),
        ]

        all_txs = bps + bcs + close_calls + close_puts
        result = reprocess(db, lot_manager, all_txs, {UNDERLYING})

        groups = _get_ztest_groups(db)
        assert len(groups) == 2
        labels = sorted(g[1] for g in groups)
        assert labels == ["Bear Call Spread", "Bull Put Spread"]
        assert all(g[2] == "CLOSED" for g in groups)
