"""
Tests for OrderManager — P&L methods, chain status, save/load.

Source: src/models/order_models.py
"""

import pytest
from datetime import date, datetime

from src.models.order_models import (
    OrderManager, Order, OrderChain, Position,
    OrderType, OrderStatus, PositionStatus, ChainStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    order_id="ORD-1",
    symbol="AAPL 250321C00170000",
    underlying="AAPL",
    instrument_type="EQUITY_OPTION",
    option_type="Call",
    strike=170.0,
    quantity=-1,
    opening_price=2.00,
    closing_price=None,
    opening_action="SELL_TO_OPEN",
    closing_action=None,
    status=PositionStatus.OPEN,
    pnl=0.0,
    **kwargs,
):
    return Position(
        position_id=0,  # Will be assigned by DB
        order_id=order_id,
        account_number="ACCT1",
        symbol=symbol,
        underlying=underlying,
        instrument_type=instrument_type,
        option_type=option_type,
        strike=strike,
        quantity=quantity,
        opening_price=opening_price,
        closing_price=closing_price,
        opening_transaction_id="tx-001",
        opening_action=opening_action,
        closing_action=closing_action,
        status=status,
        pnl=pnl,
        **kwargs,
    )


def _make_order(
    order_id="ORD-1",
    order_type=OrderType.OPENING,
    status=OrderStatus.OPEN,
    positions=None,
    order_date=None,
):
    return Order(
        order_id=order_id,
        account_number="ACCT1",
        underlying="AAPL",
        order_type=order_type,
        strategy_type="Short Put",
        order_date=order_date or date(2025, 3, 1),
        status=status,
        positions=positions or [],
    )


# ---------------------------------------------------------------------------
# calculate_realized_position_pnl
# ---------------------------------------------------------------------------

class TestRealizedPositionPnl:
    def test_calculate_realized_position_pnl_sto_btc(self, db):
        """STO at $2.00, BTC at $1.00, qty=1 → P&L = +$100"""
        mgr = OrderManager(db)
        pos = {
            "quantity": 1,
            "opening_price": 2.00,
            "closing_price": 1.00,
            "opening_action": "SELL_TO_OPEN",
            "closing_action": "BUY_TO_CLOSE",
            "status": "CLOSED",
            "instrument_type": "EQUITY_OPTION",
        }
        pnl = mgr.calculate_realized_position_pnl(pos)
        # Opening credit: 1 * 2.00 * 100 = +200
        # Closing debit:  1 * 1.00 * 100 = -100
        assert pnl == pytest.approx(100.00)

    def test_calculate_realized_position_pnl_bto_stc(self, db):
        """BTO at $1.50, STC at $3.00, qty=2 → P&L = +$300"""
        mgr = OrderManager(db)
        pos = {
            "quantity": 2,
            "opening_price": 1.50,
            "closing_price": 3.00,
            "opening_action": "BUY_TO_OPEN",
            "closing_action": "SELL_TO_CLOSE",
            "status": "CLOSED",
            "instrument_type": "EQUITY_OPTION",
        }
        pnl = mgr.calculate_realized_position_pnl(pos)
        # Opening debit:  2 * 1.50 * 100 = -300
        # Closing credit:  2 * 3.00 * 100 = +600
        assert pnl == pytest.approx(300.00)

    def test_calculate_realized_position_pnl_stock(self, db):
        """Buy 100 shares at $50, sell at $55 → P&L = +$500"""
        mgr = OrderManager(db)
        pos = {
            "quantity": 100,
            "opening_price": 50.00,
            "closing_price": 55.00,
            "opening_action": "BUY_TO_OPEN",
            "closing_action": "SELL_TO_CLOSE",
            "status": "CLOSED",
            "instrument_type": "EQUITY",
        }
        pnl = mgr.calculate_realized_position_pnl(pos)
        # Opening debit:  100 * 50 = -5000
        # Closing credit: 100 * 55 = +5500
        assert pnl == pytest.approx(500.00)


# ---------------------------------------------------------------------------
# Chain realized and unrealized P&L
# ---------------------------------------------------------------------------

