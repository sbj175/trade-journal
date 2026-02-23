"""
Tests for StrategyDetector — strategy identification from chain positions.

Source: src/models/strategy_detector.py
"""

import pytest
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Set
from enum import Enum


# ---------------------------------------------------------------------------
# Lightweight stubs matching the interface StrategyDetector expects
# ---------------------------------------------------------------------------

class _OrderType(Enum):
    OPENING = "OPENING"
    CLOSING = "CLOSING"


@dataclass
class _FakeTx:
    """Minimal transaction stub for strategy detection."""
    symbol: str
    underlying_symbol: str
    option_type: Optional[str]
    strike: Optional[float]
    expiration: Optional[date]
    quantity: int
    action: str

    @property
    def is_buy(self):
        return "BUY" in (self.action or "")

    @property
    def is_sell(self):
        return "SELL" in (self.action or "")

    @property
    def is_opening(self):
        return "TO_OPEN" in (self.action or "")


@dataclass
class _FakeOrder:
    order_type: _OrderType
    transactions: List[_FakeTx] = field(default_factory=list)


@dataclass
class _FakeChain:
    chain_id: str = "chain-test"
    account_number: str = "ACCT1"
    orders: List[_FakeOrder] = field(default_factory=list)

    @property
    def opening_date(self) -> Optional[date]:
        return date(2025, 3, 1)


def _make_chain(*legs):
    """Helper: build a fake chain with a single opening order containing the given legs."""
    txs = []
    for leg in legs:
        txs.append(_FakeTx(**leg))
    order = _FakeOrder(order_type=_OrderType.OPENING, transactions=txs)
    return _FakeChain(orders=[order])


# ---------------------------------------------------------------------------
# Single-leg strategies
# ---------------------------------------------------------------------------

class TestSingleLeg:
    def test_short_put(self, strategy_detector):
        chain = _make_chain({
            "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
            "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
            "quantity": -1, "action": "SELL_TO_OPEN",
        })
        assert strategy_detector.detect_chain_strategy(chain) == "Short Put"

    def test_short_call(self, strategy_detector):
        chain = _make_chain({
            "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
            "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
            "quantity": -1, "action": "SELL_TO_OPEN",
        })
        assert strategy_detector.detect_chain_strategy(chain) == "Short Call"

    def test_long_put(self, strategy_detector):
        chain = _make_chain({
            "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
            "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
            "quantity": 1, "action": "BUY_TO_OPEN",
        })
        assert strategy_detector.detect_chain_strategy(chain) == "Long Put"

    def test_long_call(self, strategy_detector):
        chain = _make_chain({
            "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
            "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
            "quantity": 1, "action": "BUY_TO_OPEN",
        })
        assert strategy_detector.detect_chain_strategy(chain) == "Long Call"


# ---------------------------------------------------------------------------
# Two-leg strategies (spreads)
# ---------------------------------------------------------------------------

class TestSpreads:
    def test_put_credit_spread(self, strategy_detector):
        """STO higher put + BTO lower put → Bull Put Spread"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321P00160000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 160.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
        )
        result = strategy_detector.detect_chain_strategy(chain)
        assert result == "Bull Put Spread"

    def test_call_credit_spread(self, strategy_detector):
        """STO lower call + BTO higher call → Bear Call Spread"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321C00180000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 180.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
        )
        result = strategy_detector.detect_chain_strategy(chain)
        assert result == "Bear Call Spread"

    def test_put_debit_spread(self, strategy_detector):
        """BTO higher put + STO lower put → Bear Put Spread"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321P00180000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 180.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
        )
        result = strategy_detector.detect_chain_strategy(chain)
        assert result == "Bear Put Spread"


# ---------------------------------------------------------------------------
# Four-leg strategies
# ---------------------------------------------------------------------------

class TestMultiLeg:
    def test_iron_condor(self, strategy_detector):
        """4 legs: short put + long put + short call + long call → Iron Condor"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321P00160000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 160.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321C00180000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 180.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321C00190000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 190.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
        )
        assert strategy_detector.detect_chain_strategy(chain) == "Iron Condor"


# ---------------------------------------------------------------------------
# Straddle / strangle
# ---------------------------------------------------------------------------

class TestStraddleStrangle:
    def test_short_straddle(self, strategy_detector):
        """Same strike, same expiry, different types, both sold → Short Straddle"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": -1, "action": "SELL_TO_OPEN",
            },
        )
        assert strategy_detector.detect_chain_strategy(chain) == "Short Straddle"

    def test_long_straddle(self, strategy_detector):
        """Same strike, same expiry, different types, both bought → Long Straddle"""
        chain = _make_chain(
            {
                "symbol": "AAPL 250321P00170000", "underlying_symbol": "AAPL",
                "option_type": "Put", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
            {
                "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
                "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
                "quantity": 1, "action": "BUY_TO_OPEN",
            },
        )
        assert strategy_detector.detect_chain_strategy(chain) == "Long Straddle"


# ---------------------------------------------------------------------------
# Covered call (requires stock in DB)
# ---------------------------------------------------------------------------

class TestCoveredCall:
    def test_covered_call(self, strategy_detector, db):
        """Short call + stock position in account → Covered Call"""
        from src.database.models import RawTransaction
        # Insert a stock purchase into raw_transactions so coverage check passes
        with db.get_session() as session:
            session.add(RawTransaction(
                id="tx-stock-buy", account_number="ACCT1", order_id="ORD-STOCK",
                transaction_type="Trade", transaction_sub_type="Buy to Open",
                description="Buy 100 AAPL", executed_at="2025-01-15T10:00:00",
                action="BUY_TO_OPEN", symbol="AAPL", instrument_type="EQUITY",
                underlying_symbol="AAPL", quantity=100, price=150.00, value=15000.00,
            ))

        chain = _make_chain({
            "symbol": "AAPL 250321C00170000", "underlying_symbol": "AAPL",
            "option_type": "Call", "strike": 170.0, "expiration": date(2025, 3, 21),
            "quantity": -1, "action": "SELL_TO_OPEN",
        })

        result = strategy_detector.detect_chain_strategy(chain)
        assert result == "Covered Call"
