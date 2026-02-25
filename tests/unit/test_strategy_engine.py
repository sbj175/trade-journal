"""Unit tests for the strategy engine — pure logic, no database."""

import pytest
from datetime import date

from src.pipeline.strategy_engine import recognize, lots_to_legs, Leg, StrategyResult, STRATEGIES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opt(option_type, strike, direction, exp=None, quantity=1):
    """Shorthand to build an option Leg."""
    return Leg(
        instrument_type="Option",
        option_type=option_type,
        strike=strike,
        expiration=exp or date(2026, 3, 21),
        direction=direction,
        quantity=quantity,
    )


def _equity(direction="long", quantity=100):
    """Shorthand to build an equity Leg."""
    return Leg(
        instrument_type="Equity",
        option_type=None,
        strike=None,
        expiration=None,
        direction=direction,
        quantity=quantity,
    )


# ---------------------------------------------------------------------------
# Single-leg strategies
# ---------------------------------------------------------------------------

class TestSingleLeg:
    def test_long_call(self):
        r = recognize([_opt("C", 100, "long")])
        assert r.name == "Long Call"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"
        assert r.confidence == 1.0

    def test_short_call(self):
        r = recognize([_opt("C", 100, "short")])
        assert r.name == "Short Call"
        assert r.direction == "bearish"

    def test_long_put(self):
        r = recognize([_opt("P", 50, "long")])
        assert r.name == "Long Put"
        assert r.direction == "bearish"
        assert r.credit_debit == "debit"

    def test_short_put(self):
        r = recognize([_opt("P", 50, "short")])
        assert r.name == "Short Put"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_shares_long(self):
        r = recognize([_equity("long")])
        assert r.name == "Shares"
        assert r.direction is None
        assert r.confidence == 1.0

    def test_shares_short(self):
        r = recognize([_equity("short")])
        assert r.name == "Shares"


# ---------------------------------------------------------------------------
# Vertical spreads
# ---------------------------------------------------------------------------

class TestVerticals:
    def test_bull_put_spread(self):
        legs = [
            _opt("P", 100, "short"),  # short higher put
            _opt("P", 95, "long"),    # long lower put
        ]
        r = recognize(legs)
        assert r.name == "Bull Put Spread"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_bear_call_spread(self):
        legs = [
            _opt("C", 100, "short"),  # short lower call
            _opt("C", 105, "long"),   # long higher call
        ]
        r = recognize(legs)
        assert r.name == "Bear Call Spread"
        assert r.direction == "bearish"
        assert r.credit_debit == "credit"

    def test_bull_call_spread(self):
        legs = [
            _opt("C", 100, "long"),   # long lower call
            _opt("C", 105, "short"),  # short higher call
        ]
        r = recognize(legs)
        assert r.name == "Bull Call Spread"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"

    def test_bear_put_spread(self):
        legs = [
            _opt("P", 100, "long"),   # long higher put
            _opt("P", 95, "short"),   # short lower put
        ]
        r = recognize(legs)
        assert r.name == "Bear Put Spread"
        assert r.direction == "bearish"
        assert r.credit_debit == "debit"

    def test_vertical_requires_different_strikes(self):
        legs = [
            _opt("P", 100, "short"),
            _opt("P", 100, "long"),
        ]
        r = recognize(legs)
        # Same strike puts with different directions = not a vertical
        assert "Spread" not in r.name


# ---------------------------------------------------------------------------
# Multi-leg strategies
# ---------------------------------------------------------------------------

