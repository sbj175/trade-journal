"""Combo patterns: strategies that mix equity and options."""

from typing import List, Optional

from .types import Leg


def match_combo(equity_legs: List[Leg], option_legs: List[Leg]) -> Optional[str]:
    """Identify combo strategies that combine equity with options.

    Args:
        equity_legs: Equity legs (Shares).
        option_legs: Option legs.

    Returns:
        Strategy name or None.
    """
    if not equity_legs:
        # Cash Secured Put: short put with no equity (still a combo conceptually)
        return _match_option_only_combo(option_legs)

    if len(equity_legs) != 1:
        return None

    equity = equity_legs[0]
    if equity.direction != "long":
        return None

    share_qty = equity.quantity

    if len(option_legs) == 1:
        return _match_covered_call(equity, option_legs[0], share_qty)

    if len(option_legs) == 2:
        return _match_collar_or_jade(equity, option_legs, share_qty)

    return None


def _match_option_only_combo(option_legs: List[Leg]) -> Optional[str]:
    """Match combos that don't require equity: Jade Lizard, Cash Secured Put."""
    if len(option_legs) == 1:
        leg = option_legs[0]
        if leg.option_type == "P" and leg.direction == "short":
            return "Cash Secured Put"
        return None

    if len(option_legs) == 3:
        return _match_jade_lizard_no_equity(option_legs)

    return None


def _match_covered_call(equity: Leg, option: Leg, share_qty: int) -> Optional[str]:
    """Covered Call: long equity + short call, 100:1 ratio."""
    if (option.option_type == "C"
            and option.direction == "short"
            and share_qty >= option.quantity * 100):
        return "Covered Call"
    return None


def _match_collar_or_jade(equity: Leg, option_legs: List[Leg], share_qty: int) -> Optional[str]:
    """Collar: long equity + short call + long put."""
    calls = [l for l in option_legs if l.option_type == "C"]
    puts = [l for l in option_legs if l.option_type == "P"]

    if len(calls) == 1 and len(puts) == 1:
        call, put = calls[0], puts[0]
        if call.direction == "short" and put.direction == "long":
            return "Collar"

    return None


def _match_jade_lizard_no_equity(option_legs: List[Leg]) -> Optional[str]:
    """Jade Lizard: short put + bear call spread (short call + long call).

    No upside risk — the call spread credit offsets the short call obligation.
    """
    puts = [l for l in option_legs if l.option_type == "P"]
    calls = [l for l in option_legs if l.option_type == "C"]

    if len(puts) != 1 or len(calls) != 2:
        return None

    put = puts[0]
    if put.direction != "short":
        return None

    # Sort calls by strike
    calls.sort(key=lambda l: l.strike)
    low_call, high_call = calls

    # Bear call spread: short lower call + long higher call
    if low_call.direction == "short" and high_call.direction == "long":
        return "Jade Lizard"

    return None
