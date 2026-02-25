"""Multi-leg patterns: Iron Condor, Iron Butterfly, Strangles, Straddles."""

from typing import List, Optional

from .types import Leg


def match_multi(legs: List[Leg]) -> Optional[str]:
    """Identify multi-leg option strategies.

    Handles 4-leg (iron condor/butterfly) and 2-leg (strangle/straddle).
    All legs must be options with the same expiration.
    """
    if not legs:
        return None

    # All legs must be options with the same expiration
    if any(leg.instrument_type != "Option" for leg in legs):
        return None
    expirations = {leg.expiration for leg in legs}
    if len(expirations) != 1:
        return None

    if len(legs) == 4:
        return _match_four_leg(legs)
    if len(legs) == 2:
        return _match_two_leg(legs)

    return None


def _match_four_leg(legs: List[Leg]) -> Optional[str]:
    """Match 4-leg strategies: Iron Condor, Iron Butterfly."""
    puts = [l for l in legs if l.option_type == "P"]
    calls = [l for l in legs if l.option_type == "C"]

    if len(puts) != 2 or len(calls) != 2:
        return None

    # Sort by strike
    puts.sort(key=lambda l: l.strike)
    calls.sort(key=lambda l: l.strike)

    long_put, short_put = puts[0], puts[1]
    short_call, long_call = calls[0], calls[1]

    # Validate directions: long wings, short body
    if not (long_put.direction == "long" and short_put.direction == "short"
            and short_call.direction == "short" and long_call.direction == "long"):
        return None

    # Validate strike ordering: long_put < short_put <= short_call < long_call
    if not (long_put.strike < short_put.strike <= short_call.strike < long_call.strike):
        return None

    # Iron Butterfly: short put and short call share the same strike
    if short_put.strike == short_call.strike:
        return "Iron Butterfly"

    return "Iron Condor"


def _match_two_leg(legs: List[Leg]) -> Optional[str]:
    """Match 2-leg same-expiry strategies: Strangle, Straddle.

    Only matches when legs are different option types (put + call).
    Same-type pairs are verticals (handled elsewhere).
    """
    a, b = legs

    # Must be one put and one call
    if a.option_type == b.option_type:
        return None

    # Both must have the same direction
    if a.direction != b.direction:
        return None

    is_short = a.direction == "short"
    same_strike = a.strike == b.strike

    if same_strike:
        return "Short Straddle" if is_short else "Long Straddle"
    else:
        return "Short Strangle" if is_short else "Long Strangle"
