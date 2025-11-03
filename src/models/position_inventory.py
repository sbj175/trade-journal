"""
Position Inventory Management System
Based on the new order chain processing rules
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


@dataclass
class PositionInventory:
    """Represents current state of a position"""
    id: int
    account_number: str
    symbol: str
    underlying: str
    option_type: Optional[str]  # 'Call', 'Put', or None for stock
    strike: Optional[float]
    expiration: Optional[date]
    current_quantity: int  # Can be negative for short positions
    cost_basis: float  # Weighted average entry price
    last_updated: datetime
    
    @property
    def is_option(self) -> bool:
        return self.option_type is not None
    
    @property
    def is_short(self) -> bool:
        return self.current_quantity < 0
    
    @property
    def is_long(self) -> bool:
        return self.current_quantity > 0
    
    @property
    def is_closed(self) -> bool:
        return self.current_quantity == 0


class PositionInventoryManager:
    """Manages position inventory state"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._create_table_if_not_exists()
    
    def _create_table_if_not_exists(self):
        """Create the positions_inventory table if it doesn't exist"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_number TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    option_type TEXT,
                    strike REAL,
                    expiration DATE,
                    current_quantity INTEGER NOT NULL,
                    cost_basis REAL NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_number, symbol)
                )
            """)
            
            # Create indexes for efficient lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_account_underlying 
                ON positions_inventory(account_number, underlying)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_symbol 
                ON positions_inventory(symbol)
            """)
    
    def get_position(self, account_number: str, symbol: str) -> Optional[PositionInventory]:
        """Get a specific position from inventory"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, account_number, symbol, underlying, option_type, 
                       strike, expiration, current_quantity, cost_basis, last_updated
                FROM positions_inventory
                WHERE account_number = ? AND symbol = ?
            """, (account_number, symbol))
            
            row = cursor.fetchone()
            if row:
                return self._row_to_position(row)
            return None
    
    def get_positions_for_account(self, account_number: str, 
                                  underlying: Optional[str] = None) -> List[PositionInventory]:
        """Get all positions for an account, optionally filtered by underlying"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if underlying:
                cursor.execute("""
                    SELECT id, account_number, symbol, underlying, option_type, 
                           strike, expiration, current_quantity, cost_basis, last_updated
                    FROM positions_inventory
                    WHERE account_number = ? AND underlying = ?
                    ORDER BY symbol
                """, (account_number, underlying))
            else:
                cursor.execute("""
                    SELECT id, account_number, symbol, underlying, option_type, 
                           strike, expiration, current_quantity, cost_basis, last_updated
                    FROM positions_inventory
                    WHERE account_number = ?
                    ORDER BY underlying, symbol
                """, (account_number,))
            
            return [self._row_to_position(row) for row in cursor.fetchall()]
    
    def get_open_positions(self, account_number: Optional[str] = None) -> List[PositionInventory]:
        """Get all open positions (quantity != 0)"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if account_number:
                cursor.execute("""
                    SELECT id, account_number, symbol, underlying, option_type, 
                           strike, expiration, current_quantity, cost_basis, last_updated
                    FROM positions_inventory
                    WHERE account_number = ? AND current_quantity != 0
                    ORDER BY underlying, symbol
                """, (account_number,))
            else:
                cursor.execute("""
                    SELECT id, account_number, symbol, underlying, option_type, 
                           strike, expiration, current_quantity, cost_basis, last_updated
                    FROM positions_inventory
                    WHERE current_quantity != 0
                    ORDER BY account_number, underlying, symbol
                """)
            
            return [self._row_to_position(row) for row in cursor.fetchall()]
    
    def update_position_from_transaction(self, transaction: Dict) -> PositionInventory:
        """Update position inventory based on a transaction"""
        account_number = transaction['account_number']
        symbol = transaction['symbol']
        action = (transaction.get('action') or '').upper()
        quantity = abs(int(transaction.get('quantity', 0)))
        price = float(transaction.get('price') or 0)
        
        # Get or create position
        position = self.get_position(account_number, symbol)
        
        if not position:
            # Create new position
            position = self._create_position_from_transaction(transaction)
        
        # Check transaction sub-type for assignment/exercise/expiration
        sub_type = (transaction.get('transaction_sub_type') or '').upper()
        
        # Update position based on action or transaction type
        if 'BUY_TO_OPEN' in action:
            # Long position - increase quantity
            self._update_position_quantity(position, quantity, price, is_opening=True)
        elif 'SELL_TO_OPEN' in action:
            # Short position - decrease quantity (negative)
            self._update_position_quantity(position, -quantity, price, is_opening=True)
        elif 'BUY_TO_CLOSE' in action:
            # Close short position - increase quantity (toward zero)
            self._update_position_quantity(position, quantity, price, is_opening=False)
        elif 'SELL_TO_CLOSE' in action:
            # Close long position - decrease quantity (toward zero)
            self._update_position_quantity(position, -quantity, price, is_opening=False)
        elif 'ASSIGNMENT' in sub_type:
            # Assignment closes the position completely (short option gets assigned)
            self._close_position_completely(position)
        elif 'EXERCISE' in sub_type:
            # Exercise closes the position completely (long option gets exercised)
            self._close_position_completely(position)
        elif 'EXPIR' in sub_type:
            # Expiration closes the position completely
            self._close_position_completely(position)
        
        return position
    
    def _close_position_completely(self, position: PositionInventory):
        """Close a position completely (set quantity to 0)"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE positions_inventory
                SET current_quantity = 0, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (position.id,))
            
            # Update object
            position.current_quantity = 0
            position.last_updated = datetime.now()
    
    def _update_position_quantity(self, position: PositionInventory, 
                                  quantity_change: int, price: float, 
                                  is_opening: bool):
        """Update position quantity and cost basis"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            old_quantity = position.current_quantity
            new_quantity = old_quantity + quantity_change
            
            # Calculate new cost basis for opening trades
            if is_opening and new_quantity != 0:
                # Weighted average cost basis
                old_value = abs(old_quantity) * position.cost_basis
                new_value = abs(quantity_change) * price
                total_value = old_value + new_value
                total_quantity = abs(old_quantity) + abs(quantity_change)
                new_cost_basis = total_value / total_quantity if total_quantity > 0 else price
            else:
                # Keep existing cost basis for closing trades
                new_cost_basis = position.cost_basis
            
            # Update in database
            cursor.execute("""
                UPDATE positions_inventory
                SET current_quantity = ?, cost_basis = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_quantity, new_cost_basis, position.id))
            
            # Update object
            position.current_quantity = new_quantity
            position.cost_basis = new_cost_basis
            position.last_updated = datetime.now()
    
    def _create_position_from_transaction(self, transaction: Dict) -> PositionInventory:
        """Create a new position from a transaction"""
        symbol = transaction['symbol']
        underlying = transaction.get('underlying_symbol', symbol)
        
        # Remove option suffixes to get underlying
        if ' ' in underlying:
            underlying = underlying.split()[0]
        
        # Parse option details if this is an option
        option_type = None
        strike = None
        expiration = None
        
        instrument_type = transaction.get('instrument_type', '')
        if 'OPTION' in instrument_type and ' ' in symbol:
            # Parse option symbol format: "AAPL  241220C00150000"
            parts = symbol.split()
            if len(parts) >= 2:
                option_part = parts[1]
                if len(option_part) >= 8:
                    # Extract date (first 6 chars: YYMMDD)
                    date_str = option_part[:6]
                    try:
                        expiration = datetime.strptime('20' + date_str, '%Y%m%d').date()
                    except:
                        pass
                    
                    # Extract option type (7th char: C or P)
                    if len(option_part) > 6:
                        option_type = 'Call' if option_part[6] == 'C' else 'Put'
                    
                    # Extract strike (remaining digits / 1000)
                    if len(option_part) > 7:
                        try:
                            strike = float(option_part[7:]) / 1000
                        except:
                            pass
        
        # Insert into database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO positions_inventory 
                (account_number, symbol, underlying, option_type, strike, 
                 expiration, current_quantity, cost_basis)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """, (transaction['account_number'], symbol, underlying, 
                  option_type, strike, expiration))
            
            position_id = cursor.lastrowid
        
        return PositionInventory(
            id=position_id,
            account_number=transaction['account_number'],
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            current_quantity=0,
            cost_basis=0.0,
            last_updated=datetime.now()
        )
    
    def _row_to_position(self, row) -> PositionInventory:
        """Convert database row to PositionInventory object"""
        (id, account_number, symbol, underlying, option_type, 
         strike, expiration, current_quantity, cost_basis, last_updated) = row
        
        # Parse dates
        if expiration and isinstance(expiration, str):
            expiration = datetime.strptime(expiration, '%Y-%m-%d').date()
        
        if isinstance(last_updated, str):
            last_updated = datetime.strptime(last_updated, '%Y-%m-%d %H:%M:%S')
        
        return PositionInventory(
            id=id,
            account_number=account_number,
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            current_quantity=current_quantity,
            cost_basis=cost_basis,
            last_updated=last_updated
        )
    
    def clear_all_positions(self):
        """Clear all positions - use with caution!"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions_inventory")
            logger.warning("Cleared all positions from inventory")