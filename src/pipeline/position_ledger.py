"""
Position Ledger — Stage 3 of the OPT-121 pipeline redesign.

Creates and closes lots from assembled Order objects.  Assignment and exercise
handling creates derived stock lots linked to the originating option chain.

Extracted from OrderProcessor._update_positions() and _process_assignments().
All chain-derivation logic is gone — chains are derived in Stage 4
(chain_graph.derive_chains) from the lots this module creates.

Part of OPT-121.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Set

from src.models.order_processor import Order, OrderType

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager
    from src.models.position_inventory import PositionInventoryManager

logger = logging.getLogger(__name__)

__all__ = ["process_lots"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_lots(
    orders: List[Order],
    assignment_stock_transactions: List[Dict],
    lot_manager: "LotManager",
    position_manager: "PositionInventoryManager",
    db_manager: "DatabaseManager",
) -> None:
    """Stage 3: create/close lots and handle assignment/exercise derived lots.

    Parameters
    ----------
    orders : list[Order]
        Chronologically sorted Order objects from Stage 2 (order_assembler).
    assignment_stock_transactions : list[dict]
        Raw stock transaction dicts that were separated during preprocessing
        (stock transactions resulting from assignment/exercise, no order_id).
    lot_manager : LotManager
        Manages position_lots and lot_closings tables.
    position_manager : PositionInventoryManager
        Legacy position inventory (updated for backward compatibility).
    db_manager : DatabaseManager
        Database access for assignment/exercise lot lookups.
    """
    _create_and_close_lots(orders, lot_manager, position_manager)
    _process_assignments_and_exercises(
        orders, assignment_stock_transactions, lot_manager, db_manager,
    )


# ---------------------------------------------------------------------------
# Lot creation and FIFO closing
# ---------------------------------------------------------------------------

def _create_and_close_lots(
    orders: List[Order],
    lot_manager: "LotManager",
    position_manager: "PositionInventoryManager",
) -> None:
    """For each order: create lots for openings, FIFO-close lots for closings.

    Rolling orders inherit chain_id from the lots they close.
    ``order_to_temp_chain`` and ``closing_order_to_chains`` are local
    variables — not instance state.
    """
    order_to_temp_chain: Dict[str, str] = {}
    closing_order_to_chains: Dict[str, Set[str]] = {}

    for order in orders:
        temp_chain_id = None

        # Opening orders get a new temporary chain_id
        if order.order_type == OrderType.OPENING:
            temp_chain_id = (
                f"{order.underlying}_OPENING_"
                f"{order.executed_at.strftime('%Y%m%d')}_"
                f"{order.order_id[:8]}"
            )
            order_to_temp_chain[order.order_id] = temp_chain_id

        # For closing/rolling orders, capture affected chains BEFORE closing
        if order.order_type in (OrderType.CLOSING, OrderType.ROLLING):
            affected_chains: Set[str] = set()
            for tx in order.closing_transactions:
                open_lots = lot_manager.get_open_lots(
                    account_number=tx.account_number,
                    symbol=tx.symbol,
                )
                for lot in open_lots:
                    if lot.chain_id:
                        affected_chains.add(lot.chain_id)

            if affected_chains:
                closing_order_to_chains[order.order_id] = affected_chains
                logger.debug(
                    "Order %s will close lots in chains: %s",
                    order.order_id, affected_chains,
                )

                # Rolling orders: new lots inherit chain from closed lots
                if order.order_type == OrderType.ROLLING:
                    temp_chain_id = next(iter(affected_chains))
                    order_to_temp_chain[order.order_id] = temp_chain_id
                    logger.debug(
                        "Rolling order %s will create new lots in chain: %s",
                        order.order_id, temp_chain_id,
                    )

        # Process each transaction in the order
        for idx, tx in enumerate(order.transactions):
            tx_dict = {
                "id": tx.id,
                "account_number": tx.account_number,
                "symbol": tx.symbol,
                "underlying_symbol": tx.underlying_symbol,
                "action": tx.action,
                "quantity": tx.quantity,
                "price": tx.price,
                "executed_at": (
                    tx.executed_at.isoformat() if tx.executed_at else ""
                ),
                "instrument_type": (
                    "EQUITY_OPTION" if tx.option_type else "EQUITY"
                ),
                "transaction_sub_type": tx.transaction_sub_type,
            }

            # Update legacy position inventory
            position_manager.update_position_from_transaction(tx_dict)

            if tx.is_opening:
                lot_manager.create_lot(
                    transaction=tx_dict,
                    chain_id=temp_chain_id or "",
                    leg_index=idx,
                    opening_order_id=order.order_id,
                )
            elif tx.is_closing:
                close_long = None
                if "SELL_TO_CLOSE" in (tx.action or ""):
                    close_long = True
                elif "BUY_TO_CLOSE" in (tx.action or ""):
                    close_long = False

                if tx.is_assignment:
                    closing_type = "ASSIGNMENT"
                elif tx.is_exercise:
                    closing_type = "EXERCISE"
                elif tx.is_expiration:
                    closing_type = "EXPIRATION"
                else:
                    closing_type = "MANUAL"

                lot_manager.close_lot_fifo(
                    account_number=tx.account_number,
                    symbol=tx.symbol,
                    quantity_to_close=abs(tx.quantity),
                    closing_price=tx.price,
                    closing_order_id=order.order_id,
                    closing_transaction_id=tx.id,
                    closing_date=tx.executed_at,
                    closing_type=closing_type,
                    close_long=close_long,
                )


# ---------------------------------------------------------------------------
# Assignment / exercise derived lots
# ---------------------------------------------------------------------------

def _process_assignments_and_exercises(
    orders: List[Order],
    assignment_stock_txs: List[Dict],
    lot_manager: "LotManager",
    db_manager: "DatabaseManager",
) -> None:
    """Match assignment/exercise option closings with stock transactions.

    Creates derived stock lots (for assignments) or closes existing stock
    lots (for exercises that sell shares).
    """
    if not assignment_stock_txs:
        return

    from src.database.models import PositionLot as PL, LotClosing as LC

    # Make a mutable copy so we can remove matched transactions
    remaining_stock_txs = list(assignment_stock_txs)

    # --- Assignments ---
    assignment_txs = [
        tx for order in orders for tx in order.transactions
        if tx.is_assignment and tx.option_type is not None
    ]

    if assignment_txs:
        logger.info(
            "Processing %d assignments with %d stock transactions",
            len(assignment_txs), len(remaining_stock_txs),
        )

    for assignment_tx in assignment_txs:
        underlying = assignment_tx.underlying_symbol

        matching_stock = _find_matching_stock(
            assignment_tx, remaining_stock_txs, underlying,
        )
        if not matching_stock:
            logger.warning(
                "No matching stock transaction found for assignment: %s",
                assignment_tx.symbol,
            )
            continue

        with db_manager.get_session() as session:
            result = (
                session.query(PL.id, PL.chain_id, PL.option_type, PL.strike)
                .join(LC, PL.id == LC.lot_id)
                .filter(
                    PL.account_number == assignment_tx.account_number,
                    PL.symbol == assignment_tx.symbol,
                    LC.closing_type == "ASSIGNMENT",
                    LC.resulting_lot_id.is_(None),
                )
                .order_by(LC.closing_date.desc())
                .first()
            )

        if not result:
            logger.warning(
                "No closed option lot found for assignment: %s",
                assignment_tx.symbol,
            )
            continue

        option_lot_id, chain_id, option_type, strike = result

        if not chain_id:
            logger.warning(
                "Option lot %s has no chain_id, skipping derived lot creation",
                option_lot_id,
            )
            continue

        stock_tx_dict = _stock_raw_to_dict(matching_stock)

        derived_lot_id = lot_manager.create_derived_lot(
            source_lot_id=option_lot_id,
            stock_transaction=stock_tx_dict,
            derivation_type="ASSIGNMENT",
            chain_id=chain_id,
        )

        logger.info(
            "Created derived stock lot %s from option lot %s via ASSIGNMENT",
            derived_lot_id, option_lot_id,
        )
        remaining_stock_txs.remove(matching_stock)

    # --- Exercises ---
    if not remaining_stock_txs:
        return

    exercise_txs = [
        tx for order in orders for tx in order.transactions
        if tx.is_exercise and tx.option_type is not None
    ]

    if not exercise_txs:
        return

    logger.info(
        "Processing %d exercises with %d stock transactions",
        len(exercise_txs), len(remaining_stock_txs),
    )

    for exercise_tx in exercise_txs:
        underlying = exercise_tx.underlying_symbol

        matching_stock = _find_matching_stock(
            exercise_tx, remaining_stock_txs, underlying,
        )
        if not matching_stock:
            logger.warning(
                "No matching stock transaction found for exercise: %s",
                exercise_tx.symbol,
            )
            continue

        with db_manager.get_session() as session:
            result = (
                session.query(
                    PL.id, PL.chain_id, PL.option_type, PL.strike,
                    LC.closing_order_id,
                )
                .join(LC, PL.id == LC.lot_id)
                .filter(
                    PL.account_number == exercise_tx.account_number,
                    PL.symbol == exercise_tx.symbol,
                    LC.closing_type == "EXERCISE",
                    LC.resulting_lot_id.is_(None),
                )
                .order_by(LC.closing_date.desc())
                .first()
            )

        if not result:
            logger.warning(
                "No closed option lot found for exercise: %s",
                exercise_tx.symbol,
            )
            continue

        option_lot_id, chain_id, option_type, strike, closing_order_id = result

        stock_action = (matching_stock.get("action") or "").upper()

        if "TO_CLOSE" in stock_action:
            # Exercise closes existing shares (e.g. long put -> STC)
            close_long = "SELL" in stock_action
            stock_executed_str = matching_stock.get("executed_at", "")
            try:
                stock_executed_dt = datetime.fromisoformat(
                    stock_executed_str.replace("Z", "+00:00")
                )
            except Exception:
                stock_executed_dt = exercise_tx.executed_at

            pnl, affected_lots = lot_manager.close_lot_fifo(
                account_number=matching_stock.get(
                    "account_number", exercise_tx.account_number
                ),
                symbol=matching_stock.get("symbol", underlying),
                quantity_to_close=abs(int(matching_stock.get("quantity", 0))),
                closing_price=float(matching_stock.get("price", 0)),
                closing_order_id=(
                    closing_order_id
                    or f"EXERCISE_{exercise_tx.symbol}"
                ),
                closing_transaction_id=str(matching_stock.get("id", "")),
                closing_date=stock_executed_dt,
                closing_type="EXERCISE",
                close_long=close_long,
            )

            logger.info(
                "Exercise closed %d stock lots via %s, P&L: $%.2f",
                len(affected_lots), exercise_tx.symbol, pnl,
            )

            # Link the exercise LotClosing to the affected stock lot
            if affected_lots:
                with db_manager.get_session() as session:
                    lc = (
                        session.query(LC)
                        .filter(
                            LC.lot_id == option_lot_id,
                            LC.closing_type == "EXERCISE",
                            LC.resulting_lot_id.is_(None),
                        )
                        .order_by(LC.closing_id.desc())
                        .first()
                    )
                    if lc:
                        lc.resulting_lot_id = affected_lots[0]

        elif "TO_OPEN" in stock_action:
            # Exercise opens new position (e.g. long call -> BTO shares)
            stock_tx_dict = _stock_raw_to_dict(matching_stock)

            raw_qty = abs(int(matching_stock.get("quantity", 0)))
            if "SELL" in stock_action:
                override_qty = -raw_qty
            else:
                override_qty = raw_qty

            derived_lot_id = lot_manager.create_derived_lot(
                source_lot_id=option_lot_id,
                stock_transaction=stock_tx_dict,
                derivation_type="EXERCISE",
                chain_id=chain_id or "",
                override_quantity=override_qty,
            )

            logger.info(
                "Created derived stock lot %s from exercise of option lot %s",
                derived_lot_id, option_lot_id,
            )
        else:
            logger.warning(
                "Unexpected stock action for exercise: %s", stock_action,
            )
            continue

        remaining_stock_txs.remove(matching_stock)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_matching_stock(
    option_tx,
    stock_txs: List[Dict],
    underlying: str,
) -> Dict | None:
    """Find a stock transaction matching an assignment/exercise option tx."""
    for stock_raw in stock_txs:
        stock_underlying = stock_raw.get(
            "underlying_symbol", stock_raw.get("symbol", "")
        )
        if stock_underlying != underlying:
            continue

        stock_executed_str = stock_raw.get("executed_at", "")
        try:
            stock_executed = datetime.fromisoformat(
                stock_executed_str.replace("Z", "+00:00")
            )
        except Exception:
            continue

        time_diff = abs(
            (option_tx.executed_at - stock_executed).total_seconds()
        )
        if time_diff > 60:
            continue

        expected_shares = abs(option_tx.quantity) * 100
        if abs(int(stock_raw.get("quantity", 0))) != expected_shares:
            continue

        return stock_raw

    return None


def _stock_raw_to_dict(stock_raw: Dict) -> Dict:
    """Convert a raw stock transaction to the dict format LotManager expects."""
    return {
        "id": str(stock_raw.get("id", "")),
        "account_number": stock_raw.get("account_number", ""),
        "symbol": stock_raw.get("symbol", ""),
        "underlying_symbol": stock_raw.get(
            "underlying_symbol", stock_raw.get("symbol", "")
        ),
        "quantity": int(stock_raw.get("quantity", 0)),
        "price": float(stock_raw.get("price", 0)),
        "executed_at": stock_raw.get("executed_at", ""),
    }
