"""Single-leg strategy patterns."""

from typing import Optional

from .types import Leg


def match_single(leg: Leg) -> Optional[str]:
    """Identify a single-leg strategy. Returns strategy name or None."""
    if leg.instrument_type == "Equity":
        return "Shares"

    if leg.instrument_type == "Option":
        if leg.option_type == "C":
            return "Long Call" if leg.direction == "long" else "Short Call"
        if leg.option_type == "P":
            return "Long Put" if leg.direction == "long" else "Short Put"

    return None
