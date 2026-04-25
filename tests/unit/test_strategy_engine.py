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
        """A single long call should be recognized as a bullish 'Long Call' strategy paid for as a debit."""
        r = recognize([_opt("C", 100, "long")])
        assert r.name == "Long Call"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"
        assert r.confidence == 1.0

    def test_short_call(self):
        """A single short call should be recognized as a bearish 'Short Call' strategy."""
        r = recognize([_opt("C", 100, "short")])
        assert r.name == "Short Call"
        assert r.direction == "bearish"

    def test_long_put(self):
        """A single long put should be recognized as a bearish 'Long Put' strategy paid for as a debit."""
        r = recognize([_opt("P", 50, "long")])
        assert r.name == "Long Put"
        assert r.direction == "bearish"
        assert r.credit_debit == "debit"

    def test_short_put(self):
        """A single short put should be recognized as a bullish 'Short Put' strategy collected as a credit."""
        r = recognize([_opt("P", 50, "short")])
        assert r.name == "Short Put"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_shares_long(self):
        """A long-only stock holding should be recognized simply as 'Shares'."""
        r = recognize([_equity("long")])
        assert r.name == "Shares"
        assert r.direction is None
        assert r.confidence == 1.0

    def test_shares_short(self):
        """A short stock position should also be recognized as 'Shares'."""
        r = recognize([_equity("short")])
        assert r.name == "Shares"


# ---------------------------------------------------------------------------
# Vertical spreads
# ---------------------------------------------------------------------------

class TestVerticals:
    def test_bull_put_spread(self):
        """Selling a higher-strike put and buying a lower-strike put together should be recognized as a bullish credit-style 'Bull Put Spread'."""
        legs = [
            _opt("P", 100, "short"),  # short higher put
            _opt("P", 95, "long"),    # long lower put
        ]
        r = recognize(legs)
        assert r.name == "Bull Put Spread"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_bear_call_spread(self):
        """Selling a lower-strike call and buying a higher-strike call together should be recognized as a bearish credit-style 'Bear Call Spread'."""
        legs = [
            _opt("C", 100, "short"),  # short lower call
            _opt("C", 105, "long"),   # long higher call
        ]
        r = recognize(legs)
        assert r.name == "Bear Call Spread"
        assert r.direction == "bearish"
        assert r.credit_debit == "credit"

    def test_bull_call_spread(self):
        """Buying a lower-strike call and selling a higher-strike call together should be recognized as a bullish debit-style 'Bull Call Spread'."""
        legs = [
            _opt("C", 100, "long"),   # long lower call
            _opt("C", 105, "short"),  # short higher call
        ]
        r = recognize(legs)
        assert r.name == "Bull Call Spread"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"

    def test_bear_put_spread(self):
        """Buying a higher-strike put and selling a lower-strike put together should be recognized as a bearish debit-style 'Bear Put Spread'."""
        legs = [
            _opt("P", 100, "long"),   # long higher put
            _opt("P", 95, "short"),   # short lower put
        ]
        r = recognize(legs)
        assert r.name == "Bear Put Spread"
        assert r.direction == "bearish"
        assert r.credit_debit == "debit"

    def test_vertical_requires_different_strikes(self):
        """Two puts at the same strike but opposite directions should not be labelled as a vertical spread (spreads require different strikes)."""
        legs = [
            _opt("P", 100, "short"),
            _opt("P", 100, "long"),
        ]
        r = recognize(legs)
        # Same strike puts with different directions = not a vertical
        assert "Spread" not in r.name

    def test_bull_zebra_calls(self):
        """Buying two ITM calls at a lower strike and selling one call at a higher strike (a 2:1 ratio) should be recognized as a bullish 'Bull ZEBRA'."""
        legs = [
            _opt("C", 100, "long", quantity=2),   # long 2x lower call
            _opt("C", 105, "short", quantity=1),  # short 1x higher call
        ]
        r = recognize(legs)
        assert r.name == "Bull ZEBRA"

    def test_bear_zebra_calls(self):
        """Selling two calls at a lower strike and buying one call at a higher strike (a 2:1 ratio) should be recognized as a bearish 'Bear ZEBRA'."""
        legs = [
            _opt("C", 100, "short", quantity=2),  # short 2x lower call
            _opt("C", 105, "long", quantity=1),   # long 1x higher call
        ]
        r = recognize(legs)
        assert r.name == "Bear ZEBRA"

    def test_bear_zebra_puts(self):
        """Buying two ITM puts at a higher strike and selling one put at a lower strike (a 2:1 ratio) should be recognized as a bearish 'Bear ZEBRA'."""
        legs = [
            _opt("P", 105, "long", quantity=2),   # long 2x higher put
            _opt("P", 100, "short", quantity=1),  # short 1x lower put
        ]
        r = recognize(legs)
        assert r.name == "Bear ZEBRA"

    def test_bull_zebra_puts(self):
        """Selling two puts at a higher strike and buying one put at a lower strike (a 2:1 ratio) should be recognized as a bullish 'Bull ZEBRA'."""
        legs = [
            _opt("P", 105, "short", quantity=2),  # short 2x higher put
            _opt("P", 100, "long", quantity=1),   # long 1x lower put
        ]
        r = recognize(legs)
        assert r.name == "Bull ZEBRA"


