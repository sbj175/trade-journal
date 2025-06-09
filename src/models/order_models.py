"""
Order, Position, and OrderChain Models
Implements the new Order-based data model per requirements
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from enum import Enum


class OrderType(Enum):
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    ROLLING = "ROLLING"


class OrderStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"


class PositionStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ChainStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Position:
    """Represents a single position within an order"""
    position_id: int
    order_id: str
    account_number: str
    symbol: str
    underlying: str
    instrument_type: str  # 'EQUITY', 'EQUITY_OPTION'
    option_type: Optional[str] = None  # 'Call' or 'Put' for options
    strike: Optional[float] = None  # For options
    expiration: Optional[date] = None  # For options
    quantity: int = 0  # Positive for long, negative for short
    opening_price: float = 0.0
    closing_price: Optional[float] = None
    opening_transaction_id: str = ""
    closing_transaction_id: Optional[str] = None
    opening_action: str = ""  # 'BTO', 'STO', 'BUY', 'SELL'
    closing_action: Optional[str] = None  # 'BTC', 'STC', 'EXPIRED', 'ASSIGNED', etc.
    status: PositionStatus = PositionStatus.OPEN
    pnl: float = 0.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0
    
    @property
    def is_option(self) -> bool:
        return 'OPTION' in self.instrument_type
    
    @property
    def is_stock(self) -> bool:
        return 'EQUITY' in self.instrument_type and 'OPTION' not in self.instrument_type
    
    @property
    def has_system_closure(self) -> bool:
        """Check if position was closed by system (expiration/assignment)"""
        if not self.closing_action:
            return False
        return any(action in self.closing_action.upper() for action in 
                  ['EXPIRED', 'ASSIGNED', 'EXERCISED', 'CASH_SETTLED'])


@dataclass
class Order:
    """Represents an order containing one or more positions"""
    order_id: str
    account_number: str
    underlying: str
    order_type: OrderType
    strategy_type: Optional[str] = None
    order_date: Optional[date] = None
    status: OrderStatus = OrderStatus.OPEN
    total_quantity: int = 0
    total_pnl: float = 0.0
    has_assignment: bool = False
    has_expiration: bool = False
    has_exercise: bool = False
    linked_order_id: Optional[str] = None  # For rolling orders
    positions: List[Position] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def is_rolling(self) -> bool:
        return self.order_type == OrderType.ROLLING
    
    @property
    def has_system_transactions(self) -> bool:
        return self.has_assignment or self.has_expiration or self.has_exercise
    
    @property
    def system_emblems(self) -> List[str]:
        """Get list of system emblems to display"""
        emblems = []
        if self.has_assignment:
            emblems.append('A')  # Assignment
        if self.has_expiration:
            emblems.append('E')  # Expiration
        if self.has_exercise:
            emblems.append('X')  # Exercise
        if self.is_rolling:
            emblems.append('R')  # Roll
        return emblems


@dataclass
class OrderChain:
    """Represents a chain of related orders"""
    chain_id: str
    underlying: str
    account_number: str
    opening_order_id: str
    strategy_type: str  # From opening order
    chain_status: ChainStatus = ChainStatus.OPEN
    total_pnl: float = 0.0
    orders: List[Order] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def opening_order(self) -> Optional[Order]:
        """Get the opening order in the chain"""
        for order in self.orders:
            if order.order_id == self.opening_order_id:
                return order
        return None
    
    @property
    def closing_order(self) -> Optional[Order]:
        """Get the final closing order in the chain (if any)"""
        for order in reversed(self.orders):  # Check from end
            if order.order_type == OrderType.CLOSING:
                return order
        return None
    
    @property
    def roll_count(self) -> int:
        """Count of rolling orders in the chain"""
        return sum(1 for order in self.orders if order.is_rolling)
    
    @property
    def is_complete(self) -> bool:
        """Check if chain is complete (has closing order)"""
        return self.closing_order is not None
    
    @property
    def opening_date(self) -> Optional[date]:
        """Get opening date from the first order"""
        opening = self.opening_order
        return opening.order_date if opening else None
    
    @property
    def closing_date(self) -> Optional[date]:
        """Get closing date from the last closing order"""
        closing = self.closing_order
        return closing.order_date if closing else None


class OrderManager:
    """Manager class for Order/Position operations"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def get_order_chains(self, account_number: Optional[str] = None, 
                        limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get order chains with their orders and positions"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    oc.chain_id,
                    oc.underlying,
                    oc.account_number,
                    oc.opening_order_id,
                    oc.strategy_type,
                    oc.chain_status,
                    oc.total_pnl,
                    oc.created_at,
                    oc.updated_at
                FROM order_chains oc
            """
            params = []
            
            if account_number:
                query += " WHERE oc.account_number = ?"
                params.append(account_number)
            
            query += " ORDER BY oc.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            chains_data = cursor.fetchall()
            
            chains = []
            for chain_row in chains_data:
                chain_dict = dict(chain_row)
                
                # Get orders for this chain
                cursor.execute("""
                    SELECT o.*, ocm.sequence_number
                    FROM orders o
                    JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                    WHERE ocm.chain_id = ?
                    ORDER BY ocm.sequence_number
                """, (chain_dict['chain_id'],))
                
                orders_data = cursor.fetchall()
                orders = []
                
                for order_row in orders_data:
                    order_dict = dict(order_row)
                    
                    # Get positions for this order
                    cursor.execute("""
                        SELECT * FROM positions_new WHERE order_id = ?
                        ORDER BY symbol
                    """, (order_dict['order_id'],))
                    
                    positions_data = cursor.fetchall()
                    positions = [dict(pos) for pos in positions_data]
                    
                    order_dict['positions'] = positions
                    orders.append(order_dict)
                
                chain_dict['orders'] = orders
                chains.append(chain_dict)
            
            return chains
    
    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific order with its positions"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            order_row = cursor.fetchone()
            
            if not order_row:
                return None
            
            order_dict = dict(order_row)
            
            # Get positions
            cursor.execute("""
                SELECT * FROM positions_new WHERE order_id = ?
                ORDER BY symbol
            """, (order_id,))
            
            positions_data = cursor.fetchall()
            order_dict['positions'] = [dict(pos) for pos in positions_data]
            
            return order_dict
    
    def get_positions_by_account(self, account_number: str, 
                               status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get positions for an account, optionally filtered by status"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM positions_new WHERE account_number = ?"
            params = [account_number]
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def update_order_pnl(self, order_id: str) -> float:
        """Recalculate and update P&L for an order"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate total P&L from positions
            cursor.execute("""
                SELECT COALESCE(SUM(pnl), 0) FROM positions_new 
                WHERE order_id = ?
            """, (order_id,))
            
            total_pnl = cursor.fetchone()[0]
            
            # Update order
            cursor.execute("""
                UPDATE orders SET total_pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """, (total_pnl, order_id))
            
            conn.commit()
            return total_pnl
    
    def update_chain_pnl(self, chain_id: str) -> float:
        """Recalculate and update P&L for an order chain"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate total P&L from all orders in the chain
            cursor.execute("""
                SELECT COALESCE(SUM(o.total_pnl), 0)
                FROM orders o
                JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
            """, (chain_id,))
            
            total_pnl = cursor.fetchone()[0]
            
            # Update chain
            cursor.execute("""
                UPDATE order_chains SET total_pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE chain_id = ?
            """, (total_pnl, chain_id))
            
            conn.commit()
            return total_pnl
    
    def get_order_statistics(self, account_number: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for orders and chains"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            where_clause = "WHERE account_number = ?" if account_number else ""
            params = [account_number] if account_number else []
            
            # Order stats
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total_orders,
                    COUNT(CASE WHEN status = 'OPEN' THEN 1 END) as open_orders,
                    COUNT(CASE WHEN status = 'CLOSED' THEN 1 END) as closed_orders,
                    COALESCE(SUM(total_pnl), 0) as total_pnl
                FROM orders {where_clause}
            """, params)
            
            order_stats = dict(cursor.fetchone())
            
            # Chain stats
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total_chains,
                    COUNT(CASE WHEN chain_status = 'OPEN' THEN 1 END) as open_chains,
                    COUNT(CASE WHEN chain_status = 'CLOSED' THEN 1 END) as closed_chains
                FROM order_chains {where_clause}
            """, params)
            
            chain_stats = dict(cursor.fetchone())
            
            # Position stats
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total_positions,
                    COUNT(CASE WHEN status = 'OPEN' THEN 1 END) as open_positions,
                    COUNT(CASE WHEN status = 'CLOSED' THEN 1 END) as closed_positions
                FROM positions_new {where_clause}
            """, params)
            
            position_stats = dict(cursor.fetchone())
            
            return {
                **order_stats,
                **chain_stats,
                **position_stats
            }