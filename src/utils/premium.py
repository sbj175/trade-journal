"""Shared premium calculation for lots.

Single source of truth for computing net premium from position lots.
Used by roll_chain_summary.py and ledger.py roll chain endpoint.
"""


def lot_premium(lot) -> float:
    """Compute the signed premium for a single lot.

    Short legs (qty < 0) = credit received (positive).
    Long legs (qty > 0) = debit paid (negative).

    Works with both ORM PositionLot models and LotManager Lot dataclasses
    — only requires entry_price, original_quantity, quantity, and instrument_type.
    """
    if not lot.entry_price or not lot.original_quantity:
        return 0.0
    multiplier = 100 if getattr(lot, 'instrument_type', '') == 'EQUITY_OPTION' else 1
    amount = abs(lot.entry_price) * abs(lot.original_quantity) * multiplier
    return amount if lot.quantity < 0 else -amount


def group_premium_from_lots(lots) -> float:
    """Compute net premium for a group of lots (credits minus debits)."""
    return sum(lot_premium(lot) for lot in lots)
