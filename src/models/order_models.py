"""
Order, Position, and OrderChain Models
Implements the new Order-based data model per requirements
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from enum import Enum
from loguru import logger


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
    fill_count: int = 1  # Number of fills consolidated into this position
    # Enhanced tracking fields
    opening_order_id: Optional[str] = None  # Order ID that opened this position
    closing_order_id: Optional[str] = None  # Order ID that closed this position
    opening_amount: Optional[float] = None  # Total amount paid/received when opening
    closing_amount: Optional[float] = None  # Total amount paid/received when closing
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
    
    def consolidate_positions(self) -> List[Position]:
        """Consolidate multiple fills of the same position into single entries"""
        if not self.positions:
            return []
        
        from collections import defaultdict
        
        # Group positions by consolidation key - must include strike/expiration for options
        grouped_positions = defaultdict(list)
        
        for position in self.positions:
            # Create key for grouping - include strike and expiration for options
            # This ensures different option contracts (different strikes) remain separate
            # Only consolidate fills of the SAME option contract with different prices
            if position.is_option:
                key = (
                    position.symbol,
                    position.opening_action,
                    position.closing_action or '',
                    position.strike,  # Include strike for options
                    position.expiration  # Include expiration for options
                )
            else:
                # For stocks, use simpler grouping
                key = (
                    position.symbol,
                    position.opening_action,
                    position.closing_action or ''
                )
            grouped_positions[key].append(position)
        
        consolidated_positions = []
        
        for key, positions in grouped_positions.items():
            if len(positions) == 1:
                # Single position, just return as-is
                consolidated_positions.append(positions[0])
            else:
                # Multiple positions to consolidate
                first_position = positions[0]
                
                # Sum quantities and P&L
                total_quantity = sum(pos.quantity for pos in positions)
                total_pnl = sum(pos.pnl for pos in positions)
                
                # Calculate weighted average price
                total_value = 0.0
                for pos in positions:
                    total_value += (pos.opening_price or 0.0) * abs(pos.quantity)
                
                avg_opening_price = total_value / abs(total_quantity) if total_quantity != 0 else 0.0
                
                # Combine transaction IDs
                opening_tx_ids = [pos.opening_transaction_id for pos in positions if pos.opening_transaction_id]
                closing_tx_ids = [pos.closing_transaction_id for pos in positions if pos.closing_transaction_id]
                
                # Sum opening and closing amounts
                total_opening_amount = sum(pos.opening_amount or 0.0 for pos in positions)
                total_closing_amount = sum(pos.closing_amount or 0.0 for pos in positions)
                
                # Create consolidated position
                consolidated = Position(
                    position_id=first_position.position_id,  # Use first position's ID
                    order_id=first_position.order_id,
                    account_number=first_position.account_number,
                    symbol=first_position.symbol,
                    underlying=first_position.underlying,
                    instrument_type=first_position.instrument_type,
                    option_type=first_position.option_type,
                    strike=first_position.strike,
                    expiration=first_position.expiration,
                    quantity=total_quantity,
                    opening_price=avg_opening_price,
                    closing_price=first_position.closing_price,
                    opening_transaction_id=','.join(opening_tx_ids),
                    closing_transaction_id=','.join(closing_tx_ids) if closing_tx_ids else None,
                    opening_action=first_position.opening_action,
                    closing_action=first_position.closing_action,
                    status=first_position.status,
                    pnl=total_pnl,
                    fill_count=len(positions),
                    # New enhanced fields
                    opening_order_id=first_position.opening_order_id,
                    closing_order_id=first_position.closing_order_id,
                    opening_amount=total_opening_amount if total_opening_amount != 0 else None,
                    closing_amount=total_closing_amount if total_closing_amount != 0 else None,
                    created_at=first_position.created_at,
                    updated_at=first_position.updated_at
                )
                
                consolidated_positions.append(consolidated)
        
        return consolidated_positions


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
                    oc.realized_pnl,
                    oc.unrealized_pnl,
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
    
    def calculate_realized_position_pnl(self, position: Dict[str, Any]) -> float:
        """Calculate realized P&L for a position based on actual cash flows"""
        quantity = position.get('quantity', 0)
        opening_price = position.get('opening_price', 0.0)
        closing_price = position.get('closing_price')
        opening_action = position.get('opening_action', '')
        closing_action = position.get('closing_action')
        status = position.get('status', '')
        instrument_type = position.get('instrument_type', '')
        
        total_realized = 0.0
        
        # Calculate opening cash flow
        if opening_action:
            if 'STO' in opening_action or ('SELL' in opening_action and 'CLOSE' not in opening_action):
                # Selling = credit received
                if 'OPTION' in instrument_type:
                    total_realized += abs(quantity) * opening_price * 100
                else:
                    total_realized += abs(quantity) * opening_price
            elif 'BTO' in opening_action or ('BUY' in opening_action and 'CLOSE' not in opening_action):
                # Buying = debit paid
                if 'OPTION' in instrument_type:
                    total_realized -= abs(quantity) * opening_price * 100
                else:
                    total_realized -= abs(quantity) * opening_price
        
        # Calculate closing cash flow (only if position is closed)
        if status == 'CLOSED' and closing_price is not None and closing_action:
            if 'STC' in closing_action or ('SELL' in closing_action and 'CLOSE' in closing_action):
                # Selling to close = credit received
                if 'OPTION' in instrument_type:
                    total_realized += abs(quantity) * closing_price * 100
                else:
                    total_realized += abs(quantity) * closing_price
            elif 'BTC' in closing_action or ('BUY' in closing_action and 'CLOSE' in closing_action):
                # Buying to close = debit paid
                if 'OPTION' in instrument_type:
                    total_realized -= abs(quantity) * closing_price * 100
                else:
                    total_realized -= abs(quantity) * closing_price
        
        return total_realized

    def update_order_pnl(self, order_id: str) -> float:
        """Recalculate and update P&L for an order using realized P&L"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all positions for this order
            cursor.execute("""
                SELECT * FROM positions_new WHERE order_id = ?
            """, (order_id,))
            
            positions = cursor.fetchall()
            total_pnl = 0.0
            
            # Calculate realized P&L for each position
            for pos_row in positions:
                position = dict(pos_row)
                realized_pnl = self.calculate_realized_position_pnl(position)
                total_pnl += realized_pnl
                
                # Update position P&L if different
                if abs(realized_pnl - (position.get('pnl') or 0.0)) > 0.01:
                    cursor.execute("""
                        UPDATE positions_new SET pnl = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE position_id = ?
                    """, (realized_pnl, position['position_id']))
            
            # Update order
            cursor.execute("""
                UPDATE orders SET total_pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """, (total_pnl, order_id))
            
            conn.commit()
            return total_pnl
    
    def calculate_chain_realized_pnl(self, chain_id: str, chain_status: str) -> float:
        """Calculate truly realized P&L based on completed round trips
        
        Logic:
        - Closed chains: All P&L is realized
        - Open chains: Sum net P&L from completed round trips (STO + matching BTC)
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if chain_status == 'CLOSED':
                # All P&L is realized for closed chains - sum all positions
                cursor.execute("""
                    SELECT COALESCE(SUM(p.pnl), 0)
                    FROM positions_new p
                    JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                    WHERE ocm.chain_id = ?
                """, (chain_id,))
                return cursor.fetchone()[0] or 0.0
            
            # For open chains, calculate net P&L from completed round trips
            # Get all positions for this chain
            cursor.execute("""
                SELECT p.symbol, p.opening_action, p.status, p.pnl, p.strike, p.expiration
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
                ORDER BY p.strike, p.expiration
            """, (chain_id,))
            
            positions = cursor.fetchall()
            
            # Group positions by strike and expiration to find completed round trips
            from collections import defaultdict
            position_groups = defaultdict(list)
            
            for pos in positions:
                symbol, action, status, pnl, strike, expiration = pos
                key = (symbol, strike, expiration)
                position_groups[key].append({
                    'action': action,
                    'status': status,
                    'pnl': pnl
                })
            
            realized_pnl = 0.0
            
            # For each strike/expiration group, find completed round trips
            for key, group_positions in position_groups.items():
                opening_pnl = 0.0
                closing_pnl = 0.0
                has_opening = False
                has_closing = False
                
                for pos in group_positions:
                    if 'TO_OPEN' in pos['action']:
                        opening_pnl += pos['pnl']
                        has_opening = True
                    elif 'TO_CLOSE' in pos['action']:
                        closing_pnl += pos['pnl']
                        has_closing = True
                
                # If we have both opening and closing for this strike, it's a completed round trip
                if has_opening and has_closing:
                    realized_pnl += opening_pnl + closing_pnl
            
            return realized_pnl

    def calculate_chain_unrealized_pnl(self, chain_id: str, chain_status: str) -> float:
        """Calculate unrealized P&L from truly open positions (not part of completed round trips)
        
        Logic:
        - Closed chains: No unrealized P&L
        - Open chains: Sum only OPEN positions that don't have matching closing positions
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if chain_status == 'CLOSED':
                # No unrealized P&L for closed chains
                return 0.0
            
            # Get all positions for this chain
            cursor.execute("""
                SELECT p.symbol, p.opening_action, p.status, p.pnl, p.strike, p.expiration
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
                ORDER BY p.strike, p.expiration
            """, (chain_id,))
            
            positions = cursor.fetchall()
            
            # Group positions by strike and expiration
            from collections import defaultdict
            position_groups = defaultdict(list)
            
            for pos in positions:
                symbol, action, status, pnl, strike, expiration = pos
                key = (symbol, strike, expiration)
                position_groups[key].append({
                    'action': action,
                    'status': status,
                    'pnl': pnl
                })
            
            unrealized_pnl = 0.0
            
            # For each strike/expiration group, only count open positions without matching closes
            for key, group_positions in position_groups.items():
                has_opening = False
                has_closing = False
                opening_pnl = 0.0
                
                for pos in group_positions:
                    if 'TO_OPEN' in pos['action']:
                        opening_pnl += pos['pnl']
                        has_opening = True
                    elif 'TO_CLOSE' in pos['action']:
                        has_closing = True
                
                # Only count opening P&L if there's no matching closing (truly unrealized)
                if has_opening and not has_closing:
                    unrealized_pnl += opening_pnl
            
            return unrealized_pnl

    def update_chain_pnl(self, chain_id: str) -> float:
        """Recalculate and update total, realized, and unrealized P&L for an order chain"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get chain status first
            cursor.execute("SELECT chain_status FROM order_chains WHERE chain_id = ?", (chain_id,))
            result = cursor.fetchone()
            if not result:
                return 0.0
            chain_status = result[0]
            
            # Calculate total P&L from all orders in the chain
            cursor.execute("""
                SELECT COALESCE(SUM(o.total_pnl), 0)
                FROM orders o
                JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
            """, (chain_id,))
            
            total_pnl = cursor.fetchone()[0]
            
            # Calculate realized and unrealized P&L
            realized_pnl = self.calculate_chain_realized_pnl(chain_id, chain_status)
            unrealized_pnl = self.calculate_chain_unrealized_pnl(chain_id, chain_status)
            
            # Update chain with all three values
            cursor.execute("""
                UPDATE order_chains 
                SET total_pnl = ?, realized_pnl = ?, unrealized_pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE chain_id = ?
            """, (total_pnl, realized_pnl, unrealized_pnl, chain_id))
            
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
            
            # Chain stats - filter through order_chain_members since order_chains doesn't have account_number
            if account_number:
                cursor.execute("""
                    SELECT 
                        COUNT(DISTINCT oc.chain_id) as total_chains,
                        COUNT(CASE WHEN oc.chain_status = 'OPEN' THEN 1 END) as open_chains,
                        COUNT(CASE WHEN oc.chain_status = 'CLOSED' THEN 1 END) as closed_chains
                    FROM order_chains oc
                    JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
                    JOIN orders o ON ocm.order_id = o.order_id
                    WHERE o.account_number = ?
                """, [account_number])
            else:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_chains,
                        COUNT(CASE WHEN chain_status = 'OPEN' THEN 1 END) as open_chains,
                        COUNT(CASE WHEN chain_status = 'CLOSED' THEN 1 END) as closed_chains
                    FROM order_chains
                """, [])
            
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
    
    def group_transactions_by_order_id(self, transactions: List[Dict]) -> Dict[str, List[Dict]]:
        """Group transactions by order ID to handle partial fills and system events"""
        orders_dict = {}
        
        for transaction in transactions:
            order_id = transaction.get('order_id')
            
            # Handle system events (expiration, assignment, exercise) that don't have order IDs
            if not order_id:
                if self.is_system_event(transaction):
                    # Create synthetic order ID for system events
                    tx_id = transaction.get('id', 'UNKNOWN')
                    event_type = self.get_system_event_type(transaction)
                    order_id = f"SYSTEM_{event_type}_{tx_id}"
                    transaction['synthetic_order_id'] = order_id
                else:
                    continue
                
            # Filter out non-trading transactions
            if not transaction.get('symbol') or not transaction.get('instrument_type'):
                continue
                
            if order_id not in orders_dict:
                orders_dict[order_id] = []
            orders_dict[order_id].append(transaction)
        
        return orders_dict
    
    def is_system_event(self, transaction: Dict) -> bool:
        """Check if transaction is a system event (expiration, assignment, exercise)"""
        description = str(transaction.get('description') or '').upper()
        action = str(transaction.get('action') or '').upper()
        
        # Check for expiration
        if 'DUE TO EXPIRATION' in description:
            return True
        if 'EXPIRED' in action:
            return True
            
        # Check for assignment
        if 'ASSIGNED' in description or 'ASSIGNMENT' in description:
            return True
        if 'ASSIGNED' in action:
            return True
            
        # Check for exercise
        if 'EXERCISED' in description or 'EXERCISE' in description:
            return True
        if 'EXERCISED' in action:
            return True
            
        # Check for cash settlement
        if 'CASH SETTLED' in description or 'CASH_SETTLED' in action:
            return True
            
        return False
    
    def get_system_event_type(self, transaction: Dict) -> str:
        """Get the type of system event"""
        description = str(transaction.get('description') or '').upper()
        action = str(transaction.get('action') or '').upper()
        
        # Check for expiration
        if 'DUE TO EXPIRATION' in description or 'EXPIRED' in action:
            return 'EXPIRATION'
            
        # Check for assignment
        if 'ASSIGNED' in description or 'ASSIGNMENT' in description or 'ASSIGNED' in action:
            return 'ASSIGNMENT'
            
        # Check for exercise
        if 'EXERCISED' in description or 'EXERCISE' in description or 'EXERCISED' in action:
            return 'EXERCISE'
            
        # Check for cash settlement
        if 'CASH SETTLED' in description or 'CASH_SETTLED' in action:
            return 'CASH_SETTLEMENT'
            
        return 'UNKNOWN'
    
    def determine_order_type(self, transactions: List[Dict]) -> OrderType:
        """Determine if order is Opening, Rolling, or Closing based on transaction actions"""
        actions = set()
        is_system_event = False
        
        for tx in transactions:
            # Check if any transaction is a system event
            if self.is_system_event(tx):
                is_system_event = True
                
            action = tx.get('action', '')
            if action:
                actions.add(action)
        
        # System events are always closing orders
        if is_system_event:
            return OrderType.CLOSING
        
        # Handle both enum string format and simple string format
        opening_actions = {
            'BTO', 'STO', 'BUY',  # Simple format
            'OrderAction.BUY_TO_OPEN', 'OrderAction.SELL_TO_OPEN'  # Enum format
        }
        closing_actions = {
            'BTC', 'STC', 'SELL',  # Simple format  
            'OrderAction.BUY_TO_CLOSE', 'OrderAction.SELL_TO_CLOSE'  # Enum format
        }
        
        has_opening = bool(actions & opening_actions)
        has_closing = bool(actions & closing_actions)
        
        if has_opening and has_closing:
            return OrderType.ROLLING
        elif has_opening and not has_closing:
            return OrderType.OPENING
        elif has_closing and not has_opening:
            return OrderType.CLOSING
        else:
            # Default to opening if unclear
            return OrderType.OPENING
    
    def create_order_from_transactions(self, order_id: str, transactions: List[Dict]) -> Optional[Order]:
        """Create an Order object from a group of transactions with the same order ID"""
        if not transactions:
            return None
        
        # Get common properties from first transaction
        first_tx = transactions[0]
        account_number = first_tx.get('account_number', '')
        underlying = first_tx.get('underlying_symbol', first_tx.get('symbol', ''))
        
        # Remove option suffixes to get underlying
        if ' ' in underlying:
            underlying = underlying.split()[0]
        
        order_date = None
        if first_tx.get('executed_at'):
            order_date = datetime.fromisoformat(first_tx['executed_at'].replace('Z', '+00:00')).date()
        
        # Determine order type
        order_type = self.determine_order_type(transactions)
        
        # Create order (ensure order_id is string)
        order = Order(
            order_id=str(order_id),
            account_number=account_number,
            underlying=underlying,
            order_type=order_type,
            order_date=order_date,
            status=OrderStatus.CLOSED  # Most historical orders are closed
        )
        
        # Create positions from transactions
        positions = []
        for tx in transactions:
            position = self.create_position_from_transaction(tx, str(order_id))
            if position:
                positions.append(position)
                print(f"Created position for {order_id}: {position.symbol}, {position.opening_action}, {position.closing_action}")
            else:
                print(f"Failed to create position for {order_id} from transaction: {tx.get('symbol', 'unknown')}, {tx.get('action', 'unknown')}")
        
        # Consolidate multiple fills of the same action into single positions
        # This keeps different actions (BTC vs STO) separate but combines fills
        order.positions = positions  # Set positions first so consolidate_positions can access them
        order.positions = order.consolidate_positions()
        
        # Calculate order totals
        order.total_quantity = sum(abs(p.quantity) for p in order.positions)
        order.total_pnl = sum(p.pnl for p in order.positions)
        
        # Check for system events from both positions and transactions
        order.has_assignment = any('ASSIGNED' in str(p.closing_action).upper() for p in order.positions if p.closing_action)
        order.has_expiration = any('EXPIRED' in str(p.closing_action).upper() for p in order.positions if p.closing_action)
        order.has_exercise = any('EXERCISED' in str(p.closing_action).upper() for p in order.positions if p.closing_action)
        
        # Also check transactions directly for system events
        for tx in transactions:
            if self.is_system_event(tx):
                event_type = self.get_system_event_type(tx)
                if event_type == 'EXPIRATION':
                    order.has_expiration = True
                elif event_type == 'ASSIGNMENT':
                    order.has_assignment = True
                elif event_type == 'EXERCISE':
                    order.has_exercise = True
        
        return order
    
    def create_position_from_transaction(self, transaction: Dict, order_id: str) -> Optional[Position]:
        """Create a Position object from a single transaction"""
        try:
            symbol = transaction.get('symbol', '')
            if not symbol:
                return None
            
            instrument_type = transaction.get('instrument_type', '')
            account_number = transaction.get('account_number', '')
            underlying = transaction.get('underlying_symbol', symbol)
            
            # Remove option suffixes to get underlying
            if ' ' in underlying:
                underlying = underlying.split()[0]
            
            # Parse option details if this is an option
            option_type = None
            strike = None
            expiration = None
            
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
            
            # Get transaction details with safe type conversion
            try:
                quantity = int(transaction.get('quantity', 0) or 0)
            except (ValueError, TypeError):
                quantity = 0
                
            try:
                price = float(transaction.get('price', 0) or 0)
            except (ValueError, TypeError):
                price = 0.0
                
            try:
                value = float(transaction.get('value', 0) or 0)
            except (ValueError, TypeError):
                value = 0.0
            
            action = (transaction.get('action') or '').upper()
            
            # Get transaction ID (might be 'id' or other field)
            transaction_id = transaction.get('id', transaction.get('transaction_id', ''))
            if not isinstance(transaction_id, str):
                transaction_id = str(transaction_id) if transaction_id else ''
            
            # Handle system events - set closing action appropriately
            closing_action = None
            closing_transaction_id = None
            
            if self.is_system_event(transaction):
                event_type = self.get_system_event_type(transaction)
                if event_type == 'EXPIRATION':
                    closing_action = 'EXPIRED'
                elif event_type == 'ASSIGNMENT':
                    closing_action = 'ASSIGNED'
                elif event_type == 'EXERCISE':
                    closing_action = 'EXERCISED'
                elif event_type == 'CASH_SETTLEMENT':
                    closing_action = 'CASH_SETTLED'
                else:
                    closing_action = 'SYSTEM_EVENT'
                
                closing_transaction_id = transaction_id
                # For system events, the position is being closed, so it was previously opened
                # We'll use the original action as opening_action
            
            # Calculate opening and closing amounts
            # For options, amount = price * quantity * 100
            # For stocks, amount = price * quantity  
            multiplier = 100 if 'OPTION' in instrument_type else 1
            total_amount = price * abs(quantity) * multiplier
            
            # Create position
            position = Position(
                position_id=0,  # Will be set when saved to DB
                order_id=order_id,
                account_number=account_number,
                symbol=symbol,
                underlying=underlying,
                instrument_type=instrument_type,
                option_type=option_type,
                strike=strike,
                expiration=expiration,
                quantity=quantity,
                opening_price=price,
                closing_price=price if closing_action else None,
                opening_transaction_id=transaction_id if not closing_action else None,
                closing_transaction_id=closing_transaction_id,
                opening_action=action if not closing_action else None,
                closing_action=closing_action,
                status=PositionStatus.CLOSED if (closing_action or 'TO_CLOSE' in action) else PositionStatus.OPEN,
                pnl=value,  # Use transaction value as realized P&L
                # Enhanced tracking fields
                opening_order_id=order_id if not closing_action else None,
                closing_order_id=order_id if closing_action else None,
                opening_amount=total_amount if not closing_action else None,
                closing_amount=total_amount if closing_action else None
            )
            
            return position
            
        except Exception as e:
            print(f"Error creating position from transaction: {e}")
            return None
    
    def consolidate_positions(self, positions: List[Position]) -> List[Position]:
        """Consolidate matching opening and closing positions with support for partial closes"""
        if not positions:
            return positions
        
        consolidated = []
        used_positions = set()
        
        # Separate opening and closing positions
        opening_positions = []
        closing_positions = []
        
        for i, pos in enumerate(positions):
            if pos.opening_action and ('SELL_TO_OPEN' in pos.opening_action or 'BUY_TO_OPEN' in pos.opening_action):
                opening_positions.append((i, pos))
            elif pos.opening_action and ('BUY_TO_CLOSE' in pos.opening_action or 'SELL_TO_CLOSE' in pos.opening_action):
                closing_positions.append((i, pos))
            else:
                # Neither opening nor closing - keep as-is
                consolidated.append(pos)
                used_positions.add(i)
        
        # Match opening positions with closing positions
        for open_idx, opening_pos in opening_positions:
            if open_idx in used_positions:
                continue
            
            remaining_qty = abs(opening_pos.quantity)
            remaining_pnl = opening_pos.pnl
            matched_closes = []
            
            # Find all matching closing positions for this opening position
            for close_idx, closing_pos in closing_positions:
                if close_idx in used_positions:
                    continue
                
                # Check if this closing position matches the opening position
                if self.positions_match_contract(opening_pos, closing_pos):
                    # Check if actions are compatible (STO with BTC, BTO with STC)
                    if self.actions_are_compatible(opening_pos.opening_action, closing_pos.opening_action):
                        closing_qty = abs(closing_pos.quantity)
                        if closing_qty <= remaining_qty:
                            # This closing position can be fully matched
                            matched_closes.append((close_idx, closing_pos, closing_qty))
                            remaining_qty -= closing_qty
                            used_positions.add(close_idx)
                            
                            if remaining_qty == 0:
                                break  # Fully closed
            
            # Create consolidated positions based on matches
            if matched_closes:
                # Calculate total matched quantity and P&L
                total_matched_qty = sum(qty for _, _, qty in matched_closes)
                total_closing_pnl = sum(close_pos.pnl for _, close_pos, _ in matched_closes)
                
                # Create CLOSED position for matched portion
                matched_portion = total_matched_qty / abs(opening_pos.quantity)
                closed_opening_pnl = opening_pos.pnl * matched_portion
                
                closed_position = Position(
                    position_id=opening_pos.position_id,
                    order_id=opening_pos.order_id,
                    account_number=opening_pos.account_number,
                    symbol=opening_pos.symbol,
                    underlying=opening_pos.underlying,
                    instrument_type=opening_pos.instrument_type,
                    option_type=opening_pos.option_type,
                    strike=opening_pos.strike,
                    expiration=opening_pos.expiration,
                    quantity=total_matched_qty if opening_pos.quantity > 0 else -total_matched_qty,
                    opening_price=opening_pos.opening_price,
                    closing_price=sum(close_pos.opening_price * qty for _, close_pos, qty in matched_closes) / total_matched_qty,
                    opening_transaction_id=opening_pos.opening_transaction_id,
                    closing_transaction_id=','.join(close_pos.opening_transaction_id for _, close_pos, _ in matched_closes),
                    opening_action=opening_pos.opening_action,
                    closing_action=','.join(close_pos.opening_action for _, close_pos, _ in matched_closes),
                    status=PositionStatus.CLOSED,
                    pnl=closed_opening_pnl + total_closing_pnl,
                    fill_count=opening_pos.fill_count + sum(close_pos.fill_count for _, close_pos, _ in matched_closes),
                    created_at=opening_pos.created_at,
                    updated_at=opening_pos.updated_at
                )
                consolidated.append(closed_position)
                
                # Create OPEN position for remaining portion if any
                if remaining_qty > 0:
                    remaining_portion = remaining_qty / abs(opening_pos.quantity)
                    remaining_opening_pnl = opening_pos.pnl * remaining_portion
                    
                    open_position = Position(
                        position_id=opening_pos.position_id + 100000,  # Offset to avoid ID conflicts
                        order_id=opening_pos.order_id,
                        account_number=opening_pos.account_number,
                        symbol=opening_pos.symbol,
                        underlying=opening_pos.underlying,
                        instrument_type=opening_pos.instrument_type,
                        option_type=opening_pos.option_type,
                        strike=opening_pos.strike,
                        expiration=opening_pos.expiration,
                        quantity=remaining_qty if opening_pos.quantity > 0 else -remaining_qty,
                        opening_price=opening_pos.opening_price,
                        closing_price=None,
                        opening_transaction_id=opening_pos.opening_transaction_id,
                        closing_transaction_id=None,
                        opening_action=opening_pos.opening_action,
                        closing_action=None,
                        status=PositionStatus.OPEN,
                        pnl=remaining_opening_pnl,
                        fill_count=opening_pos.fill_count,
                        created_at=opening_pos.created_at,
                        updated_at=opening_pos.updated_at
                    )
                    consolidated.append(open_position)
            else:
                # No matching closes found, keep as open position
                consolidated.append(opening_pos)
            
            used_positions.add(open_idx)
        
        # Add any unmatched closing positions (orphaned closes)
        for close_idx, closing_pos in closing_positions:
            if close_idx not in used_positions:
                consolidated.append(closing_pos)
        
        return consolidated
    
    def positions_match_contract(self, pos1: Position, pos2: Position) -> bool:
        """Check if two positions represent the same option contract"""
        return (
            pos1.underlying == pos2.underlying and
            pos1.option_type == pos2.option_type and
            pos1.strike == pos2.strike and
            pos1.expiration == pos2.expiration and
            pos1.account_number == pos2.account_number
        )
    
    def actions_are_compatible(self, opening_action: str, closing_action: str) -> bool:
        """Check if opening and closing actions are compatible"""
        if not opening_action or not closing_action:
            return False
            
        opening_action = opening_action.upper()
        closing_action = closing_action.upper()
        
        # Remove ORDERACTION. prefix if present
        opening_action = opening_action.replace('ORDERACTION.', '')
        closing_action = closing_action.replace('ORDERACTION.', '')
        
        # STO should be closed with BTC
        if 'SELL_TO_OPEN' in opening_action and 'BUY_TO_CLOSE' in closing_action:
            return True
        
        # BTO should be closed with STC  
        if 'BUY_TO_OPEN' in opening_action and 'SELL_TO_CLOSE' in closing_action:
            return True
        
        return False
    
    def consolidate_chain_positions(self, chain: Dict):
        """Consolidate positions across all orders within a chain"""
        if not chain or 'orders' not in chain:
            return
        
        logger.info(f"Consolidating chain {chain['chain_id']}")
        
        # Collect all positions from all orders in the chain
        all_positions = []
        for order in chain['orders']:
            if hasattr(order, 'positions') and order.positions:
                logger.info(f"  Order {order.order_id}: {len(order.positions)} positions")
                all_positions.extend(order.positions)
        
        if not all_positions:
            logger.info(f"  No positions found for chain {chain['chain_id']}")
            return
        
        logger.info(f"  Total positions before consolidation: {len(all_positions)}")
        for i, pos in enumerate(all_positions):
            logger.info(f"    Before: {i+1}. {pos.symbol} - {pos.opening_action} - {pos.closing_action} - P&L: ${pos.pnl}")
        
        # Positions are already Position objects, so consolidate directly
        consolidated_positions = self.consolidate_positions(all_positions)
        
        logger.info(f"  Total positions after consolidation: {len(consolidated_positions)}")
        for i, pos in enumerate(consolidated_positions):
            logger.info(f"    {i+1}. {pos.symbol} - {pos.status.value} - P&L: ${pos.pnl}")
        
        # Update the database with consolidated positions
        self.update_chain_positions_in_database(chain['chain_id'], consolidated_positions)
    
    def update_chain_positions_in_database(self, chain_id: str, consolidated_positions: List[Position]):
        """Update positions in database with consolidated versions"""
        try:
            logger.info(f"Updating database for chain {chain_id} with {len(consolidated_positions)} consolidated positions")
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get all order IDs in this chain
                cursor.execute("""
                    SELECT order_id FROM order_chain_members WHERE chain_id = ?
                """, (chain_id,))
                order_ids = [row[0] for row in cursor.fetchall()]
                
                if not order_ids:
                    logger.warning(f"No order IDs found for chain {chain_id}")
                    return
                
                logger.info(f"Found order IDs for chain {chain_id}: {order_ids}")
                
                # Delete existing positions for these orders
                placeholders = ','.join(['?' for _ in order_ids])
                delete_query = f"DELETE FROM positions_new WHERE order_id IN ({placeholders})"
                logger.info(f"Deleting existing positions: {delete_query}")
                cursor.execute(delete_query, order_ids)
                deleted_count = cursor.rowcount
                logger.info(f"Deleted {deleted_count} existing positions")
                
                # Insert consolidated positions
                inserted_count = 0
                for pos in consolidated_positions:
                    cursor.execute("""
                        INSERT INTO positions_new (
                            order_id, account_number, symbol, underlying, instrument_type,
                            option_type, strike, expiration, quantity, opening_price,
                            closing_price, opening_transaction_id, closing_transaction_id,
                            opening_action, closing_action, status, pnl,
                            opening_order_id, closing_order_id, opening_amount, closing_amount,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pos.order_id, pos.account_number, pos.symbol, pos.underlying,
                        pos.instrument_type, pos.option_type, pos.strike, pos.expiration,
                        pos.quantity, pos.opening_price, pos.closing_price,
                        pos.opening_transaction_id, pos.closing_transaction_id,
                        pos.opening_action, pos.closing_action, pos.status.value,
                        pos.pnl, pos.opening_order_id, pos.closing_order_id,
                        pos.opening_amount, pos.closing_amount, pos.created_at, pos.updated_at
                    ))
                    inserted_count += 1
                
                logger.info(f"Inserted {inserted_count} consolidated positions")
                conn.commit()
                logger.info(f"Database update committed for chain {chain_id}")
                
        except Exception as e:
            logger.error(f"Error updating database for chain {chain_id}: {e}")
            raise e
    
    def create_orders_from_transactions(self, transactions: List[Dict]) -> List[Order]:
        """Process raw transactions into Order objects"""
        # Group transactions by order ID
        orders_dict = self.group_transactions_by_order_id(transactions)
        
        orders = []
        for order_id, order_transactions in orders_dict.items():
            order = self.create_order_from_transactions(order_id, order_transactions)
            if order:
                orders.append(order)
        
        return orders
    
    def save_order_to_database(self, order: Order) -> bool:
        """Save an Order and its positions to the database"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert order
                cursor.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, account_number, underlying, order_type, strategy_type,
                        order_date, status, total_quantity, total_pnl,
                        has_assignment, has_expiration, has_exercise, linked_order_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.order_id, order.account_number, order.underlying,
                    order.order_type.value, order.strategy_type, order.order_date,
                    order.status.value, order.total_quantity, order.total_pnl,
                    order.has_assignment, order.has_expiration, order.has_exercise,
                    order.linked_order_id
                ))
                
                # Delete existing positions for this order
                cursor.execute("DELETE FROM positions_new WHERE order_id = ?", (order.order_id,))
                
                # Insert positions
                for position in order.positions:
                    cursor.execute("""
                        INSERT INTO positions_new (
                            order_id, account_number, symbol, underlying, instrument_type,
                            option_type, strike, expiration, quantity, opening_price,
                            closing_price, opening_transaction_id, closing_transaction_id,
                            opening_action, closing_action, status, pnl,
                            opening_order_id, closing_order_id, opening_amount, closing_amount
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        position.order_id, position.account_number, position.symbol,
                        position.underlying, position.instrument_type, position.option_type,
                        position.strike, position.expiration, position.quantity,
                        position.opening_price, position.closing_price,
                        position.opening_transaction_id, position.closing_transaction_id,
                        position.opening_action, position.closing_action,
                        position.status.value, position.pnl,
                        position.opening_order_id, position.closing_order_id,
                        position.opening_amount, position.closing_amount
                    ))
                
                return True
                
        except Exception as e:
            print(f"Error saving order {order.order_id}: {e}")
            return False
    
    def create_order_chains_from_orders(self, orders: List[Order]) -> List[Dict]:
        """Create order chains by linking related orders using position-based analysis"""
        return self.build_position_based_chains(orders)
    
    def build_position_based_chains(self, orders: List[Order]) -> List[Dict]:
        """Advanced chaining based on actual position relationships"""
        chains = []
        used_orders = set()
        
        # Group orders by underlying and account
        grouped_orders = {}
        for order in orders:
            key = (order.underlying, order.account_number)
            if key not in grouped_orders:
                grouped_orders[key] = []
            grouped_orders[key].append(order)
        
        # Process each group using position-based logic
        for (underlying, account), group_orders in grouped_orders.items():
            # Sort by order date
            group_orders.sort(key=lambda o: o.order_date or date.min)
            
            # Build position inventory for this underlying/account
            chains_for_group = self.build_chains_for_symbol_group(group_orders, used_orders)
            chains.extend(chains_for_group)
        
        return chains
    
    def build_chains_for_symbol_group(self, group_orders: List[Order], used_orders: set) -> List[Dict]:
        """Build chains for a specific underlying/account group using position matching"""
        chains = []
        
        # Create position inventory: track what's opened and what closes it
        position_inventory = {}  # position_key -> {'opens': [orders], 'closes': [orders]}
        
        # Build inventory of all positions
        for order in group_orders:
            # Skip already used orders
            if order.order_id in used_orders:
                continue
                
            for position in order.positions:
                pos_key = self.get_position_key(position)
                if pos_key not in position_inventory:
                    position_inventory[pos_key] = {'opens': [], 'closes': []}
                
                # Determine if this position opens or closes based on action
                if hasattr(position, 'opening_action'):
                    action = position.opening_action or ''
                else:
                    action = position.get('opening_action', '') or ''
                    
                if 'BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action:
                    position_inventory[pos_key]['opens'].append((order, position))
                elif 'BUY_TO_CLOSE' in action or 'SELL_TO_CLOSE' in action:
                    position_inventory[pos_key]['closes'].append((order, position))
        
        # Build chains by matching opens to closes
        opening_orders = [o for o in group_orders if o.order_type == OrderType.OPENING and o.order_id not in used_orders]
        
        for opening_order in opening_orders:
            if opening_order.order_id in used_orders:
                continue
                
            # Find all orders that are related to this opening order through positions
            related_orders = self.find_related_orders(opening_order, position_inventory, group_orders, used_orders)
            
            if related_orders:
                # Sort by date to maintain chronological order
                related_orders.sort(key=lambda o: o.order_date or date.min)
                
                # Mark all as used
                for order in related_orders:
                    used_orders.add(order.order_id)
                
                # Create chain
                chain = self.create_order_chain_from_orders(related_orders)
                if chain:
                    chains.append(chain)
        
        # Handle remaining unprocessed orders (including expiration orders)
        for order in group_orders:
            if order.order_id not in used_orders:
                # For expiration orders, try to find matching chain
                if order.order_id.startswith('SYSTEM_EXPIRATION_'):
                    matched = self.try_match_expiration_to_chain(order, chains, used_orders)
                    if matched:
                        continue
                
                # Only create standalone chain for opening orders or system events
                # Rolling/Closing orders without a chain indicate missing data
                if order.order_type == OrderType.OPENING or order.order_id.startswith('SYSTEM_'):
                    chain = self.create_order_chain_from_orders([order])
                    if chain:
                        chains.append(chain)
                    used_orders.add(order.order_id)
                else:
                    # Check if this is a stock-only order (not part of option chains)
                    is_stock_only = True
                    stock_actions = []
                    
                    for position in order.positions:
                        if hasattr(position, 'instrument_type'):
                            instrument_type = position.instrument_type
                            symbol = getattr(position, 'symbol', '')
                            action = getattr(position, 'opening_action', '')
                            quantity = getattr(position, 'quantity', 0)
                        else:
                            instrument_type = position.get('instrument_type', '')
                            symbol = position.get('symbol', '')
                            action = position.get('opening_action', '')
                            quantity = position.get('quantity', 0)
                        
                        if 'OPTION' in str(instrument_type):
                            is_stock_only = False
                            break
                        elif 'EQUITY' in str(instrument_type):
                            # Extract action abbreviation (STC, BTC, etc.)
                            action_abbrev = action.replace('ORDERACTION.', '').replace('OrderAction.', '')
                            if action_abbrev.startswith('SELL_TO_CLOSE'):
                                action_abbrev = 'STC'
                            elif action_abbrev.startswith('BUY_TO_CLOSE'):
                                action_abbrev = 'BTC'
                            elif action_abbrev.startswith('SELL_TO_OPEN'):
                                action_abbrev = 'STO'
                            elif action_abbrev.startswith('BUY_TO_OPEN'):
                                action_abbrev = 'BTO'
                            
                            stock_actions.append(f"{action_abbrev} {quantity} {symbol}")
                    
                    if is_stock_only:
                        # Log as stock transaction, not orphaned order
                        actions_str = ', '.join(stock_actions)
                        print(f"INFO: {order.order_type.value} stock transaction {order.order_id} on {order.order_date}: {actions_str}")
                    else:
                        # Log warning for orphaned rolling/closing orders with options
                        print(f"WARNING: Orphaned {order.order_type.value} order {order.order_id} on {order.order_date} - no matching chain found")
                    
                    used_orders.add(order.order_id)  # Mark as used to prevent duplicates
        
        return chains
    
    def match_expiration_orders_to_chains(self, expiration_orders: List[Order], chains: List[Dict], used_orders: set):
        """Match expiration orders to existing chains based on position symbols"""
        
        for exp_order in expiration_orders:
            # Get the position symbols this expiration order is closing
            expired_symbols = set()
            for position in exp_order.positions:
                if hasattr(position, 'symbol'):
                    expired_symbols.add(position.symbol)
                else:
                    expired_symbols.add(position.get('symbol', ''))
            
            if not expired_symbols:
                continue
            
            # Find chains that have positions in these symbols
            matching_chain = None
            best_match_score = 0
            
            for chain in chains:
                if chain['chain_status'] == 'CLOSED':
                    continue  # Skip already closed chains
                
                # Check positions in this chain's orders
                chain_symbols = set()
                for order in chain['orders']:
                    for position in order.positions:
                        if hasattr(position, 'symbol'):
                            chain_symbols.add(position.symbol)
                        else:
                            chain_symbols.add(position.get('symbol', ''))
                
                # Calculate match score (number of matching symbols)
                match_score = len(expired_symbols & chain_symbols)
                if match_score > best_match_score:
                    best_match_score = match_score
                    matching_chain = chain
            
            # Add expiration order to the best matching chain
            if matching_chain and best_match_score > 0:
                # Add the expiration order to the chain
                matching_chain['orders'].append(exp_order)
                matching_chain['order_count'] = len(matching_chain['orders'])
                
                # Update chain totals
                matching_chain['total_pnl'] += exp_order.total_pnl
                
                # Update chain status to closed
                matching_chain['chain_status'] = 'CLOSED'
                matching_chain['closing_date'] = exp_order.order_date
                
                # Mark expiration order as used
                used_orders.add(exp_order.order_id)
                
                print(f"Matched expiration order {exp_order.order_id} to chain {matching_chain['chain_id']}")
            else:
                print(f"No matching chain found for expiration order {exp_order.order_id} with symbols {expired_symbols}")
    
    def try_match_expiration_to_chain(self, exp_order: Order, chains: List[Dict], used_orders: set) -> bool:
        """Try to match an expiration order to an existing chain"""
        # Get the position symbols this expiration order is closing
        expired_symbols = set()
        for position in exp_order.positions:
            if hasattr(position, 'symbol'):
                expired_symbols.add(position.symbol)
            else:
                expired_symbols.add(position.get('symbol', ''))
        
        if not expired_symbols:
            return False
        
        # Find chains that have positions in these symbols
        matching_chain = None
        best_match_score = 0
        
        for chain in chains:
            if chain['chain_status'] == 'CLOSED':
                continue  # Skip already closed chains
            
            # Check positions in this chain's orders
            chain_symbols = set()
            for order in chain['orders']:
                for position in order.positions:
                    if hasattr(position, 'symbol'):
                        chain_symbols.add(position.symbol)
                    else:
                        chain_symbols.add(position.get('symbol', ''))
            
            # Calculate match score (number of matching symbols)
            match_score = len(expired_symbols & chain_symbols)
            if match_score > best_match_score:
                best_match_score = match_score
                matching_chain = chain
        
        # Add expiration order to the best matching chain
        if matching_chain and best_match_score > 0:
            # Add the expiration order to the chain
            matching_chain['orders'].append(exp_order)
            matching_chain['order_count'] = len(matching_chain['orders'])
            
            # Update chain totals
            matching_chain['total_pnl'] += exp_order.total_pnl
            
            # Update chain status to closed
            matching_chain['chain_status'] = 'CLOSED'
            matching_chain['closing_date'] = exp_order.order_date
            
            # Mark expiration order as used
            used_orders.add(exp_order.order_id)
            
            print(f"Matched expiration order {exp_order.order_id} to chain {matching_chain['chain_id']}")
            return True
        
        return False
    
    def get_position_key(self, position) -> str:
        """Create a unique key for a position to match opens with closes"""
        if hasattr(position, 'symbol'):
            # Position object (dataclass)
            symbol = position.symbol
        else:
            # Position dict
            symbol = position.get('symbol', '')
        # For options, use the full symbol which includes strike and expiration
        # For stocks, just use the symbol
        return symbol
    
    def find_related_orders(self, opening_order: Order, position_inventory: Dict, all_orders: List[Order], used_orders: set) -> List[Order]:
        """Find all orders related to an opening order through position relationships"""
        related_orders = [opening_order]
        
        # Track position balances to detect when chain is complete
        position_balances = {}  # position_key -> net_quantity
        
        # Initialize with opening order positions
        for position in opening_order.positions:
            if hasattr(position, 'opening_action'):
                action = position.opening_action or ''
                quantity = position.quantity if hasattr(position, 'quantity') else position.get('quantity', 0)
            else:
                action = position.get('opening_action', '') or ''
                quantity = position.get('quantity', 0)
                
            if 'BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action:
                pos_key = self.get_position_key(position)
                if pos_key not in position_balances:
                    position_balances[pos_key] = 0
                
                # Track net position: positive for short positions, negative for long positions
                if 'SELL_TO_OPEN' in action:
                    position_balances[pos_key] += abs(quantity)  # Short position
                else:  # BUY_TO_OPEN
                    position_balances[pos_key] -= abs(quantity)  # Long position
        
        if not position_balances:
            return related_orders
        
        # Sort orders by date to process them chronologically
        sorted_orders = sorted(all_orders, key=lambda o: o.order_date or date.min)
        
        # Find orders that close these positions or open additional related positions
        for order in sorted_orders:
            if order.order_id == opening_order.order_id:
                continue
                
            # Skip orders that have already been used in another chain
            if order.order_id in used_orders:
                continue
                
            # Check if this order affects any of our tracked positions
            closes_our_positions = False
            opens_related_positions = False
            
            for position in order.positions:
                pos_key = self.get_position_key(position)
                if hasattr(position, 'opening_action'):
                    action = position.opening_action or ''
                    quantity = position.quantity if hasattr(position, 'quantity') else position.get('quantity', 0)
                else:
                    action = position.get('opening_action', '') or ''
                    quantity = position.get('quantity', 0)
                
                if 'BUY_TO_CLOSE' in action or 'SELL_TO_CLOSE' in action:
                    if pos_key in position_balances:
                        closes_our_positions = True
                elif 'BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action:
                    # Check if this opens positions on the same underlying
                    if pos_key.startswith(opening_order.underlying):
                        opens_related_positions = True
            
            # Include this order if it closes our positions
            if closes_our_positions:
                related_orders.append(order)
                
                # Update position balances based on this order's actions
                for pos in order.positions:
                    if hasattr(pos, 'opening_action'):
                        action = pos.opening_action or ''
                        quantity = pos.quantity if hasattr(pos, 'quantity') else pos.get('quantity', 0)
                    else:
                        action = pos.get('opening_action', '') or ''
                        quantity = pos.get('quantity', 0)
                    
                    pos_key = self.get_position_key(pos)
                    
                    if pos_key not in position_balances:
                        position_balances[pos_key] = 0
                    
                    if 'BUY_TO_OPEN' in action:
                        position_balances[pos_key] -= abs(quantity)  # Long position
                    elif 'SELL_TO_OPEN' in action:
                        position_balances[pos_key] += abs(quantity)  # Short position
                    elif 'BUY_TO_CLOSE' in action:
                        position_balances[pos_key] -= abs(quantity)  # Close short position
                    elif 'SELL_TO_CLOSE' in action:
                        position_balances[pos_key] += abs(quantity)  # Close long position
                
                # Check if this order closes ALL positions (chain complete)
                if order.order_type == OrderType.CLOSING:
                    all_positions_closed = True
                    for pos_key, balance in position_balances.items():
                        if abs(balance) > 0.01:  # Allow for small rounding errors
                            all_positions_closed = False
                            break
                    
                    # If all positions are closed, stop adding more orders to this chain
                    if all_positions_closed:
                        break
            
            # Only add rolling orders if they actually affect our tracked positions
            elif order.order_type == OrderType.ROLLING:
                # A rolling order should both close existing positions AND open new ones
                affects_our_positions = False
                
                for position in order.positions:
                    pos_key = self.get_position_key(position)
                    if hasattr(position, 'opening_action'):
                        action = position.opening_action or ''
                    else:
                        action = position.get('opening_action', '') or ''
                    
                    # Check if this position closes any of our tracked positions
                    if ('BUY_TO_CLOSE' in action or 'SELL_TO_CLOSE' in action) and pos_key in position_balances:
                        affects_our_positions = True
                        break
                
                if affects_our_positions:
                    related_orders.append(order)
                    
                    # Update position balances for rolling orders
                    for pos in order.positions:
                        if hasattr(pos, 'opening_action'):
                            action = pos.opening_action or ''
                            quantity = pos.quantity if hasattr(pos, 'quantity') else pos.get('quantity', 0)
                        else:
                            action = pos.get('opening_action', '') or ''
                            quantity = pos.get('quantity', 0)
                        
                        pos_key = self.get_position_key(pos)
                        
                        if pos_key not in position_balances:
                            position_balances[pos_key] = 0
                        
                        if 'BUY_TO_OPEN' in action:
                            position_balances[pos_key] -= abs(quantity)  # Long position
                        elif 'SELL_TO_OPEN' in action:
                            position_balances[pos_key] += abs(quantity)  # Short position
                        elif 'BUY_TO_CLOSE' in action:
                            position_balances[pos_key] -= abs(quantity)  # Close short position
                        elif 'SELL_TO_CLOSE' in action:
                            position_balances[pos_key] += abs(quantity)  # Close long position
        
        return related_orders
    
    def create_order_chain_from_orders(self, orders: List[Order]) -> Optional[Dict]:
        """Create an order chain from a list of related orders"""
        if not orders:
            return None
        
        # Sort orders by date
        orders.sort(key=lambda o: o.order_date or date.min)
        
        opening_order = orders[0]
        closing_order = orders[-1] if orders[-1].order_type == OrderType.CLOSING else None
        
        # Generate chain ID
        date_str = opening_order.order_date.strftime('%Y%m%d') if opening_order.order_date else 'UNKNOWN'
        order_id_str = str(opening_order.order_id) if opening_order.order_id else 'UNKNOWN'
        chain_id = f"{opening_order.underlying}_{opening_order.order_type.value}_{date_str}_{order_id_str[:8]}"
        
        # Calculate chain totals
        total_pnl = sum(order.total_pnl for order in orders)
        
        # Determine chain status
        if closing_order:
            chain_status = ChainStatus.CLOSED
            closing_date = closing_order.order_date
        else:
            chain_status = ChainStatus.OPEN
            closing_date = None
        
        chain = {
            'chain_id': chain_id,
            'underlying': opening_order.underlying,
            'account_number': opening_order.account_number,
            'opening_order_id': opening_order.order_id,
            'strategy_type': opening_order.strategy_type,
            'opening_date': opening_order.order_date,
            'closing_date': closing_date,
            'chain_status': chain_status.value,
            'order_count': len(orders),
            'total_pnl': total_pnl,
            'orders': orders
        }
        
        return chain
    
    def save_order_chain_to_database(self, chain: Dict) -> bool:
        """Save an order chain to the database"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert chain
                cursor.execute("""
                    INSERT OR REPLACE INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id, strategy_type, 
                        opening_date, closing_date, chain_status, order_count, total_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain['chain_id'], chain['underlying'], chain['account_number'],
                    chain['opening_order_id'], chain['strategy_type'], chain['opening_date'], 
                    chain['closing_date'], chain['chain_status'], chain['order_count'], chain['total_pnl']
                ))
                
                # Delete existing chain members
                cursor.execute("DELETE FROM order_chain_members WHERE chain_id = ?", (chain['chain_id'],))
                
                # Insert chain members
                for i, order in enumerate(chain['orders']):
                    cursor.execute("""
                        INSERT INTO order_chain_members (
                            chain_id, order_id, sequence_number
                        ) VALUES (?, ?, ?)
                    """, (chain['chain_id'], order.order_id, i + 1))
                
                return True
                
        except Exception as e:
            print(f"Error saving order chain {chain['chain_id']}: {e}")
            return False
    
    def process_transactions_to_orders_and_chains(self, transactions: List[Dict]) -> Dict:
        """Main method to process raw transactions into orders and chains"""
        try:
            print(f"Processing {len(transactions)} transactions")
            
            # Create orders from transactions
            orders = self.create_orders_from_transactions(transactions)
            print(f"Created {len(orders)} orders")
            
            # Save orders to database
            saved_orders = 0
            for i, order in enumerate(orders):
                try:
                    if self.save_order_to_database(order):
                        saved_orders += 1
                except Exception as e:
                    print(f"Error saving order {i}: {e}")
            
            print(f"Saved {saved_orders} orders")
            
            # Create and save order chains
            chains = self.create_order_chains_from_orders(orders)
            print(f"Created {len(chains)} chains")
            
            # Save chains to database first
            saved_chains = 0
            for i, chain in enumerate(chains):
                try:
                    if self.save_order_chain_to_database(chain):
                        saved_chains += 1
                except Exception as e:
                    print(f"Error saving chain {i}: {e}")
            
            print(f"Saved {saved_chains} chains")
            
            # Skip chain-level consolidation to preserve order-level transaction display
            # Each order should show its own transactions (BTC, STO, etc.)
            # for chain in chains:
            #     self.consolidate_chain_positions(chain)
            #     # Recalculate chain P&L after consolidation
            #     self.update_chain_pnl(chain['chain_id'])
            # print(f"Consolidated positions across chain orders")
            
            # Just update chain P&L without consolidation
            for chain in chains:
                self.update_chain_pnl(chain['chain_id'])
            
            return {
                'orders_processed': len(orders),
                'orders_saved': saved_orders,
                'chains_created': len(chains),
                'chains_saved': saved_chains
            }
            
        except Exception as e:
            import traceback
            print(f"Error processing transactions: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                'orders_processed': 0,
                'orders_saved': 0,
                'chains_created': 0,
                'chains_saved': 0,
                'error': str(e)
            }
    
    def load_raw_transactions_from_database(self) -> List[Dict]:
        """Load raw transactions from database for reprocessing"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM raw_transactions 
                    WHERE instrument_type IS NOT NULL 
                    AND symbol IS NOT NULL
                    ORDER BY executed_at
                """)
                
                rows = cursor.fetchall()
                
                # Convert rows to dictionaries
                transactions = []
                for row in rows:
                    transaction = dict(row)
                    transactions.append(transaction)
                
                print(f"Loaded {len(transactions)} raw transactions from database")
                return transactions
                
        except Exception as e:
            print(f"Error loading raw transactions: {e}")
            return []
    
    def reprocess_orders_and_chains_from_database(self) -> Dict:
        """Reprocess orders and chains using existing raw transactions"""
        try:
            print("Starting reprocessing from database...")
            
            # Clear existing orders and chains
            print("Clearing existing orders and chains...")
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM order_chain_members")
                cursor.execute("DELETE FROM order_chains") 
                cursor.execute("DELETE FROM positions_new")
                cursor.execute("DELETE FROM orders")
                print("Cleared existing data")
            
            # Load raw transactions from database
            transactions = self.load_raw_transactions_from_database()
            
            if not transactions:
                return {
                    'orders_processed': 0,
                    'orders_saved': 0,
                    'chains_created': 0,
                    'chains_saved': 0,
                    'error': 'No raw transactions found in database'
                }
            
            # Process using existing logic
            result = self.process_transactions_to_orders_and_chains(transactions)
            
            print(f"Reprocessing completed: {result['orders_saved']} orders, {result['chains_saved']} chains")
            return result
            
        except Exception as e:
            import traceback
            print(f"Error during reprocessing: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                'orders_processed': 0,
                'orders_saved': 0,
                'chains_created': 0,
                'chains_saved': 0,
                'error': str(e)
            }