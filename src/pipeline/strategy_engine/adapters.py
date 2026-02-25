"""Adapters that bridge existing codebase types to the strategy engine's Leg type."""

from collections import defaultdict
from typing import List

from src.models.lot_manager import Lot
from .types import Leg


def lots_to_legs(lots: List[Lot]) -> List[Leg]:
    """Convert a list of Lot objects to aggregated Leg objects.

    Lots sharing the same structural identity are merged:
    (instrument_type, option_type, strike, expiration, direction)

    Only non-closed lots with remaining quantity are included.
    """
    groups: dict[tuple, int] = defaultdict(int)

    for lot in lots:
        if lot.status == "CLOSED":
            continue

        qty = abs(lot.remaining_quantity)
        if qty == 0:
            continue

        # Normalize instrument_type
        if lot.instrument_type in ("Equity", "EQUITY"):
            inst_type = "Equity"
        else:
            inst_type = "Option"

        # Normalize option_type to "C" / "P"
        opt_type = None
        if lot.option_type:
            opt_type = "C" if lot.option_type.upper().startswith("C") else "P"

        direction = "short" if lot.is_short else "long"

        key = (inst_type, opt_type, lot.strike, lot.expiration, direction)
        groups[key] += qty

    legs = []
    for (inst_type, opt_type, strike, exp, direction), qty in groups.items():
        legs.append(Leg(
            instrument_type=inst_type,
            option_type=opt_type,
            strike=strike,
            expiration=exp,
            direction=direction,
            quantity=qty,
        ))

    return legs
