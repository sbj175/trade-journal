"""Calendar and diagonal spread patterns (2-leg, different expirations)."""

from typing import List, Optional

from .types import Leg


def match_calendar(legs: List[Leg]) -> Optional[str]:
    """Identify calendar-family strategies from 2 option legs with different expirations.

    Preconditions (checked by caller):
    - Exactly 2 legs
    - Both options
    - Same option_type
    - Different expirations
    """
    if len(legs) != 2:
        return None

    a, b = legs
    if not (a.instrument_type == "Option" and b.instrument_type == "Option"):
        return None
    if a.option_type != b.option_type:
        return None
    if a.expiration == b.expiration:
        return None

    # Sort by expiration: near, far
    if a.expiration > b.expiration:
        a, b = b, a
    near, far = a, b

    same_strike = near.strike == far.strike

    if same_strike:
        return "Calendar Spread"

    # Different strikes + different expirations = diagonal
    # PMCC: long far-dated call (lower strike) + short near-term call (higher strike)
    if (a.option_type == "C"
            and far.direction == "long" and near.direction == "short"
            and far.strike < near.strike):
        return "PMCC"

    return "Diagonal Spread"
