"""
P&L Calculator V2
Implements P&L calculation based on position inventory and FIFO matching
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
import logging

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


class PnLCalculatorV2:
    """Calculates P&L using FIFO matching and position inventory"""
    
    def __init__(self, db_manager, position_manager):
        self.db = db_manager
        self.position_manager = position_manager
        self._create_lots_table_if_not_exists()
    
    def _create_lots_table_if_not_exists(self):
        """Create table to track position lots for FIFO"""
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
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            quantity = int(transaction.get('quantity', 0))
            action = transaction.get('action', '').upper()
            
            # Determine quantity sign based on action
            if 'SELL_TO_OPEN' in action:
                quantity = -abs(quantity)  # Short position
            else:
                quantity = abs(quantity)  # Long position
            
            cursor.execute("""
                INSERT OR REPLACE INTO position_lots 
                (transaction_id, account_number, symbol, quantity, 
                 entry_price, entry_date, remaining_quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction.get('id', ''),
                transaction.get('account_number', ''),
                transaction.get('symbol', ''),
                quantity,
                float(transaction.get('price', 0)),
                transaction.get('executed_at', ''),
                quantity  # Initially, remaining = total
            ))
    
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
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get open lots using FIFO (ordered by entry date)
            cursor.execute("""
                SELECT id, transaction_id, quantity, entry_price, remaining_quantity
                FROM position_lots
                WHERE account_number = ? AND symbol = ? AND remaining_quantity != 0
                ORDER BY entry_date ASC
            """, (account, symbol))
            
            lots = cursor.fetchall()
            
            for lot_id, tx_id, lot_quantity, entry_price, remaining_quantity in lots:
                if remaining_to_close <= 0:
                    break
                
                # Check if this lot matches what we're closing
                if is_closing_long and lot_quantity < 0:
                    continue  # Skip short lots when closing long
                if is_closing_short and lot_quantity > 0:
                    continue  # Skip long lots when closing short
                
                # Calculate how much of this lot to close
                lot_available = abs(remaining_quantity)
                close_amount = min(remaining_to_close, lot_available)
                
                # Calculate P&L for this portion
                if is_closing_long:
                    # Closing long: P&L = (sell price - buy price) * quantity
                    pnl = (closing_price - entry_price) * close_amount * 100  # *100 for options
                else:
                    # Closing short: P&L = (sell price - buy price) * quantity
                    # But since we opened with STO, it's (entry - closing) * quantity
                    pnl = (entry_price - closing_price) * close_amount * 100  # *100 for options
                
                total_realized_pnl += pnl
                
                # Update the lot's remaining quantity
                new_remaining = abs(remaining_quantity) - close_amount
                if lot_quantity < 0:
                    new_remaining = -new_remaining  # Maintain sign for shorts
                
                cursor.execute("""
                    UPDATE position_lots
                    SET remaining_quantity = ?
                    WHERE id = ?
                """, (new_remaining, lot_id))
                
                remaining_to_close -= close_amount
                
                logger.debug(f"Closed {close_amount} contracts from lot {tx_id} "
                           f"at entry price {entry_price}, closing price {closing_price}, "
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
        
        Args:
            chain: Chain object
            current_prices: Dict mapping symbol to current market price
        
        Returns:
            PnLResult with realized, unrealized, and total P&L
        """
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
    
    def get_position_lots(self, account_number: str, symbol: str) -> List[Dict]:
        """Get all open lots for a position"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT transaction_id, quantity, entry_price, entry_date, remaining_quantity
                FROM position_lots
                WHERE account_number = ? AND symbol = ? AND remaining_quantity != 0
                ORDER BY entry_date ASC
            """, (account_number, symbol))
            
            lots = []
            for row in cursor.fetchall():
                lots.append({
                    'transaction_id': row[0],
                    'quantity': row[1],
                    'entry_price': row[2],
                    'entry_date': row[3],
                    'remaining_quantity': row[4]
                })
            
            return lots
    
    def rebuild_lots_from_transactions(self):
        """Rebuild position lots table from raw transactions"""
        logger.info("Rebuilding position lots from transactions...")
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Clear existing lots
            cursor.execute("DELETE FROM position_lots")
            
            # Get all opening transactions
            cursor.execute("""
                SELECT id, account_number, symbol, action, quantity, price, executed_at
                FROM raw_transactions
                WHERE (action LIKE '%TO_OPEN%')
                AND symbol IS NOT NULL
                ORDER BY executed_at ASC
            """)
            
            opening_txs = cursor.fetchall()
            
            for tx in opening_txs:
                tx_dict = {
                    'id': tx[0],
                    'account_number': tx[1],
                    'symbol': tx[2],
                    'action': tx[3],
                    'quantity': tx[4],
                    'price': tx[5],
                    'executed_at': tx[6]
                }
                self.record_opening_lot(tx_dict)
            
            logger.info(f"Created {len(opening_txs)} position lots")
            
            # Now process all closing transactions to update remaining quantities
            cursor.execute("""
                SELECT id, account_number, symbol, action, quantity, price, executed_at
                FROM raw_transactions
                WHERE (action LIKE '%TO_CLOSE%' OR transaction_sub_type = 'Expiration')
                AND symbol IS NOT NULL
                ORDER BY executed_at ASC
            """)
            
            closing_txs = cursor.fetchall()
            
            for tx in closing_txs:
                tx_dict = {
                    'id': tx[0],
                    'account_number': tx[1],
                    'symbol': tx[2],
                    'action': tx[3],
                    'quantity': tx[4],
                    'price': tx[5],
                    'executed_at': tx[6]
                }
                self.calculate_realized_pnl_for_closing(tx_dict)
            
            logger.info(f"Processed {len(closing_txs)} closing transactions")