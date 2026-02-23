"""
Tests for PositionInventoryManager — position state tracking, cost basis.

Source: src/models/position_inventory.py
"""

import pytest


def _make_tx(action, quantity, price, symbol="AAPL  250321C00170000",
             underlying="AAPL", instrument_type="EQUITY_OPTION",
             account_number="ACCT1", sub_type=""):
    return {
        "account_number": account_number,
        "symbol": symbol,
        "underlying_symbol": underlying,
        "action": action,
        "quantity": quantity,
        "price": price,
        "instrument_type": instrument_type,
        "transaction_sub_type": sub_type,
    }


# ---------------------------------------------------------------------------
# Position creation and updates
# ---------------------------------------------------------------------------

class TestPositionUpdates:
    def test_update_position_new(self, position_manager):
        """First fill creates a new inventory entry."""
        tx = _make_tx("BUY_TO_OPEN", 3, 1.50)
        pos = position_manager.update_position_from_transaction(tx)

        assert pos.current_quantity == 3
        assert pos.cost_basis == pytest.approx(1.50)
        assert pos.is_long is True

    def test_update_position_add(self, position_manager):
        """Second fill for same symbol adds to quantity, recalculates cost_basis."""
        tx1 = _make_tx("BUY_TO_OPEN", 3, 1.00)
        position_manager.update_position_from_transaction(tx1)

        tx2 = _make_tx("BUY_TO_OPEN", 2, 1.50)
        position_manager.update_position_from_transaction(tx2)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.current_quantity == 5

    def test_update_position_close(self, position_manager):
        """Closing fill reduces quantity to 0."""
        tx_open = _make_tx("BUY_TO_OPEN", 3, 1.50)
        position_manager.update_position_from_transaction(tx_open)

        tx_close = _make_tx("SELL_TO_CLOSE", 3, 2.00)
        position_manager.update_position_from_transaction(tx_close)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.current_quantity == 0
        assert pos.is_closed is True

    def test_update_position_partial_close(self, position_manager):
        """Partial close adjusts quantity but maintains cost_basis."""
        tx_open = _make_tx("SELL_TO_OPEN", 5, 2.00)
        position_manager.update_position_from_transaction(tx_open)

        tx_close = _make_tx("BUY_TO_CLOSE", 2, 1.50)
        position_manager.update_position_from_transaction(tx_close)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.current_quantity == -3  # Was -5, closed 2 → -3
        assert pos.cost_basis == pytest.approx(2.00)  # Unchanged for closing


# ---------------------------------------------------------------------------
# Position queries
# ---------------------------------------------------------------------------

class TestPositionQueries:
    def test_get_position(self, position_manager):
        """Retrieve by account + symbol."""
        tx = _make_tx("BUY_TO_OPEN", 1, 1.00)
        position_manager.update_position_from_transaction(tx)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos is not None
        assert pos.symbol == "AAPL  250321C00170000"

        missing = position_manager.get_position("ACCT1", "NONEXISTENT")
        assert missing is None

    def test_get_open_positions_for_underlying(self, position_manager):
        """Multiple symbols, same underlying — verified via get_open_positions."""
        tx1 = _make_tx("BUY_TO_OPEN", 1, 1.00, symbol="AAPL 250321C00170000")
        tx2 = _make_tx("SELL_TO_OPEN", 1, 2.00, symbol="AAPL 250321P00160000")

        position_manager.update_position_from_transaction(tx1)
        position_manager.update_position_from_transaction(tx2)

        positions = position_manager.get_open_positions("ACCT1")
        aapl_positions = [p for p in positions if p.underlying == "AAPL"]
        assert len(aapl_positions) == 2


# ---------------------------------------------------------------------------
# Cost basis calculations
# ---------------------------------------------------------------------------

class TestCostBasis:
    def test_cost_basis_weighted_average(self, position_manager):
        """BTO 3 at $1.00 then BTO 2 at $1.50 → cost_basis = $1.20"""
        tx1 = _make_tx("BUY_TO_OPEN", 3, 1.00)
        position_manager.update_position_from_transaction(tx1)

        tx2 = _make_tx("BUY_TO_OPEN", 2, 1.50)
        position_manager.update_position_from_transaction(tx2)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        # Weighted avg: (3*1.00 + 2*1.50) / 5 = 6.00/5 = 1.20
        assert pos.cost_basis == pytest.approx(1.20)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_position_state_transitions(self, position_manager):
        """OPEN → quantity changes → is_closed when 0."""
        tx = _make_tx("BUY_TO_OPEN", 2, 1.00)
        position_manager.update_position_from_transaction(tx)

        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.is_closed is False
        assert pos.is_long is True

        # Partially close
        tx_partial = _make_tx("SELL_TO_CLOSE", 1, 1.50)
        position_manager.update_position_from_transaction(tx_partial)
        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.current_quantity == 1
        assert pos.is_closed is False

        # Fully close
        tx_full = _make_tx("SELL_TO_CLOSE", 1, 2.00)
        position_manager.update_position_from_transaction(tx_full)
        pos = position_manager.get_position("ACCT1", "AAPL  250321C00170000")
        assert pos.is_closed is True
