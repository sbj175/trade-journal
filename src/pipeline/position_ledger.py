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
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src.models.order_processor import Order, OrderType

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)

__all__ = ["process_lots"]

# Cash-settled index options — no stock delivery on assignment/exercise
_CASH_SETTLED = frozenset({
    "SPX", "SPXW", "NDX", "VIX", "RUT", "XSP", "DJX", "OEX", "XEO",
})


def _skip_stock_delivery(underlying: str) -> bool:
    """Return True if this option doesn't deliver stock on assignment/exercise.

    Covers:
    - Cash-settled index options (SPX, NDX, VIX, etc.)
    - Adjusted options (symbol ends with digit, e.g. WOLF1) — non-standard
      deliverables that don't follow the 100-share convention
    """
    u = (underlying or "").upper()
    if u in _CASH_SETTLED:
        return True
    if u and u[-1].isdigit():
        return True
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_lots(
    orders: List[Order],
    assignment_stock_transactions: List[Dict],
    lot_manager: "LotManager",
    db_manager: "DatabaseManager",
) -> None:
    """Stage 3: create/close lots in a single chronological pass.

    For each order (already sorted by executed_at):
      - OPENING transactions create new lots
      - CLOSING transactions FIFO-close matching lots
      - Assignment/exercise closings on options immediately create (or close)
        derived stock lots, so subsequent orders can close those shares normally

    Parameters
    ----------
    orders : list[Order]
        Chronologically sorted Order objects from Stage 2 (order_assembler).
    assignment_stock_transactions : list[dict]
        Raw stock transaction dicts that were separated during preprocessing
        (stock transactions resulting from assignment/exercise, no order_id).
    lot_manager : LotManager
        Manages position_lots and lot_closings tables.
    db_manager : DatabaseManager
        Database access for assignment/exercise lot lookups.
    """
    # Mutable copy — items removed as they are matched to assignments/exercises
    remaining_stock_txs = list(assignment_stock_transactions)

    # Deferred TO_CLOSE events: when a spread settles simultaneously, the
    # TO_CLOSE stock action may be processed before the corresponding TO_OPEN
    # creates the shares.  We defer and retry after the main pass.
    deferred_closings: List[Dict] = []

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

                # ── Inline assignment/exercise handling ──────────────
                # When an option is closed by assignment or exercise,
                # create the derived stock lot NOW so that later orders
                # in this same pass can close those shares normally.
                if tx.option_type and tx.is_assignment:
                    _create_assignment_derived_lot(
                        tx, remaining_stock_txs, lot_manager, db_manager,
                        deferred_closings,
                    )
                elif tx.option_type and tx.is_exercise:
                    _handle_exercise_inline(
                        tx, remaining_stock_txs, lot_manager, db_manager,
                        deferred_closings,
                    )

    # Retry deferred TO_CLOSE events (spread settlement ordering)
    for deferred in deferred_closings:
        _process_deferred_closing(deferred, lot_manager, db_manager)


# ---------------------------------------------------------------------------
# Inline assignment / exercise handlers
# ---------------------------------------------------------------------------

