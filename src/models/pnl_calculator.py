"""
P&L Calculator
Implements P&L calculation based on position inventory and FIFO matching
Enhanced with lot-based calculations for accurate chain P&L
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
from decimal import Decimal
import logging

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from src.database.models import PositionLot as PositionLotModel

if TYPE_CHECKING:
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)


@dataclass
class PnLResult:
    """Result of P&L calculation"""
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    
    def __post_init__(self):
        self.total_pnl = self.realized_pnl + self.unrealized_pnl


@dataclass
class PositionLot:
    """Represents a specific lot for FIFO tracking"""
    transaction_id: str
    quantity: int  # Can be negative for short
    entry_price: float
    entry_date: datetime
    symbol: str
    account_number: str


class PnLCalculator:
    """Calculates P&L using FIFO matching and position inventory

    Enhanced with lot-based calculations when LotManager is provided.
    Falls back to legacy position-based calculations otherwise.
    """

    def __init__(self, db_manager, position_manager, lot_manager: Optional['LotManager'] = None):
        self.db = db_manager
        self.position_manager = position_manager
        self.lot_manager = lot_manager
        self._use_lots = lot_manager is not None
        self._create_lots_table_if_not_exists()
    
    def _create_lots_table_if_not_exists(self):
        """Ensure position_lots table exists (legacy DDL fallback).

        Table is also defined in models.py and created by the main
        initialize_database() flow.  This is kept as a safety net for
        standalone scripts.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL,
                    account_number TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_date TIMESTAMP NOT NULL,
                    remaining_quantity INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(transaction_id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_lots_account_symbol
                ON position_lots(account_number, symbol)
            """)
    
    def record_opening_lot(self, transaction: Dict):
        """Record a new opening lot for FIFO tracking"""
        quantity = int(transaction.get('quantity', 0))
        action = transaction.get('action', '').upper()

        # Determine quantity sign based on action
        if 'SELL_TO_OPEN' in action:
            quantity = -abs(quantity)  # Short position
        else:
            quantity = abs(quantity)  # Long position

        values = dict(
            transaction_id=transaction.get('id', ''),
            account_number=transaction.get('account_number', ''),
            symbol=transaction.get('symbol', ''),
            quantity=quantity,
            entry_price=float(transaction.get('price', 0)),
            entry_date=transaction.get('executed_at', ''),
            remaining_quantity=quantity,  # Initially, remaining = total
        )

        with self.db.get_session() as session:
            stmt = sqlite_insert(PositionLotModel).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[PositionLotModel.transaction_id],
                set_={k: stmt.excluded[k] for k in values},
            )
            session.execute(stmt)
    
    def calculate_realized_pnl_for_closing(self, closing_transaction: Dict) -> float:
        """
        Calculate realized P&L for a closing transaction using FIFO
        Returns the realized P&L amount
        """
        account = closing_transaction.get('account_number', '')
        symbol = closing_transaction.get('symbol', '')
        closing_quantity = abs(int(closing_transaction.get('quantity', 0)))
        closing_price = float(closing_transaction.get('price', 0))
        action = closing_transaction.get('action', '').upper()
        
        # Determine if we're closing long or short
        is_closing_long = 'SELL_TO_CLOSE' in action
        is_closing_short = 'BUY_TO_CLOSE' in action
        
        if not (is_closing_long or is_closing_short):
            return 0.0
        
        total_realized_pnl = 0.0
        remaining_to_close = closing_quantity

        with self.db.get_session() as session:
            # Get open lots using FIFO (ordered by entry date)
            lots = session.query(PositionLotModel).filter(
                PositionLotModel.account_number == account,
                PositionLotModel.symbol == symbol,
                PositionLotModel.remaining_quantity != 0,
            ).order_by(PositionLotModel.entry_date.asc()).all()

            for lot in lots:
                if remaining_to_close <= 0:
                    break

                # Check if this lot matches what we're closing
                if is_closing_long and lot.quantity < 0:
                    continue  # Skip short lots when closing long
                if is_closing_short and lot.quantity > 0:
                    continue  # Skip long lots when closing short

                # Calculate how much of this lot to close
                lot_available = abs(lot.remaining_quantity)
                close_amount = min(remaining_to_close, lot_available)

                # Calculate P&L for this portion
                if is_closing_long:
                    pnl = (closing_price - lot.entry_price) * close_amount * 100
                else:
                    pnl = (lot.entry_price - closing_price) * close_amount * 100

                total_realized_pnl += pnl

                # Update the lot's remaining quantity
                new_remaining = abs(lot.remaining_quantity) - close_amount
                if lot.quantity < 0:
                    new_remaining = -new_remaining  # Maintain sign for shorts

                lot.remaining_quantity = new_remaining

                remaining_to_close -= close_amount

                logger.debug(f"Closed {close_amount} contracts from lot {lot.transaction_id} "
                           f"at entry price {lot.entry_price}, closing price {closing_price}, "
                           f"P&L: ${pnl:.2f}")

        return total_realized_pnl
    
    def calculate_unrealized_pnl_for_position(self, position, current_price: float) -> float:
        """
        Calculate unrealized P&L for an open position
        Uses the position's cost basis (weighted average)
        """
        if position.is_closed:
            return 0.0
        
        quantity = abs(position.current_quantity)
        
        if position.is_long:
            # Long position: unrealized = (current - cost basis) * quantity
            pnl = (current_price - position.cost_basis) * quantity * 100
        else:
            # Short position: unrealized = (cost basis - current) * quantity  
            pnl = (position.cost_basis - current_price) * quantity * 100
        
        return pnl
    
    def calculate_chain_pnl(self, chain, current_prices: Dict[str, float]) -> PnLResult:
        """
        Calculate total P&L for a chain

        When lot_manager is available, uses lot_closings for realized P&L
        and open lots for unrealized P&L.

        Args:
            chain: Chain object
            current_prices: Dict mapping symbol to current market price

        Returns:
            PnLResult with realized, unrealized, and total P&L
        """
        # V3: Use lot-based P&L if available
        if self._use_lots and self.lot_manager:
            return self._calculate_chain_pnl_from_lots(chain, current_prices)

        # Legacy: Calculate from transaction-level FIFO
        realized_pnl = 0.0
        unrealized_pnl = 0.0

        # Calculate realized P&L from all closing transactions in the chain
        for order in chain.orders:
            for tx in order.closing_transactions:
                if not tx.is_expiration or tx.price > 0:  # Skip $0 expirations
                    tx_dict = {
                        'id': tx.id,
                        'account_number': tx.account_number,
                        'symbol': tx.symbol,
                        'action': tx.action,
                        'quantity': tx.quantity,
                        'price': tx.price,
                        'executed_at': tx.executed_at.isoformat()
                    }
                    realized_pnl += self.calculate_realized_pnl_for_closing(tx_dict)

        # Calculate unrealized P&L from open positions
        all_symbols = set()
        for order in chain.orders:
            all_symbols.update(order.symbols)

        for symbol in all_symbols:
            position = self.position_manager.get_position(chain.account_number, symbol)
            if position and not position.is_closed:
                current_price = current_prices.get(symbol, position.cost_basis)
                unrealized_pnl += self.calculate_unrealized_pnl_for_position(position, current_price)

        return PnLResult(
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=realized_pnl + unrealized_pnl
        )

    def _calculate_chain_pnl_from_lots(self, chain, current_prices: Dict[str, float]) -> PnLResult:
        """
        Calculate chain P&L using lot_closings and open lots.

        This is the V3 lot-based calculation method.
        """
        # Get realized P&L from lot_closings table
        realized_pnl = self.lot_manager.get_realized_pnl_for_chain(chain.chain_id)

        # Get unrealized P&L from open lots
        unrealized_pnl = 0.0
        open_lots = self.lot_manager.get_open_lots(
            account_number=chain.account_number,
            chain_id=chain.chain_id
        )

        for lot in open_lots:
            current_price = current_prices.get(lot.symbol)
            if current_price is None:
                # Fall back to entry price if no current price
                current_price = lot.entry_price

            # Determine multiplier (100 for options, 1 for stock)
            multiplier = 100 if lot.is_option else 1
            remaining_qty = abs(lot.remaining_quantity)

            if lot.is_long:
                # Long position: unrealized = (current - entry) * quantity * multiplier
                lot_unrealized = (current_price - lot.entry_price) * remaining_qty * multiplier
            else:
                # Short position: unrealized = (entry - current) * quantity * multiplier
                lot_unrealized = (lot.entry_price - current_price) * remaining_qty * multiplier

            unrealized_pnl += lot_unrealized

        return PnLResult(
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=realized_pnl + unrealized_pnl
        )

    def get_lot_level_pnl(self, chain_id: str, current_prices: Dict[str, float]) -> List[Dict]:
        """
        Get P&L breakdown by lot for a chain.

        Returns per-lot P&L details for display in the UI.
        """
        if not self._use_lots or not self.lot_manager:
            return []

        lots = self.lot_manager.get_lots_for_chain(chain_id, include_derived=True)
        lot_pnl_list = []

        for lot in lots:
            # Get closings for this lot
            closings = self.lot_manager.get_lot_closings(lot.id)
            realized_pnl = sum(c.realized_pnl for c in closings)

            # Calculate unrealized if still open
            unrealized_pnl = 0.0
            if lot.remaining_quantity != 0:
                current_price = current_prices.get(lot.symbol, lot.entry_price)
                multiplier = 100 if lot.is_option else 1
                remaining_qty = abs(lot.remaining_quantity)

                if lot.is_long:
                    unrealized_pnl = (current_price - lot.entry_price) * remaining_qty * multiplier
                else:
                    unrealized_pnl = (lot.entry_price - current_price) * remaining_qty * multiplier

            lot_pnl_list.append({
                'lot_id': lot.id,
                'symbol': lot.symbol,
                'underlying': lot.underlying,
                'option_type': lot.option_type,
                'strike': lot.strike,
                'expiration': lot.expiration.isoformat() if lot.expiration else None,
                'original_quantity': lot.original_quantity,
                'remaining_quantity': lot.remaining_quantity,
                'entry_price': lot.entry_price,
                'entry_date': lot.entry_date.isoformat() if lot.entry_date else None,
                'status': lot.status,
                'leg_index': lot.leg_index,
                'derived_from_lot_id': lot.derived_from_lot_id,
                'derivation_type': lot.derivation_type,
                'realized_pnl': realized_pnl,
                'unrealized_pnl': unrealized_pnl,
                'total_pnl': realized_pnl + unrealized_pnl,
                'closings': [
                    {
                        'closing_id': c.closing_id,
                        'quantity_closed': c.quantity_closed,
                        'closing_price': c.closing_price,
                        'closing_date': c.closing_date.isoformat() if c.closing_date else None,
                        'closing_type': c.closing_type,
                        'realized_pnl': c.realized_pnl,
                        'resulting_lot_id': c.resulting_lot_id
                    }
                    for c in closings
                ]
            })

        return lot_pnl_list
    