class TestMultiLeg:
    def test_iron_condor(self):
        legs = [
            _opt("P", 90, "long"),    # long put wing
            _opt("P", 95, "short"),   # short put
            _opt("C", 105, "short"),  # short call
            _opt("C", 110, "long"),   # long call wing
        ]
        r = recognize(legs)
        assert r.name == "Iron Condor"
        assert r.direction == "neutral"
        assert r.credit_debit == "credit"
        assert r.leg_count == 4
        assert r.confidence == 1.0

    def test_iron_butterfly(self):
        legs = [
            _opt("P", 90, "long"),
            _opt("P", 100, "short"),
            _opt("C", 100, "short"),  # same strike as short put
            _opt("C", 110, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Iron Butterfly"
        assert r.direction == "neutral"

    def test_short_strangle(self):
        legs = [
            _opt("P", 95, "short"),
            _opt("C", 105, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Short Strangle"
        assert r.direction == "neutral"
        assert r.credit_debit == "credit"

    def test_long_strangle(self):
        legs = [
            _opt("P", 95, "long"),
            _opt("C", 105, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Long Strangle"
        assert r.credit_debit == "debit"

    def test_short_straddle(self):
        legs = [
            _opt("P", 100, "short"),
            _opt("C", 100, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Short Straddle"

    def test_long_straddle(self):
        legs = [
            _opt("P", 100, "long"),
            _opt("C", 100, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Long Straddle"

    def test_iron_condor_cross_order_assembly(self):
        """IC built from two separate vertical orders — different quantities."""
        legs = [
            _opt("P", 90, "long", quantity=2),
            _opt("P", 95, "short", quantity=2),
            _opt("C", 105, "short", quantity=2),
            _opt("C", 110, "long", quantity=2),
        ]
        r = recognize(legs)
        assert r.name == "Iron Condor"


# ---------------------------------------------------------------------------
# Calendar / Diagonal
# ---------------------------------------------------------------------------

class TestCalendar:
    def test_calendar_spread(self):
        legs = [
            _opt("C", 100, "short", exp=date(2026, 3, 21)),
            _opt("C", 100, "long", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Calendar Spread"
        assert r.direction == "neutral"
        assert r.credit_debit == "debit"

    def test_diagonal_spread(self):
        legs = [
            _opt("P", 95, "short", exp=date(2026, 3, 21)),
            _opt("P", 90, "long", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Diagonal Spread"

    def test_pmcc(self):
        """Poor Man's Covered Call: long far call (lower strike) + short near call (higher strike)."""
        legs = [
            _opt("C", 90, "long", exp=date(2026, 6, 19)),    # far, lower strike
            _opt("C", 105, "short", exp=date(2026, 3, 21)),  # near, higher strike
        ]
        r = recognize(legs)
        assert r.name == "PMCC"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"

    def test_calendar_put(self):
        legs = [
            _opt("P", 100, "short", exp=date(2026, 3, 21)),
            _opt("P", 100, "long", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Calendar Spread"


# ---------------------------------------------------------------------------
# Combo strategies
# ---------------------------------------------------------------------------

class TestCombos:
    def test_covered_call(self):
        legs = [
            _equity("long", 100),
            _opt("C", 105, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Covered Call"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_covered_call_200_shares_2_calls(self):
        legs = [
            _equity("long", 200),
            _opt("C", 105, "short", quantity=2),
        ]
        r = recognize(legs)
        assert r.name == "Covered Call"

    def test_collar(self):
        legs = [
            _equity("long", 100),
            _opt("C", 110, "short"),
            _opt("P", 95, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Collar"
        assert r.direction == "neutral"
        assert r.credit_debit == "mixed"

    def test_cash_secured_put(self):
        legs = [_opt("P", 100, "short")]
        r = recognize(legs)
        # Single short put is recognized as Short Put by single-leg first;
        # Cash Secured Put requires the combo path (option-only combo).
        # The recognizer tries option_legs path first for single options.
        assert r.name == "Short Put"

    def test_jade_lizard(self):
        legs = [
            _opt("P", 90, "short"),   # short put
            _opt("C", 100, "short"),  # short call (lower)
            _opt("C", 105, "long"),   # long call (higher) — bear call spread
        ]
        r = recognize(legs)
        assert r.name == "Jade Lizard"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_list(self):
        r = recognize([])
        assert r.name == "Custom (0-leg)"
        assert r.confidence == 0.0

    def test_unrecognized_two_leg(self):
        """Two options with mixed directions and different types, different expiry."""
        legs = [
            _opt("C", 100, "long", exp=date(2026, 3, 21)),
            _opt("P", 95, "short", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Custom (2-leg)"
        assert r.confidence == 0.0

    def test_unrecognized_three_leg(self):
        """Three random options that don't match any pattern."""
        legs = [
            _opt("C", 100, "long"),
            _opt("C", 105, "long"),
            _opt("P", 90, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Custom (3-leg)"
        assert r.confidence == 0.0

    def test_all_strategies_in_registry(self):
        """Verify every strategy in STRATEGIES has required fields."""
        for name, defn in STRATEGIES.items():
            assert defn.name == name
            assert defn.category in ("single", "vertical", "multi", "calendar", "combo")
            assert defn.leg_count >= 1


# ---------------------------------------------------------------------------
# Adapter: lots_to_legs
# ---------------------------------------------------------------------------

class TestLotsToLegs:
    def test_aggregation(self):
        """Multiple lots with same structural identity are merged."""
        from unittest.mock import MagicMock
        from datetime import datetime

        exp = date(2026, 3, 21)

        def _make_lot(option_type, strike, is_short, qty, status="OPEN"):
            lot = MagicMock()
            lot.instrument_type = "EQUITY_OPTION"
            lot.option_type = option_type
            lot.strike = strike
            lot.expiration = exp
            lot.is_short = is_short
            lot.remaining_quantity = -qty if is_short else qty
            lot.status = status
            return lot

        lots = [
            _make_lot("Call", 100, True, 1),
            _make_lot("Call", 100, True, 1),  # same — should merge
            _make_lot("Put", 95, False, 1),
        ]

        legs = lots_to_legs(lots)
        assert len(legs) == 2  # merged calls + 1 put

        call_leg = next(l for l in legs if l.option_type == "C")
        assert call_leg.quantity == 2
        assert call_leg.direction == "short"

        put_leg = next(l for l in legs if l.option_type == "P")
        assert put_leg.quantity == 1
        assert put_leg.direction == "long"

    def test_closed_lots_excluded(self):
        from unittest.mock import MagicMock

        lot = MagicMock()
        lot.instrument_type = "EQUITY_OPTION"
        lot.option_type = "Call"
        lot.strike = 100.0
        lot.expiration = date(2026, 3, 21)
        lot.is_short = True
        lot.remaining_quantity = 0
        lot.status = "CLOSED"

        legs = lots_to_legs([lot])
        assert len(legs) == 0

    def test_equity_normalization(self):
        from unittest.mock import MagicMock

        lot = MagicMock()
        lot.instrument_type = "Equity"
        lot.option_type = None
        lot.strike = None
        lot.expiration = None
        lot.is_short = False
        lot.remaining_quantity = 100
        lot.status = "OPEN"

        legs = lots_to_legs([lot])
        assert len(legs) == 1
        assert legs[0].instrument_type == "Equity"
        assert legs[0].direction == "long"
        assert legs[0].quantity == 100