# ---------------------------------------------------------------------------
# Multi-leg strategies
# ---------------------------------------------------------------------------

class TestMultiLeg:
    def test_iron_condor(self):
        """A four-leg position made of a short put spread and a short call spread should be recognized as a neutral 'Iron Condor'."""
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
        """An iron condor whose short put and short call share the same strike should be recognized as an 'Iron Butterfly'."""
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
        """A short put combined with a short call at a higher strike should be recognized as a 'Short Strangle'."""
        legs = [
            _opt("P", 95, "short"),
            _opt("C", 105, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Short Strangle"
        assert r.direction == "neutral"
        assert r.credit_debit == "credit"

    def test_long_strangle(self):
        """A long put combined with a long call at a higher strike should be recognized as a 'Long Strangle'."""
        legs = [
            _opt("P", 95, "long"),
            _opt("C", 105, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Long Strangle"
        assert r.credit_debit == "debit"

    def test_short_straddle(self):
        """A short put plus a short call at the same strike should be recognized as a 'Short Straddle'."""
        legs = [
            _opt("P", 100, "short"),
            _opt("C", 100, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Short Straddle"

    def test_long_straddle(self):
        """A long put plus a long call at the same strike should be recognized as a 'Long Straddle'."""
        legs = [
            _opt("P", 100, "long"),
            _opt("C", 100, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Long Straddle"

    def test_iron_condor_cross_order_assembly(self):
        """An Iron Condor should still be recognized when its put and call wings are entered as separate spreads with matching multi-contract sizes."""
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
        """A short near-term call and a long longer-dated call at the same strike should be recognized as a 'Calendar Spread'."""
        legs = [
            _opt("C", 100, "short", exp=date(2026, 3, 21)),
            _opt("C", 100, "long", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Calendar Spread"
        assert r.direction == "neutral"
        assert r.credit_debit == "debit"

    def test_diagonal_spread(self):
        """A short near-term put and a long longer-dated put at a different strike should be recognized as a 'Diagonal Spread'."""
        legs = [
            _opt("P", 95, "short", exp=date(2026, 3, 21)),
            _opt("P", 90, "long", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Diagonal Spread"

    def test_pmcc(self):
        """A long far-dated lower-strike call combined with a short near-dated higher-strike call should be recognized as a bullish 'Diagonal Call Spread' (a Poor Man's Covered Call)."""
        legs = [
            _opt("C", 90, "long", exp=date(2026, 6, 19)),    # far, lower strike
            _opt("C", 105, "short", exp=date(2026, 3, 21)),  # near, higher strike
        ]
        r = recognize(legs)
        assert r.name == "Diagonal Call Spread"
        assert r.direction == "bullish"
        assert r.credit_debit == "debit"

    def test_calendar_put(self):
        """A short near-term put and a long longer-dated put at the same strike should also be recognized as a 'Calendar Spread'."""
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
        """100 shares of stock paired with a short call should be recognized as a bullish credit-style 'Covered Call'."""
        legs = [
            _equity("long", 100),
            _opt("C", 105, "short"),
        ]
        r = recognize(legs)
        assert r.name == "Covered Call"
        assert r.direction == "bullish"
        assert r.credit_debit == "credit"

    def test_covered_call_200_shares_2_calls(self):
        """200 shares paired with two short calls should still be recognized as a 'Covered Call' (the share-to-contract ratio scales)."""
        legs = [
            _equity("long", 200),
            _opt("C", 105, "short", quantity=2),
        ]
        r = recognize(legs)
        assert r.name == "Covered Call"

    def test_collar(self):
        """Long shares plus a short call above the price plus a long put below the price should be recognized as a neutral 'Collar' position."""
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
        """A lone short put is reported as 'Short Put' rather than 'Cash Secured Put' because the engine prefers the simpler single-leg label."""
        legs = [_opt("P", 100, "short")]
        r = recognize(legs)
        # Single short put is recognized as Short Put by single-leg first;
        # Cash Secured Put requires the combo path (option-only combo).
        # The recognizer tries option_legs path first for single options.
        assert r.name == "Short Put"

    def test_jade_lizard(self):
        """A short put combined with a short call spread on the upside should be recognized as a bullish credit-style 'Jade Lizard'."""
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
        """Recognizing an empty leg list should produce a placeholder 'Custom (0-leg)' result with zero confidence."""
        r = recognize([])
        assert r.name == "Custom (0-leg)"
        assert r.confidence == 0.0

    def test_two_leg_partition(self):
        """Two options that do not fit any known two-leg pattern should be reported as the combination of their individual labels."""
        legs = [
            _opt("C", 100, "long", exp=date(2026, 3, 21)),
            _opt("P", 95, "short", exp=date(2026, 4, 17)),
        ]
        r = recognize(legs)
        assert r.name == "Long Call + Short Put"
        assert r.confidence == 0.9

    def test_three_leg_partition(self):
        """Three legs that do not fit a single strategy should be reported as a combination of their individual labels."""
        legs = [
            _opt("C", 100, "long"),
            _opt("C", 105, "long"),
            _opt("P", 90, "short"),
        ]
        r = recognize(legs)
        # All three recognized as individual legs
        assert "Long Call" in r.name
        assert "Short Put" in r.name
        assert r.confidence == 0.9

    def test_all_strategies_in_registry(self):
        """Every entry in the strategy registry should have a name, a category, and a leg count."""
        for name, defn in STRATEGIES.items():
            assert defn.name == name
            assert defn.category in ("single", "vertical", "multi", "calendar", "combo")
            assert defn.leg_count >= 1


# ---------------------------------------------------------------------------
# Scoring / Partition (OPT-206)
# ---------------------------------------------------------------------------

class TestPartitionScoring:
    def test_jade_lizard_beats_vertical_plus_single(self):
        """Three legs that can form a Jade Lizard should be labelled as such instead of being split into a Bear Call Spread plus a separate Short Put."""
        legs = [
            _opt("P", 90, "short"),
            _opt("C", 100, "short"),
            _opt("C", 105, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Jade Lizard"
        assert r.confidence == 1.0

    def test_iron_condor_beats_two_verticals(self):
        """Four legs that can form an Iron Condor should be labelled as such instead of being split into two separate vertical spreads."""
        legs = [
            _opt("P", 90, "long"),
            _opt("P", 95, "short"),
            _opt("C", 105, "short"),
            _opt("C", 110, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Iron Condor"
        assert r.confidence == 1.0

    def test_three_leg_partition_with_strangle(self):
        """Three legs that contain a strangle plus an extra option should be reported as a two-leg-plus-one partition with high confidence."""
        legs = [
            _opt("P", 95, "long"),
            _opt("P", 100, "short"),
            _opt("C", 110, "short"),  # can form strangle with short put
        ]
        r = recognize(legs)
        # Solver finds Short Strangle(100P+110C) + Long Put, or Bull Put Spread + Short Call
        # Both are valid 2+1 partitions — either is acceptable
        assert r.confidence == 0.9
        assert "+" in r.name

    def test_strangle_plus_extra_leg(self):
        """A short strangle plus an extra long protective put should be reported as a partition of two recognized strategies."""
        legs = [
            _opt("P", 90, "short"),
            _opt("C", 110, "short"),
            _opt("P", 85, "long"),  # protective put
        ]
        r = recognize(legs)
        # Solver finds Bull Put Spread(85P+90P) + Short Call, or Short Strangle + Long Put
        # Both are valid 2+1 partitions
        assert r.confidence == 0.9
        assert "+" in r.name

    def test_five_leg_partition(self):
        """Five legs should be split into the highest-scoring combination of recognized strategies that covers every leg."""
        legs = [
            _opt("P", 90, "long"),
            _opt("P", 95, "short"),
            _opt("C", 105, "short"),
            _opt("C", 110, "long"),
            _opt("P", 80, "short"),  # extra short put
        ]
        r = recognize(legs)
        # Jade Lizard(80P+105C+110C) + Bull Put Spread(90P+95P) scores 8+5=13
        # Iron Condor(90P+95P+105C+110C) + Short Put(80P) scores 10+2=12
        # Solver picks the highest-scoring partition
        assert r.confidence == 0.9
        assert "+" in r.name
        # All 5 legs should be covered
        assert r.leg_count == 5

    def test_two_verticals_different_types(self):
        """A bull put spread combined with a bear call spread at the same expiration should still be recognized as a single Iron Condor."""
        legs = [
            _opt("P", 90, "long"),
            _opt("P", 95, "short"),
            _opt("C", 110, "short"),   # gap between 95 and 110
            _opt("C", 115, "long"),
        ]
        r = recognize(legs)
        # Should recognize as Iron Condor (4-leg pattern matches)
        assert r.name == "Iron Condor"

    def test_covered_call_with_extra_put(self):
        """Adding a protective long put to a covered call should be recognized as a 'Collar'."""
        legs = [
            _equity("long", 100),
            _opt("C", 110, "short"),
            _opt("P", 95, "long"),
        ]
        r = recognize(legs)
        assert r.name == "Collar"
        assert r.confidence == 1.0


# ---------------------------------------------------------------------------
# Adapter: lots_to_legs
# ---------------------------------------------------------------------------

class TestLotsToLegs:
    def test_aggregation(self):
        """Lots with identical option type, strike, expiration, and direction should be merged into a single leg with the combined contract count."""
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
        """Closed lots should not produce any legs since they no longer represent open exposure."""
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
        """Stock lots should be turned into a single equity leg with the right direction and share count."""
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
