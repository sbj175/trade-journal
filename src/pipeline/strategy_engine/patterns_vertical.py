"""Vertical spread patterns (2-leg, same expiry, same option type)."""

from typing import List, Optional

from .types import Leg


def match_vertical(legs: List[Leg]) -> Optional[str]:
    """Identify a vertical spread from exactly 2 option legs.

    Preconditions (checked by caller):
    - Exactly 2 legs
    - Both options
    - Same expiration
    - Same option_type
    - Different strikes
    """
    if len(legs) != 2:
        return None

    a, b = legs
    if not (a.instrument_type == "Option" and b.instrument_type == "Option"):
        return None
    if a.option_type != b.option_type:
        return None
    if a.expiration != b.expiration:
        return None
    if a.strike == b.strike:
        return None

    # Sort by strike: low, high
    if a.strike > b.strike:
        a, b = b, a
    low, high = a, b

    if a.option_type == "P":
        # Put verticals
        if low.direction == "long" and high.direction == "short":
            return "Bull Put Spread"   # credit: short higher put, long lower put
        if low.direction == "short" and high.direction == "long":
            return "Bear Put Spread"   # debit: long higher put, short lower put
    else:
        # Call verticals
        if low.direction == "long" and high.direction == "short":
            return "Bull Call Spread"  # debit: long lower call, short higher call
        if low.direction == "short" and high.direction == "long":
            return "Bear Call Spread"  # credit: short lower call, long higher call

    return None
