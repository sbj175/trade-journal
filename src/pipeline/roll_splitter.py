"""
Roll Splitter — splits compound rolling orders into roll pairs + new positions.

When a trader places a single order that closes a position AND opens multiple
new positions (e.g., rolling a covered call up while adding an extra call for
income), the broker assigns one order_id to all legs. Without splitting, the
pipeline treats this as a single multi-leg strategy (e.g., "Diagonal Spread")
and misses the roll.

This module splits such orders so that:
  - The close + closest-strike open stay as a ROLLING order (preserving chain)
  - Remaining opens become a separate OPENING order (new position)

Runs between order assembly (Stage 2) and lot processing (Stage 3).
Pure function — no DB access.
"""

import logging
from collections import Counter, defaultdict
from typing import List

from src.models.order_processor import Order, OrderType

logger = logging.getLogger(__name__)


def _signature(tx) -> tuple:
    """(option_type, direction) key for pairing closes with opens.

    BTO/STC touch long positions; STO/BTC touch short. `is_short` on the
    Position object reflects the affected side regardless of action verb.
    """
    return (tx.option_type, "short" if tx.is_short else "long")


def split_rolling_orders(orders: List[Order]) -> List[Order]:
    """Split ROLLING orders that have multiple distinct opening symbols.

    A standard roll has one closing symbol and one opening symbol.
    A compound roll has one closing symbol and multiple opening symbols —
    one is the roll target (closest strike), the rest are new positions.

    A multi-leg roll (e.g. rolling a put spread in one order) has N closes
    and N opens that mirror each other by (option_type, direction). In that
    case the whole order IS the roll — no split.
    """
    result = []

    for order in orders:
        if order.order_type != OrderType.ROLLING:
            result.append(order)
            continue

        closing_txns = order.closing_transactions
        opening_txns = order.opening_transactions

        # Group opening transactions by distinct symbol
        opening_by_symbol = defaultdict(list)
        for tx in opening_txns:
            opening_by_symbol[tx.symbol].append(tx)

        # No split needed if there's only one opening symbol
        if len(opening_by_symbol) <= 1:
            result.append(order)
            continue

        # Multi-leg roll: closes and opens mirror each other by (type, direction).
        # e.g. put-spread roll closes 1 long-put + 1 short-put and opens 1 long-put
        # + 1 short-put at new strikes. Treat as a single rolling order; each new
        # lot will pair with its direction-matched close during lot processing.
        if Counter(_signature(tx) for tx in closing_txns) == Counter(_signature(tx) for tx in opening_txns):
            result.append(order)
            continue

        # Find the closing leg's strike and option type for matching
        # (use the first closing txn — in a standard roll they all share the same symbol)
        close_strike = closing_txns[0].strike
        close_option_type = closing_txns[0].option_type

        if close_strike is None or close_option_type is None:
            # Can't match without strike/type — keep as-is
            result.append(order)
            continue

        # Find the best roll target: same option type, closest strike
        best_symbol = None
        best_distance = float('inf')

        for symbol, txns in opening_by_symbol.items():
            tx = txns[0]
            if tx.option_type == close_option_type and tx.strike is not None:
                distance = abs(tx.strike - close_strike)
                if distance < best_distance:
                    best_distance = distance
                    best_symbol = symbol

        if best_symbol is None:
            # No matching option type found — keep as-is
            result.append(order)
            continue

        # Split: ROLLING order (close + roll target) + OPENING order (rest)
        roll_opening_txns = opening_by_symbol.pop(best_symbol)
        remaining_txns = [tx for txns in opening_by_symbol.values() for tx in txns]

        # Update order_id on the split-off transactions so downstream lot
        # creation uses the derived id (prevents grouping with the roll pair)
        split_order_id = f"{order.order_id}_split"
        for tx in remaining_txns:
            tx.order_id = split_order_id

        roll_order = Order(
            order_id=order.order_id,
            account_number=order.account_number,
            underlying=order.underlying,
            executed_at=order.executed_at,
            order_type=OrderType.ROLLING,
            transactions=closing_txns + roll_opening_txns,
        )

        new_order = Order(
            order_id=split_order_id,
            account_number=order.account_number,
            underlying=order.underlying,
            executed_at=order.executed_at,
            order_type=OrderType.OPENING,
            transactions=remaining_txns,
        )

        result.append(roll_order)
        result.append(new_order)

        logger.info(
            "Split ROLLING order %s (%s): roll %s→%s, new position %s",
            order.order_id,
            order.underlying,
            closing_txns[0].symbol,
            best_symbol,
            ", ".join(opening_by_symbol.keys()) if opening_by_symbol else remaining_txns[0].symbol,
        )

    return result