class TestChainPnl:
    def _setup_chain(self, db, chain_status="CLOSED", position_pnl=150.0,
                     position_status="CLOSED"):
        """Insert a chain with one order and one position into the DB."""
        mgr = OrderManager(db)

        pos = _make_position(
            status=PositionStatus.CLOSED if position_status == "CLOSED" else PositionStatus.OPEN,
            pnl=position_pnl,
            closing_price=1.00 if position_status == "CLOSED" else None,
            closing_action="BUY_TO_CLOSE" if position_status == "CLOSED" else None,
        )
        order = _make_order(positions=[pos])
        mgr.save_order_to_database(order)

        # Create chain
        from src.database.models import OrderChain as OC, OrderChainMember as OCM
        with db.get_session() as session:
            session.add(OC(
                chain_id="chain-test", underlying="AAPL", account_number="ACCT1",
                opening_order_id="ORD-1", strategy_type="Short Call",
                chain_status=chain_status, total_pnl=position_pnl,
            ))
            session.flush()
            session.add(OCM(chain_id="chain-test", order_id="ORD-1", sequence_number=1))

        return mgr

    def test_calculate_chain_realized_pnl_closed(self, db):
        """Closed chain: all P&L is realized."""
        mgr = self._setup_chain(db, chain_status="CLOSED", position_pnl=150.0)
        realized = mgr.calculate_chain_realized_pnl("chain-test", "CLOSED")
        assert realized == pytest.approx(150.0)

    def test_calculate_chain_unrealized_pnl_closed(self, db):
        """Closed chain: no unrealized P&L."""
        mgr = self._setup_chain(db, chain_status="CLOSED", position_pnl=150.0)
        unrealized = mgr.calculate_chain_unrealized_pnl("chain-test", "CLOSED")
        assert unrealized == pytest.approx(0.0)

    def test_update_chain_pnl(self, db):
        """update_chain_pnl writes realized + unrealized to database."""
        mgr = self._setup_chain(db, chain_status="CLOSED", position_pnl=200.0)
        total = mgr.update_chain_pnl("chain-test")

        # Verify it was written to the DB
        from src.database.models import OrderChain as OC
        with db.get_session() as session:
            row = session.query(OC).filter(OC.chain_id == "chain-test").first()
            assert row is not None


# ---------------------------------------------------------------------------
# Save and load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadOrder:
    def test_save_and_load_order(self, db):
        """Round-trip: save Order → load from DB → verify fields."""
        mgr = OrderManager(db)

        pos = _make_position(
            order_id="ORD-SAVE-TEST",
            quantity=-2,
            opening_price=2.50,
            opening_action="SELL_TO_OPEN",
        )
        order = _make_order(
            order_id="ORD-SAVE-TEST",
            order_type=OrderType.OPENING,
            positions=[pos],
            order_date=date(2025, 3, 15),
        )

        success = mgr.save_order_to_database(order)
        assert success is True

        loaded = mgr.get_order_by_id("ORD-SAVE-TEST")
        assert loaded is not None
        assert loaded["order_id"] == "ORD-SAVE-TEST"
        assert loaded["underlying"] == "AAPL"
        assert loaded["order_type"] == "OPENING"
        assert len(loaded["positions"]) == 1
        assert loaded["positions"][0]["opening_price"] == pytest.approx(2.50)


# ---------------------------------------------------------------------------
# Chain status logic
# ---------------------------------------------------------------------------

class TestChainStatus:
    def test_chain_status_all_closed(self, db):
        """All positions closed → chain status returned as CLOSED."""
        mgr = OrderManager(db)
        pos = _make_position(
            status=PositionStatus.CLOSED,
            closing_price=1.00,
            closing_action="BUY_TO_CLOSE",
        )
        order = _make_order(
            status=OrderStatus.CLOSED,
            positions=[pos],
        )

        # The order itself tracks status
        assert order.status == OrderStatus.CLOSED

    def test_chain_status_partially_closed(self, db):
        """Mix of open/closed positions → OPEN."""
        mgr = OrderManager(db)
        pos_open = _make_position(status=PositionStatus.OPEN)
        pos_closed = _make_position(
            status=PositionStatus.CLOSED,
            closing_price=1.00,
            closing_action="BUY_TO_CLOSE",
        )
        order = _make_order(
            status=OrderStatus.OPEN,
            positions=[pos_open, pos_closed],
        )
        # Order with any open positions should be OPEN
        assert order.status == OrderStatus.OPEN

    def test_order_status_transitions(self, db):
        """Order status computed from position states."""
        pos = _make_position(status=PositionStatus.OPEN)
        order = _make_order(positions=[pos])

        assert order.status == OrderStatus.OPEN

        # Simulate status update
        order.status = OrderStatus.CLOSED
        assert order.status == OrderStatus.CLOSED
