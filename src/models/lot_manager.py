"""
Lot Manager for V3 Position Tracking
Implements lot-based position tracking with FIFO matching and assignment/exercise handling
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class Lot:
    """Represents a position lot"""
    id: int
    transaction_id: str
    account_number: str
    symbol: str
    underlying: str
    instrument_type: str
    option_type: Optional[str]
    strike: Optional[float]
    expiration: Optional[date]
    quantity: int  # Original quantity (negative for short)
    entry_price: float
    entry_date: datetime
    remaining_quantity: int
    original_quantity: int
    chain_id: Optional[str]
    leg_index: int
    opening_order_id: Optional[str]
    derived_from_lot_id: Optional[int]
    derivation_type: Optional[str]  # ASSIGNMENT, EXERCISE
    status: str  # OPEN, CLOSED, PARTIAL

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_closed(self) -> bool:
        return self.remaining_quantity == 0

    @property
    def is_option(self) -> bool:
        return self.option_type is not None


@dataclass
class LotClosing:
    """Represents a closing record for a lot"""
    closing_id: int
    lot_id: int
    closing_order_id: str
    closing_transaction_id: Optional[str]
    quantity_closed: int
    closing_price: float
    closing_date: datetime
    closing_type: str  # MANUAL, EXPIRATION, ASSIGNMENT, EXERCISE
    realized_pnl: float
    resulting_lot_id: Optional[int]  # For assignment: stock lot created


class LotManager:
    """Centralized lot operations for V3 position tracking"""

    def __init__(self, db_manager):
        self.db = db_manager

    def create_lot(
        self,
        transaction: Dict,
        chain_id: str,
        leg_index: int = 0,
        opening_order_id: Optional[str] = None
    ) -> int:
        """
        Create a new lot from an opening transaction.

        Args:
            transaction: Transaction dict with id, account_number, symbol, action, quantity, price, etc.
            chain_id: The chain this lot belongs to
            leg_index: Index within multi-leg strategy (0 for single leg)
            opening_order_id: The order that opened this lot

        Returns:
            The ID of the created lot
        """
        symbol = transaction.get('symbol', '')
        underlying = transaction.get('underlying_symbol', '')
        if not underlying and ' ' in symbol:
            underlying = symbol.split()[0]
        elif not underlying:
            underlying = symbol

        quantity = int(transaction.get('quantity', 0))
        action = (transaction.get('action') or '').upper()

        # Determine quantity sign based on action
        if 'SELL_TO_OPEN' in action:
            quantity = -abs(quantity)  # Short position
        else:
            quantity = abs(quantity)  # Long position

        # Parse option details from symbol if available
        option_type = None
        strike = None
        expiration = None
        instrument_type = transaction.get('instrument_type', '')

        if 'OPTION' in instrument_type.upper() and ' ' in symbol:
            parts = symbol.split()
            if len(parts) >= 2:
                option_part = parts[1]
                if len(option_part) >= 8:
                    # Extract date (YYMMDD)
                    date_str = option_part[:6]
                    try:
                        expiration = datetime.strptime('20' + date_str, '%Y%m%d').date()
                    except:
                        pass

                    # Extract type (C or P)
                    if len(option_part) > 6:
                        option_type = 'Call' if option_part[6] == 'C' else 'Put'

                    # Extract strike
                    if len(option_part) > 7:
                        try:
                            strike = float(option_part[7:]) / 1000
                        except:
                            pass

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO position_lots (
                    transaction_id, account_number, symbol, underlying,
                    instrument_type, option_type, strike, expiration,
                    quantity, entry_price, entry_date, remaining_quantity,
                    original_quantity, chain_id, leg_index, opening_order_id,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (
                transaction.get('id', ''),
                transaction.get('account_number', ''),
                symbol,
                underlying,
                instrument_type,
                option_type,
                strike,
                expiration,
                quantity,
                float(transaction.get('price', 0)),
                transaction.get('executed_at', ''),
                quantity,  # remaining = original initially
                abs(quantity),  # original_quantity is always positive
                chain_id,
                leg_index,
                opening_order_id
            ))

            lot_id = cursor.lastrowid
            logger.debug(f"Created lot {lot_id}: {symbol} qty={quantity} chain={chain_id}")
            return lot_id

    def close_lot_fifo(
        self,
        account_number: str,
        symbol: str,
        quantity_to_close: int,
        closing_price: float,
        closing_order_id: str,
        closing_transaction_id: Optional[str],
        closing_date: datetime,
        closing_type: str = 'MANUAL',
        chain_id: Optional[str] = None,
        close_long: Optional[bool] = None
    ) -> Tuple[float, List[int]]:
        """
        Close lots using FIFO matching.

        Args:
            account_number: Account to match against
            symbol: Symbol to close
            quantity_to_close: Absolute quantity to close
            closing_price: Price at closing
            closing_order_id: Order that's closing
            closing_transaction_id: Transaction ID for the closing
            closing_date: When the close occurred
            closing_type: MANUAL, EXPIRATION, ASSIGNMENT, EXERCISE
            chain_id: Optional chain to limit matching to
            close_long: Direction filter for equity lots.
                True = only match lots where quantity > 0 (STC closes long).
                False = only match lots where quantity < 0 (BTC closes short).
                None = match any direction (default, backward-compatible).

        Returns:
            Tuple of (total realized P&L, list of affected lot IDs)
        """
        total_pnl = 0.0
        affected_lots = []
        remaining_to_close = abs(quantity_to_close)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Get open lots using FIFO (ordered by entry date)
            direction_clause = ""
            if close_long is True:
                direction_clause = " AND quantity > 0"
            elif close_long is False:
                direction_clause = " AND quantity < 0"

            if chain_id:
                cursor.execute(f"""
                    SELECT id, quantity, entry_price, remaining_quantity, option_type
                    FROM position_lots
                    WHERE account_number = ? AND symbol = ? AND chain_id = ?
                    AND remaining_quantity != 0 AND status != 'CLOSED'
                    {direction_clause}
                    ORDER BY entry_date ASC
                """, (account_number, symbol, chain_id))
            else:
                cursor.execute(f"""
                    SELECT id, quantity, entry_price, remaining_quantity, option_type
                    FROM position_lots
                    WHERE account_number = ? AND symbol = ?
                    AND remaining_quantity != 0 AND status != 'CLOSED'
                    {direction_clause}
                    ORDER BY entry_date ASC
                """, (account_number, symbol))

            lots = cursor.fetchall()

            for lot_id, lot_quantity, entry_price, remaining_qty, option_type in lots:
                if remaining_to_close <= 0:
                    break

                # Calculate how much of this lot to close
                lot_available = abs(remaining_qty)
                close_amount = min(remaining_to_close, lot_available)

                # Determine multiplier (100 for options, 1 for stock)
                multiplier = 100 if option_type else 1

                # Calculate P&L for this portion
                if lot_quantity > 0:
                    # Long position: P&L = (closing - entry) * quantity * multiplier
                    pnl = (closing_price - entry_price) * close_amount * multiplier
                else:
                    # Short position: P&L = (entry - closing) * quantity * multiplier
                    pnl = (entry_price - closing_price) * close_amount * multiplier

                total_pnl += pnl

                # Update lot remaining quantity
                new_remaining = abs(remaining_qty) - close_amount
                if lot_quantity < 0:
                    new_remaining = -new_remaining

                new_status = 'CLOSED' if new_remaining == 0 else 'PARTIAL'

                cursor.execute("""
                    UPDATE position_lots
                    SET remaining_quantity = ?, status = ?
                    WHERE id = ?
                """, (new_remaining, new_status, lot_id))

                # Create lot_closings record
                cursor.execute("""
                    INSERT INTO lot_closings (
                        lot_id, closing_order_id, closing_transaction_id,
                        quantity_closed, closing_price, closing_date,
                        closing_type, realized_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lot_id,
                    closing_order_id,
                    closing_transaction_id,
                    close_amount,
                    closing_price,
                    closing_date,
                    closing_type,
                    pnl
                ))

                affected_lots.append(lot_id)
                remaining_to_close -= close_amount

                logger.debug(f"Closed {close_amount} from lot {lot_id}, P&L: ${pnl:.2f}")

        return total_pnl, affected_lots

    def create_derived_lot(
        self,
        source_lot_id: int,
        stock_transaction: Dict,
        derivation_type: str,  # ASSIGNMENT or EXERCISE
        chain_id: str
    ) -> int:
        """
        Create a derived lot (stock from option assignment/exercise).

        Args:
            source_lot_id: The option lot that was assigned/exercised
            stock_transaction: The stock transaction created
            derivation_type: ASSIGNMENT or EXERCISE
            chain_id: Chain to link to

        Returns:
            ID of the newly created stock lot
        """
        symbol = stock_transaction.get('symbol', '')
        underlying = stock_transaction.get('underlying_symbol', symbol)

        raw_quantity = abs(int(stock_transaction.get('quantity', 0)))

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Get source lot info to determine direction and entry price
            cursor.execute("""
                SELECT option_type, strike FROM position_lots WHERE id = ?
            """, (source_lot_id,))
            source_info = cursor.fetchone()

            # The strike price becomes the stock entry price
            entry_price = float(source_info[1]) if source_info and source_info[1] else float(stock_transaction.get('price', 0))

            # Determine direction from source option type:
            #   Short put assigned  → user buys shares  → positive quantity
            #   Short call assigned → user sells/delivers shares → negative quantity
            source_option_type = source_info[0] if source_info else None
            if source_option_type and source_option_type.upper() == 'CALL':
                quantity = -raw_quantity
            else:
                quantity = raw_quantity

            cursor.execute("""
                INSERT INTO position_lots (
                    transaction_id, account_number, symbol, underlying,
                    instrument_type, option_type, strike, expiration,
                    quantity, entry_price, entry_date, remaining_quantity,
                    original_quantity, chain_id, leg_index, opening_order_id,
                    derived_from_lot_id, derivation_type, status
                ) VALUES (?, ?, ?, ?, 'EQUITY', NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, 'OPEN')
            """, (
                stock_transaction.get('id', ''),
                stock_transaction.get('account_number', ''),
                symbol,
                underlying,
                quantity,
                entry_price,
                stock_transaction.get('executed_at', ''),
                quantity,  # remaining = original
                abs(quantity),
                chain_id,
                source_lot_id,
                derivation_type
            ))

            lot_id = cursor.lastrowid

            # Update the lot_closings to reference the resulting lot
            cursor.execute("""
                UPDATE lot_closings
                SET resulting_lot_id = ?
                WHERE lot_id = ? AND closing_type = ?
                ORDER BY closing_id DESC LIMIT 1
            """, (lot_id, source_lot_id, derivation_type))

            logger.info(f"Created derived lot {lot_id} from lot {source_lot_id} via {derivation_type}")
            return lot_id

    def get_open_lots(
        self,
        account_number: str,
        symbol: Optional[str] = None,
        chain_id: Optional[str] = None,
        underlying: Optional[str] = None
    ) -> List[Lot]:
        """
        Get all open lots matching criteria.

        Args:
            account_number: Account to query
            symbol: Optional symbol filter
            chain_id: Optional chain filter
            underlying: Optional underlying filter

        Returns:
            List of Lot objects
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, transaction_id, account_number, symbol, underlying,
                       instrument_type, option_type, strike, expiration,
                       quantity, entry_price, entry_date, remaining_quantity,
                       original_quantity, chain_id, leg_index, opening_order_id,
                       derived_from_lot_id, derivation_type, status
                FROM position_lots
                WHERE account_number = ? AND remaining_quantity != 0 AND status != 'CLOSED'
            """
            params = [account_number]

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            if chain_id:
                query += " AND chain_id = ?"
                params.append(chain_id)

            if underlying:
                query += " AND underlying = ?"
                params.append(underlying)

            query += " ORDER BY entry_date ASC"

            cursor.execute(query, params)

            lots = []
            for row in cursor.fetchall():
                lots.append(self._row_to_lot(row))

            return lots

    def get_lots_for_groups_batch(self, group_ids: List[str]) -> Dict[str, List[Lot]]:
        """
        Get lots for multiple position groups in a single query.
        Joins position_lots with position_group_lots using transaction_id.

        Returns:
            Dict keyed by group_id, each value a list of Lot objects
        """
        if not group_ids:
            return {}

        result = {gid: [] for gid in group_ids}

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?' for _ in group_ids])
            cursor.execute(f"""
                SELECT pgl.group_id,
                       pl.id, pl.transaction_id, pl.account_number, pl.symbol, pl.underlying,
                       pl.instrument_type, pl.option_type, pl.strike, pl.expiration,
                       pl.quantity, pl.entry_price, pl.entry_date, pl.remaining_quantity,
                       pl.original_quantity, pl.chain_id, pl.leg_index, pl.opening_order_id,
                       pl.derived_from_lot_id, pl.derivation_type, pl.status
                FROM position_group_lots pgl
                JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
                WHERE pgl.group_id IN ({placeholders})
                ORDER BY pl.entry_date ASC, pl.leg_index ASC
            """, group_ids)

            for row in cursor.fetchall():
                group_id = row[0]
                lot = self._row_to_lot(row[1:])  # Skip group_id column
                result[group_id].append(lot)

        return result

    def get_lot_closings_batch(self, lot_ids: List[int]) -> Dict[int, List[LotClosing]]:
        """
        Get closings for multiple lots in a single query.

        Returns:
            Dict keyed by lot_id, each value a list of LotClosing objects
        """
        if not lot_ids:
            return {}

        result = {lid: [] for lid in lot_ids}

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?' for _ in lot_ids])
            cursor.execute(f"""
                SELECT closing_id, lot_id, closing_order_id, closing_transaction_id,
                       quantity_closed, closing_price, closing_date, closing_type,
                       realized_pnl, resulting_lot_id
                FROM lot_closings
                WHERE lot_id IN ({placeholders})
                ORDER BY closing_date ASC
            """, lot_ids)

            for row in cursor.fetchall():
                closing_date = row[6]
                if isinstance(closing_date, str):
                    closing_date = datetime.fromisoformat(closing_date.replace('Z', '+00:00'))

                closing = LotClosing(
                    closing_id=row[0],
                    lot_id=row[1],
                    closing_order_id=row[2],
                    closing_transaction_id=row[3],
                    quantity_closed=row[4],
                    closing_price=row[5],
                    closing_date=closing_date,
                    closing_type=row[7],
                    realized_pnl=row[8],
                    resulting_lot_id=row[9]
                )
                result[row[1]].append(closing)

        return result

    def get_unassigned_lots(self, account_number: Optional[str] = None) -> List[Lot]:
        """
        Find lots whose transaction_id is NOT in position_group_lots.
        Used for seeding new lots into groups.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT pl.id, pl.transaction_id, pl.account_number, pl.symbol, pl.underlying,
                       pl.instrument_type, pl.option_type, pl.strike, pl.expiration,
                       pl.quantity, pl.entry_price, pl.entry_date, pl.remaining_quantity,
                       pl.original_quantity, pl.chain_id, pl.leg_index, pl.opening_order_id,
                       pl.derived_from_lot_id, pl.derivation_type, pl.status
                FROM position_lots pl
                LEFT JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
                WHERE pgl.transaction_id IS NULL
            """
            params = []

            if account_number:
                query += " AND pl.account_number = ?"
                params.append(account_number)

            query += " ORDER BY pl.entry_date ASC"

            cursor.execute(query, params)

            lots = []
            for row in cursor.fetchall():
                lots.append(self._row_to_lot(row))

            return lots

    def get_lots_for_chain(self, chain_id: str, include_derived: bool = True) -> List[Lot]:
        """
        Get all lots belonging to a chain.

        Args:
            chain_id: Chain ID to query
            include_derived: Whether to include derived (assignment) lots

        Returns:
            List of Lot objects
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if include_derived:
                cursor.execute("""
                    SELECT id, transaction_id, account_number, symbol, underlying,
                           instrument_type, option_type, strike, expiration,
                           quantity, entry_price, entry_date, remaining_quantity,
                           original_quantity, chain_id, leg_index, opening_order_id,
                           derived_from_lot_id, derivation_type, status
                    FROM position_lots
                    WHERE chain_id = ?
                    ORDER BY entry_date ASC, leg_index ASC
                """, (chain_id,))
            else:
                cursor.execute("""
                    SELECT id, transaction_id, account_number, symbol, underlying,
                           instrument_type, option_type, strike, expiration,
                           quantity, entry_price, entry_date, remaining_quantity,
                           original_quantity, chain_id, leg_index, opening_order_id,
                           derived_from_lot_id, derivation_type, status
                    FROM position_lots
                    WHERE chain_id = ? AND derived_from_lot_id IS NULL
                    ORDER BY entry_date ASC, leg_index ASC
                """, (chain_id,))

            lots = []
            for row in cursor.fetchall():
                lots.append(self._row_to_lot(row))

            return lots

    def get_lot_by_id(self, lot_id: int) -> Optional[Lot]:
        """Get a specific lot by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, transaction_id, account_number, symbol, underlying,
                       instrument_type, option_type, strike, expiration,
                       quantity, entry_price, entry_date, remaining_quantity,
                       original_quantity, chain_id, leg_index, opening_order_id,
                       derived_from_lot_id, derivation_type, status
                FROM position_lots
                WHERE id = ?
            """, (lot_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_lot(row)
            return None

    def get_lot_closings(self, lot_id: int) -> List[LotClosing]:
        """Get all closing records for a lot"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT closing_id, lot_id, closing_order_id, closing_transaction_id,
                       quantity_closed, closing_price, closing_date, closing_type,
                       realized_pnl, resulting_lot_id
                FROM lot_closings
                WHERE lot_id = ?
                ORDER BY closing_date ASC
            """, (lot_id,))

            closings = []
            for row in cursor.fetchall():
                closing_date = row[6]
                if isinstance(closing_date, str):
                    closing_date = datetime.fromisoformat(closing_date.replace('Z', '+00:00'))

                closings.append(LotClosing(
                    closing_id=row[0],
                    lot_id=row[1],
                    closing_order_id=row[2],
                    closing_transaction_id=row[3],
                    quantity_closed=row[4],
                    closing_price=row[5],
                    closing_date=closing_date,
                    closing_type=row[7],
                    realized_pnl=row[8],
                    resulting_lot_id=row[9]
                ))

            return closings

    def get_realized_pnl_for_chain(self, chain_id: str) -> float:
        """Calculate total realized P&L for a chain from lot closings"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(lc.realized_pnl), 0)
                FROM lot_closings lc
                JOIN position_lots pl ON lc.lot_id = pl.id
                WHERE pl.chain_id = ?
            """, (chain_id,))
            result = cursor.fetchone()
            return float(result[0]) if result else 0.0

    def update_lot_chain(self, lot_id: int, chain_id: str):
        """Update the chain_id for a lot"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE position_lots SET chain_id = ? WHERE id = ?
            """, (chain_id, lot_id))

    def clear_all_lots(self, underlyings: set = None):
        """Clear lots. If underlyings is provided, only clear lots for those symbols."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if underlyings:
                placeholders = ','.join(['?' for _ in underlyings])
                cursor.execute(f"""
                    DELETE FROM lot_closings WHERE lot_id IN (
                        SELECT id FROM position_lots WHERE underlying IN ({placeholders})
                    )
                """, list(underlyings))
                cursor.execute(f"DELETE FROM position_lots WHERE underlying IN ({placeholders})",
                               list(underlyings))
                logger.info(f"Cleared lots and closings for {len(underlyings)} underlyings")
            else:
                cursor.execute("DELETE FROM lot_closings")
                cursor.execute("DELETE FROM position_lots")
                logger.warning("Cleared all lots and closings")

    def _row_to_lot(self, row) -> Lot:
        """Convert database row to Lot object"""
        (id, transaction_id, account_number, symbol, underlying,
         instrument_type, option_type, strike, expiration,
         quantity, entry_price, entry_date, remaining_quantity,
         original_quantity, chain_id, leg_index, opening_order_id,
         derived_from_lot_id, derivation_type, status) = row

        # Parse dates
        if expiration and isinstance(expiration, str):
            expiration = datetime.strptime(expiration, '%Y-%m-%d').date()

        if isinstance(entry_date, str):
            entry_date = datetime.fromisoformat(entry_date.replace('Z', '+00:00'))

        return Lot(
            id=id,
            transaction_id=transaction_id,
            account_number=account_number,
            symbol=symbol,
            underlying=underlying or '',
            instrument_type=instrument_type or '',
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            quantity=quantity,
            entry_price=entry_price,
            entry_date=entry_date,
            remaining_quantity=remaining_quantity,
            original_quantity=original_quantity or abs(quantity),
            chain_id=chain_id,
            leg_index=leg_index or 0,
            opening_order_id=opening_order_id,
            derived_from_lot_id=derived_from_lot_id,
            derivation_type=derivation_type,
            status=status or 'OPEN'
        )
