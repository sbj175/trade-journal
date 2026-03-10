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

    # Check for ZEBRA ratios (2:1) before regular spreads
    low_qty = low.quantity
    high_qty = high.quantity

    if a.option_type == "C":
        # Bull ZEBRA: long 2x at lower strike, short 1x at higher strike
        if low.direction == "long" and high.direction == "short" and low_qty == 2 * high_qty:
            return "Bull ZEBRA"
        # Bear ZEBRA: short 2x at lower strike, long 1x at higher strike
        if low.direction == "short" and high.direction == "long" and low_qty == 2 * high_qty:
            return "Bear ZEBRA"
    elif a.option_type == "P":
        # Bear ZEBRA with puts: long 2x at higher strike, short 1x at lower strike
        # Net long puts = bearish (profits when underlying falls)
        if high.direction == "long" and low.direction == "short" and high_qty == 2 * low_qty:
            return "Bear ZEBRA"
        # Bull ZEBRA with puts: short 2x at higher strike, long 1x at lower strike
        # Net short puts = bullish (profits when underlying rises)
        if high.direction == "short" and low.direction == "long" and high_qty == 2 * low_qty:
            return "Bull ZEBRA"

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
