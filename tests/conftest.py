"""
Shared pytest fixtures and transaction factory helpers for OptionLedger tests.

Each test gets a fresh temporary SQLite database (auto-cleaned by pytest).
"""

import pytest
from datetime import datetime, date

from src.database.db_manager import DatabaseManager
from src.database import engine as sa_engine
from src.models.lot_manager import LotManager
from src.models.pnl_calculator import PnLCalculator
from src.models.position_inventory import PositionInventoryManager
from src.models.strategy_detector import StrategyDetector
from src.models.order_processor import OrderProcessor


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Temporary SQLite database, fully initialized and auto-cleaned."""
    db_path = str(tmp_path / "test.db")
    db_manager = DatabaseManager(db_url=f"sqlite:///{db_path}")
    db_manager.initialize_database()
    return db_manager


@pytest.fixture
def lot_manager(db):
    return LotManager(db)


@pytest.fixture
def position_manager(db):
    return PositionInventoryManager(db)


@pytest.fixture
def pnl_calculator(db, position_manager, lot_manager):
    return PnLCalculator(db, position_manager, lot_manager)


@pytest.fixture
def pnl_calculator_legacy(db, position_manager):
    """PnLCalculator without lot_manager (legacy path)."""
    return PnLCalculator(db, position_manager, lot_manager=None)


@pytest.fixture
def strategy_detector(db):
    return StrategyDetector(db)


@pytest.fixture
def order_processor(db, position_manager, lot_manager):
    return OrderProcessor(db, position_manager, lot_manager)


# ---------------------------------------------------------------------------
# Transaction factory helpers
# ---------------------------------------------------------------------------

def make_option_transaction(
    *,
    id="tx-001",
    account_number="ACCT1",
    order_id="ORD-001",
    symbol="AAPL  250321C00170000",
    underlying_symbol="AAPL",
    action="SELL_TO_OPEN",
    quantity=1,
    price=2.50,
    executed_at="2025-03-01T10:00:00+00:00",
    instrument_type="EQUITY_OPTION",
    transaction_type="Trade",
    transaction_sub_type="Sell to Open",
    description="Sold 1 AAPL 03/21/25 Call 170.00",
    option_type="Call",
    strike=170.0,
    expiration="2025-03-21",
    value=None,
    net_value=None,
    commission=0.0,
    regulatory_fees=0.0,
    clearing_fees=0.0,
):
    """Build a raw transaction dict suitable for OrderProcessor / LotManager."""
    return {
        "id": id,
        "account_number": account_number,
        "order_id": order_id,
        "symbol": symbol,
        "underlying_symbol": underlying_symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": instrument_type,
        "transaction_type": transaction_type,
        "transaction_sub_type": transaction_sub_type,
        "description": description,
        "option_type": option_type,
        "strike": strike,
        "expiration": expiration,
        "value": value or (price * quantity * 100),
        "net_value": net_value or (price * quantity * 100),
        "commission": commission,
        "regulatory_fees": regulatory_fees,
        "clearing_fees": clearing_fees,
    }


def make_stock_transaction(
    *,
    id="tx-stock-001",
    account_number="ACCT1",
    order_id="ORD-STOCK-001",
    symbol="AAPL",
    underlying_symbol="AAPL",
    action="BUY_TO_OPEN",
    quantity=100,
    price=150.00,
    executed_at="2025-03-01T10:00:00+00:00",
    instrument_type="EQUITY",
    transaction_type="Trade",
    transaction_sub_type="Buy to Open",
    description="Bought 100 AAPL",
    value=None,
    net_value=None,
    commission=0.0,
    regulatory_fees=0.0,
    clearing_fees=0.0,
):
    """Build a raw stock transaction dict."""
    return {
        "id": id,
        "account_number": account_number,
        "order_id": order_id,
        "symbol": symbol,
        "underlying_symbol": underlying_symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": instrument_type,
        "transaction_type": transaction_type,
        "transaction_sub_type": transaction_sub_type,
        "description": description,
        "value": value or (price * quantity),
        "net_value": net_value or (price * quantity),
        "commission": commission,
        "regulatory_fees": regulatory_fees,
        "clearing_fees": clearing_fees,
    }


def make_expiration_transaction(
    *,
    id="tx-exp-001",
    account_number="ACCT1",
    symbol="AAPL  250321C00170000",
    underlying_symbol="AAPL",
    quantity=1,
    price=0.0,
    executed_at="2025-03-21T16:00:00+00:00",
    instrument_type="EQUITY_OPTION",
):
    """Build a transaction representing an option expiration."""
    return {
        "id": id,
        "account_number": account_number,
        "order_id": None,
        "symbol": symbol,
        "underlying_symbol": underlying_symbol,
        "action": None,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": instrument_type,
        "transaction_type": "Trade",
        "transaction_sub_type": "Expiration",
        "description": f"Expiration of {symbol}",
        "value": 0.0,
        "net_value": 0.0,
        "commission": 0.0,
        "regulatory_fees": 0.0,
        "clearing_fees": 0.0,
    }


def make_assignment_transaction(
    *,
    id="tx-assign-001",
    account_number="ACCT1",
    symbol="AAPL  250321P00170000",
    underlying_symbol="AAPL",
    quantity=1,
    price=0.0,
    executed_at="2025-03-21T16:00:00+00:00",
    instrument_type="EQUITY_OPTION",
):
    """Build a transaction representing an option assignment."""
    return {
        "id": id,
        "account_number": account_number,
        "order_id": None,
        "symbol": symbol,
        "underlying_symbol": underlying_symbol,
        "action": None,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": instrument_type,
        "transaction_type": "Trade",
        "transaction_sub_type": "Assignment",
        "description": f"Assignment of {symbol}",
        "value": 0.0,
        "net_value": 0.0,
        "commission": 0.0,
        "regulatory_fees": 0.0,
        "clearing_fees": 0.0,
    }


def make_exercise_transaction(
    *,
    id="tx-exercise-001",
    account_number="ACCT1",
    symbol="AAPL  250321P00170000",
    underlying_symbol="AAPL",
    quantity=1,
    price=0.0,
    executed_at="2025-03-21T16:00:00+00:00",
    instrument_type="EQUITY_OPTION",
):
    """Build a transaction representing an option exercise."""
    return {
        "id": id,
        "account_number": account_number,
        "order_id": None,
        "symbol": symbol,
        "underlying_symbol": underlying_symbol,
        "action": None,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": instrument_type,
        "transaction_type": "Trade",
        "transaction_sub_type": "Exercise",
        "description": f"Exercise of {symbol}",
        "value": 0.0,
        "net_value": 0.0,
        "commission": 0.0,
        "regulatory_fees": 0.0,
        "clearing_fees": 0.0,
    }
