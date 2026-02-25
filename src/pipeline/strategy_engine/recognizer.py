"""Main strategy recognition dispatcher."""

from typing import List

from .types import Leg, StrategyResult
from .constants import STRATEGIES
from .patterns_single import match_single
from .patterns_vertical import match_vertical
from .patterns_multi import match_multi
from .patterns_calendar import match_calendar
from .patterns_combo import match_combo


def recognize(legs: List[Leg]) -> StrategyResult:
    """Recognize the strategy formed by a set of legs.

    Algorithm:
    1. Separate equity vs option legs
    2. If equity present, try combo patterns first (Covered Call, Collar, etc.)
    3. Group options by expiration
    4. Try multi-leg patterns (Iron Condor, Strangles, etc.)
    5. Try calendar/diagonal patterns (cross-expiry)
    6. Try vertical patterns (same-expiry, same-type)
    7. Try single-leg patterns
    8. Fall back to Custom (N-leg)
    """
    if not legs:
        return _custom_result(0)

    equity_legs = [l for l in legs if l.instrument_type == "Equity"]
    option_legs = [l for l in legs if l.instrument_type == "Option"]

    # 1. Combo patterns (equity + options, or option-only combos like Jade Lizard)
    if equity_legs:
        name = match_combo(equity_legs, option_legs)
        if name:
            return _result(name)

    # 2. Option-only strategies
    if option_legs:
        # Group by expiration
        expirations = {l.expiration for l in option_legs}

        if len(expirations) == 1:
            # Same expiration — try multi-leg, then vertical
            name = match_multi(option_legs)
            if name:
                return _result(name)

            # Verticals: 2 legs, same type, same expiry
            if len(option_legs) == 2 and option_legs[0].option_type == option_legs[1].option_type:
                name = match_vertical(option_legs)
                if name:
                    return _result(name)

        elif len(expirations) == 2 and len(option_legs) == 2:
            # Different expirations — calendar/diagonal
            if option_legs[0].option_type == option_legs[1].option_type:
                name = match_calendar(option_legs)
                if name:
                    return _result(name)

        # 3-leg option-only combos (Jade Lizard without equity)
        if not equity_legs and len(option_legs) == 3:
            name = match_combo([], option_legs)
            if name:
                return _result(name)

    # 3. Single-leg patterns
    if len(legs) == 1:
        name = match_single(legs[0])
        if name:
            return _result(name)

    # 4. Fallback
    return _custom_result(len(legs))


def _result(name: str) -> StrategyResult:
    """Build a StrategyResult from a strategy name using the registry."""
    defn = STRATEGIES.get(name)
    if defn:
        return StrategyResult(
            name=defn.name,
            direction=defn.direction,
            credit_debit=defn.credit_debit,
            leg_count=defn.leg_count,
            confidence=1.0,
        )
    # Name not in registry — treat as recognized but unregistered
    return StrategyResult(name=name, direction=None, credit_debit=None,
                          leg_count=0, confidence=0.5)


def _custom_result(leg_count: int) -> StrategyResult:
    """Build a fallback Custom result."""
    return StrategyResult(
        name=f"Custom ({leg_count}-leg)",
        direction=None,
        credit_debit=None,
        leg_count=leg_count,
        confidence=0.0,
    )