def _create_assignment_derived_lot(
    assignment_tx,
    remaining_stock_txs: List[Dict],
    lot_manager: "LotManager",
    db_manager: "DatabaseManager",
    deferred_closings: List[Dict],
) -> None:
    """Create (or close) a derived stock lot after an option assignment closes.

    Like _handle_exercise_inline, inspects the stock action:
    - TO_CLOSE: close existing shares via FIFO (e.g. short call assigned when
      shares already held → STC)
    - TO_OPEN: create a new derived lot (the common case)
    - Fallback: infer direction from option_type (legacy data without action)
    """
    from src.database.models import PositionLot as PL, LotClosing as LC

    underlying = assignment_tx.underlying_symbol

    if _skip_stock_delivery(underlying):
        logger.debug(
            "Skipping stock delivery for assignment: %s (cash-settled or adjusted)",
            assignment_tx.symbol,
        )
        return

    # Query the option lot FIRST so we can pass strike to _find_matching_stock
    with db_manager.get_session() as session:
        result = (
            session.query(
                PL.id, PL.chain_id, PL.option_type, PL.strike,
                LC.closing_order_id,
            )
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
        return

    option_lot_id, chain_id, option_type, strike, closing_order_id = result

    matching_stock = _find_matching_stock(
        assignment_tx, remaining_stock_txs, underlying, strike=strike,
    )
    if not matching_stock:
        logger.warning(
            "No matching stock transaction found for assignment: %s",
            assignment_tx.symbol,
        )
        return

    if not chain_id:
        logger.warning(
            "Option lot %s has no chain_id, skipping derived lot creation",
            option_lot_id,
        )
        return

    stock_action = (matching_stock.get("action") or "").upper()

    if "TO_CLOSE" in stock_action:
        # Assignment closes existing shares (e.g. short call assigned
        # while holding long shares → STC)
        close_long = "SELL" in stock_action
        stock_executed_str = matching_stock.get("executed_at", "")
        try:
            stock_executed_dt = datetime.fromisoformat(
                stock_executed_str.replace("Z", "+00:00")
            )
        except Exception:
            stock_executed_dt = assignment_tx.executed_at

        pnl, affected_lots = lot_manager.close_lot_fifo(
            account_number=matching_stock.get(
                "account_number", assignment_tx.account_number
            ),
            symbol=matching_stock.get("symbol", underlying),
            quantity_to_close=abs(int(matching_stock.get("quantity", 0))),
            closing_price=float(matching_stock.get("price", 0)),
            closing_order_id=(
                closing_order_id
                or f"ASSIGNMENT_{assignment_tx.symbol}"
            ),
            closing_transaction_id=str(matching_stock.get("id", "")),
            closing_date=stock_executed_dt,
            closing_type="ASSIGNMENT",
            close_long=close_long,
        )

        if not affected_lots:
            # Shares don't exist yet — defer until after all events are
            # processed (spread settlement: TO_OPEN may not have run yet).
            deferred_closings.append({
                "matching_stock": matching_stock,
                "option_lot_id": option_lot_id,
                "closing_type": "ASSIGNMENT",
                "close_long": close_long,
                "closing_order_id": (
                    closing_order_id
                    or f"ASSIGNMENT_{assignment_tx.symbol}"
                ),
            })
            logger.debug(
                "Deferred assignment TO_CLOSE for %s (no shares yet)",
                assignment_tx.symbol,
            )
            return  # Don't remove stock tx — retry later

        logger.info(
            "Assignment closed %d stock lots via %s, P&L: $%.2f",
            len(affected_lots), assignment_tx.symbol, pnl,
        )

        # Link the assignment LotClosing to the affected stock lot
        with db_manager.get_session() as session:
            lc = (
                session.query(LC)
                .filter(
                    LC.lot_id == option_lot_id,
                    LC.closing_type == "ASSIGNMENT",
                    LC.resulting_lot_id.is_(None),
                )
                .order_by(LC.closing_id.desc())
                .first()
            )
            if lc:
                lc.resulting_lot_id = affected_lots[0]

    elif "TO_OPEN" in stock_action:
        # Assignment opens new position (the common case)
        stock_tx_dict = _stock_raw_to_dict(matching_stock)

        raw_qty = abs(int(matching_stock.get("quantity", 0)))
        if "SELL" in stock_action:
            override_qty = -raw_qty
        else:
            override_qty = raw_qty

        derived_lot_id = lot_manager.create_derived_lot(
            source_lot_id=option_lot_id,
            stock_transaction=stock_tx_dict,
            derivation_type="ASSIGNMENT",
            chain_id=chain_id,
            override_quantity=override_qty,
        )

        logger.info(
            "Created derived stock lot %s from option lot %s via ASSIGNMENT",
            derived_lot_id, option_lot_id,
        )
    else:
        # Fallback: infer direction from option_type (legacy data)
        stock_tx_dict = _stock_raw_to_dict(matching_stock)

        derived_lot_id = lot_manager.create_derived_lot(
            source_lot_id=option_lot_id,
            stock_transaction=stock_tx_dict,
            derivation_type="ASSIGNMENT",
            chain_id=chain_id,
        )

        logger.info(
            "Created derived stock lot %s from option lot %s via ASSIGNMENT (fallback)",
            derived_lot_id, option_lot_id,
        )

    remaining_stock_txs.remove(matching_stock)


def _handle_exercise_inline(
    exercise_tx,
    remaining_stock_txs: List[Dict],
    lot_manager: "LotManager",
    db_manager: "DatabaseManager",
    deferred_closings: List[Dict],
) -> None:
    """Handle an exercise-derived stock lot immediately after the option closes."""
    from src.database.models import PositionLot as PL, LotClosing as LC

    underlying = exercise_tx.underlying_symbol

    if _skip_stock_delivery(underlying):
        logger.debug(
            "Skipping stock delivery for exercise: %s (cash-settled or adjusted)",
            exercise_tx.symbol,
        )
        return

    # Query the option lot FIRST so we can pass strike to _find_matching_stock
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
        return

    option_lot_id, chain_id, option_type, strike, closing_order_id = result

    matching_stock = _find_matching_stock(
        exercise_tx, remaining_stock_txs, underlying, strike=strike,
    )
    if not matching_stock:
        logger.warning(
            "No matching stock transaction found for exercise: %s",
            exercise_tx.symbol,
        )
        return

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

        if not affected_lots:
            # Shares don't exist yet — defer until after all events are
            # processed (spread settlement: TO_OPEN may not have run yet).
            deferred_closings.append({
                "matching_stock": matching_stock,
                "option_lot_id": option_lot_id,
                "closing_type": "EXERCISE",
                "close_long": close_long,
                "closing_order_id": (
                    closing_order_id
                    or f"EXERCISE_{exercise_tx.symbol}"
                ),
            })
            logger.debug(
                "Deferred exercise TO_CLOSE for %s (no shares yet)",
                exercise_tx.symbol,
            )
            return  # Don't remove stock tx — retry later

        logger.info(
            "Exercise closed %d stock lots via %s, P&L: $%.2f",
            len(affected_lots), exercise_tx.symbol, pnl,
        )

        # Link the exercise LotClosing to the affected stock lot
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
        return

    remaining_stock_txs.remove(matching_stock)


# ---------------------------------------------------------------------------
# Deferred closing retry
# ---------------------------------------------------------------------------

def _process_deferred_closing(
    deferred: Dict,
    lot_manager: "LotManager",
    db_manager: "DatabaseManager",
) -> None:
    """Retry a TO_CLOSE that was deferred because shares didn't exist yet.

    This handles spread settlement where TO_OPEN hadn't been processed when
    the TO_CLOSE first ran.
    """
    from src.database.models import LotClosing as LC

    matching_stock = deferred["matching_stock"]
    option_lot_id = deferred["option_lot_id"]
    closing_type = deferred["closing_type"]
    close_long = deferred["close_long"]
    closing_order_id = deferred["closing_order_id"]

    stock_executed_str = matching_stock.get("executed_at", "")
    try:
        stock_executed_dt = datetime.fromisoformat(
            stock_executed_str.replace("Z", "+00:00")
        )
    except Exception:
        stock_executed_dt = datetime.now()

    pnl, affected_lots = lot_manager.close_lot_fifo(
        account_number=matching_stock.get("account_number", ""),
        symbol=matching_stock.get("symbol", ""),
        quantity_to_close=abs(int(matching_stock.get("quantity", 0))),
        closing_price=float(matching_stock.get("price", 0)),
        closing_order_id=closing_order_id,
        closing_transaction_id=str(matching_stock.get("id", "")),
        closing_date=stock_executed_dt,
        closing_type=closing_type,
        close_long=close_long,
    )

    if affected_lots:
        logger.info(
            "Deferred %s closed %d stock lots, P&L: $%.2f",
            closing_type, len(affected_lots), pnl,
        )

        # Link the option LotClosing to the affected stock lot
        with db_manager.get_session() as session:
            lc = (
                session.query(LC)
                .filter(
                    LC.lot_id == option_lot_id,
                    LC.closing_type == closing_type,
                    LC.resulting_lot_id.is_(None),
                )
                .order_by(LC.closing_id.desc())
                .first()
            )
            if lc:
                lc.resulting_lot_id = affected_lots[0]
    else:
        logger.warning(
            "Deferred %s retry still found no shares to close for stock tx %s",
            closing_type, matching_stock.get("id", "?"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_matching_stock(
    option_tx,
    stock_txs: List[Dict],
    underlying: str,
    *,
    strike: Optional[float] = None,
) -> Optional[Dict]:
    """Find a stock transaction matching an assignment/exercise option tx.

    When multiple candidates match (same underlying, time, quantity), prefer
    the one whose price equals the option's strike.  This prevents
    cross-matching when two option events settle simultaneously (e.g. spread
    settlement: two stock txs for the same underlying at the same time).
    """
    candidates: List[Dict] = []

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

        candidates.append(stock_raw)

    if not candidates:
        return None

    # Single match — return it directly
    if len(candidates) == 1:
        return candidates[0]

    # Multiple matches — prefer the one whose price equals the strike
    if strike is not None:
        for c in candidates:
            if float(c.get("price", 0)) == strike:
                return c

    # Still ambiguous — return first match (original behavior)
    return candidates[0]


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
