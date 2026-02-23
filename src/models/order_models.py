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

    @property
    def commission(self) -> float:
        """Commission for this position (not tracked at position level)"""
        return 0.0

    @property
    def regulatory_fees(self) -> float:
        """Regulatory fees for this position (not tracked at position level)"""
        return 0.0

    @property
    def clearing_fees(self) -> float:
        """Clearing fees for this position (not tracked at position level)"""
        return 0.0

    # Legacy transaction-like properties for backward compatibility
    @property
    def is_closing(self) -> bool:
        """Whether this position is a closing transaction"""
        return bool(self.closing_action)

    @property
    def is_opening(self) -> bool:
        """Whether this position is an opening transaction"""
        return not self.closing_action

    @property
    def is_buy(self) -> bool:
        """Whether the opening action was a buy"""
        return 'BUY' in str(self.opening_action).upper()

    @property
    def is_sell(self) -> bool:
        """Whether the opening action was a sell"""
        return 'SELL' in str(self.opening_action).upper()

    @property
    def is_assignment(self) -> bool:
        """Whether this position was closed by assignment"""
        return self.closing_action == 'ASSIGNED' if self.closing_action else False

    @property
    def is_exercise(self) -> bool:
        """Whether this position was closed by exercise"""
        return self.closing_action == 'EXERCISED' if self.closing_action else False

    @property
    def is_expiration(self) -> bool:
        """Whether this position was closed by expiration"""
        return self.closing_action == 'EXPIRED' if self.closing_action else False

    @property
    def underlying_symbol(self) -> str:
        """Underlying symbol (alias for compatibility)"""
        return self.underlying

    @property
    def price(self) -> float:
        """Opening price (alias for compatibility)"""
        return self.opening_price

    @property
    def id(self) -> str:
        """Position ID (alias for compatibility)"""
        return str(self.position_id)

    @property
    def action(self) -> str:
        """Opening action (alias for compatibility)"""
        return self.opening_action

    # executed_at would need to be added as a field; using a datetime from created_at for now
    @property
    def executed_at(self) -> datetime:
        """Execution timestamp (using created_at as proxy)"""
        return self.created_at or datetime.now()


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

    @property
    def transactions(self) -> List[Position]:
        """Alias for positions to support legacy code that accesses .transactions"""
        return self.positions

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
        from src.database.models import OrderChain as OC, Order as OrderModel, OrderChainMember as OCM, OrderPosition as OP

        with self.db.get_session() as session:
            q = session.query(OC)
            if account_number:
                q = q.filter(OC.account_number == account_number)
            q = q.order_by(OC.created_at.desc()).limit(limit).offset(offset)
            chains_data = q.all()

            chain_ids = [c.chain_id for c in chains_data]
            if not chain_ids:
                return []

            # Batch-load members (chain_id → list of order_ids in sequence order)
            member_rows = (
                session.query(OCM.chain_id, OCM.order_id, OCM.sequence_number)
                .filter(OCM.chain_id.in_(chain_ids))
                .order_by(OCM.chain_id, OCM.sequence_number)
                .all()
            )
            members_by_chain: Dict[str, list] = {cid: [] for cid in chain_ids}
            all_order_ids = set()
            for cid, oid, _seq in member_rows:
                members_by_chain[cid].append(oid)
                all_order_ids.add(oid)

            # Batch-load orders
            order_rows = session.query(OrderModel).filter(
                OrderModel.order_id.in_(list(all_order_ids)),
            ).all()
            order_by_id = {o.order_id: o.to_dict() for o in order_rows}

            # Batch-load positions
            pos_rows = session.query(OP).filter(
                OP.order_id.in_(list(all_order_ids)),
            ).order_by(OP.symbol).all()
            pos_by_order: Dict[str, list] = {}
            for p in pos_rows:
                pos_by_order.setdefault(p.order_id, []).append(p.to_dict())

            # Assemble result
            chains = []
            for c in chains_data:
                chain_dict = c.to_dict()
                orders = []
                for oid in members_by_chain.get(c.chain_id, []):
                    od = order_by_id.get(oid)
                    if od:
                        od['positions'] = pos_by_order.get(oid, [])
                        orders.append(od)
                chain_dict['orders'] = orders
                chains.append(chain_dict)

            return chains
    
    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific order with its positions"""
        from src.database.models import Order as OrderModel, OrderPosition as OP

        with self.db.get_session() as session:
            row = session.get(OrderModel, order_id)
            if not row:
                return None
            order_dict = row.to_dict()
            positions = (
                session.query(OP)
                .filter(OP.order_id == order_id)
                .order_by(OP.symbol)
                .all()
            )
            order_dict['positions'] = [p.to_dict() for p in positions]
            return order_dict
    
    def get_positions_by_account(self, account_number: str,
                               status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get positions for an account, optionally filtered by status"""
        from src.database.models import OrderPosition as OP

        with self.db.get_session() as session:
            q = session.query(OP).filter(OP.account_number == account_number)
            if status:
                q = q.filter(OP.status == status)
            q = q.order_by(OP.created_at.desc())
            return [row.to_dict() for row in q.all()]
    
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
        from src.database.models import Order as OrderModel, OrderPosition as OP

        with self.db.get_session() as session:
            pos_rows = session.query(OP).filter(OP.order_id == order_id).all()
            total_pnl = 0.0

            for pos_row in pos_rows:
                position = pos_row.to_dict()
                realized_pnl = self.calculate_realized_position_pnl(position)
                total_pnl += realized_pnl

                if abs(realized_pnl - (pos_row.pnl or 0.0)) > 0.01:
                    pos_row.pnl = realized_pnl
                    pos_row.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            order_row = session.get(OrderModel, order_id)
            if order_row:
                order_row.total_pnl = total_pnl
                order_row.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            return total_pnl
    
    def calculate_chain_realized_pnl(self, chain_id: str, chain_status: str) -> float:
        """Calculate truly realized P&L based on completed round trips

        Logic:
        - Closed chains: All P&L is realized
        - Open chains: Sum net P&L from completed round trips (STO + matching BTC)
        """
        from sqlalchemy import func as sa_func
        from src.database.models import OrderPosition as OP, OrderChainMember as OCM

        with self.db.get_session() as session:
            if chain_status == 'CLOSED':
                total = (
                    session.query(sa_func.coalesce(sa_func.sum(OP.pnl), 0))
                    .join(OCM, OP.order_id == OCM.order_id)
                    .filter(OCM.chain_id == chain_id)
                    .scalar()
                )
                return total or 0.0

            # Batch-load all positions for this chain (symbol, action, status, pnl, strike, expiration, quantity)
            rows = (
                session.query(
                    OP.symbol, OP.opening_action, OP.status, OP.pnl,
                    OP.strike, OP.expiration, OP.quantity,
                )
                .join(OCM, OP.order_id == OCM.order_id)
                .filter(OCM.chain_id == chain_id)
                .order_by(OP.strike, OP.expiration)
                .all()
            )

            from collections import defaultdict
            position_groups = defaultdict(list)
            for symbol, action, status, pnl, strike, expiration, quantity in rows:
                key = (symbol, strike, expiration)
                position_groups[key].append({
                    'action': action, 'status': status, 'pnl': pnl, 'quantity': quantity,
                })

            realized_pnl = 0.0
            for key, group_positions in position_groups.items():
                opening_quantity = 0
                closing_quantity = 0
                opening_pnl = 0.0
                closing_pnl = 0.0

                for pos in group_positions:
                    action = pos['action'] or ''
                    qty = abs(pos['quantity'] or 0)
                    if 'TO_OPEN' in action:
                        opening_quantity += qty
                        opening_pnl += pos['pnl'] or 0.0
                    elif 'TO_CLOSE' in action:
                        closing_quantity += qty
                        closing_pnl += pos['pnl'] or 0.0

                if opening_quantity > 0 and closing_quantity > 0:
                    completed_quantity = min(opening_quantity, closing_quantity)
                    opening_ratio = completed_quantity / opening_quantity
                    closing_ratio = completed_quantity / closing_quantity
                    realized_pnl += opening_pnl * opening_ratio + closing_pnl * closing_ratio

            return realized_pnl

    def calculate_chain_unrealized_pnl(self, chain_id: str, chain_status: str) -> float:
        """Calculate unrealized P&L from truly open positions (not part of completed round trips)

        Logic:
        - Closed chains: No unrealized P&L
        - Open chains: Sum only OPEN positions that don't have matching closing positions
        """
        from src.database.models import OrderPosition as OP, OrderChainMember as OCM

        if chain_status == 'CLOSED':
            return 0.0

        with self.db.get_session() as session:
            rows = (
                session.query(
                    OP.symbol, OP.opening_action, OP.status, OP.pnl,
                    OP.strike, OP.expiration, OP.quantity,
                )
                .join(OCM, OP.order_id == OCM.order_id)
                .filter(OCM.chain_id == chain_id)
                .order_by(OP.strike, OP.expiration)
                .all()
            )

            from collections import defaultdict
            position_groups = defaultdict(list)
            for symbol, action, status, pnl, strike, expiration, quantity in rows:
                key = (symbol, strike, expiration)
                position_groups[key].append({
                    'action': action, 'status': status, 'pnl': pnl, 'quantity': quantity,
                })

            unrealized_pnl = 0.0
            for key, group_positions in position_groups.items():
                opening_quantity = 0
                closing_quantity = 0
                opening_pnl = 0.0

                for pos in group_positions:
                    action = pos['action'] or ''
                    qty = abs(pos['quantity'] or 0)
                    if 'TO_OPEN' in action:
                        opening_quantity += qty
                        opening_pnl += pos['pnl'] or 0.0
                    elif 'TO_CLOSE' in action:
                        closing_quantity += qty

                if opening_quantity > 0:
                    remaining_open_quantity = max(0, opening_quantity - closing_quantity)
                    if remaining_open_quantity > 0:
                        unrealized_ratio = remaining_open_quantity / opening_quantity
                        unrealized_pnl += opening_pnl * unrealized_ratio

            return unrealized_pnl

    def update_chain_pnl(self, chain_id: str) -> float:
        """Recalculate and update total, realized, and unrealized P&L for an order chain"""
        from sqlalchemy import func as sa_func
        from src.database.models import OrderChain as OC, Order as OrderModel, OrderChainMember as OCM

        with self.db.get_session() as session:
            chain_row = session.get(OC, chain_id)
            if not chain_row:
                return 0.0
            chain_status = chain_row.chain_status

            total_pnl = (
                session.query(sa_func.coalesce(sa_func.sum(OrderModel.total_pnl), 0))
                .join(OCM, OrderModel.order_id == OCM.order_id)
                .filter(OCM.chain_id == chain_id)
                .scalar()
            ) or 0.0

        # These methods open their own sessions
        realized_pnl = self.calculate_chain_realized_pnl(chain_id, chain_status)
        unrealized_pnl = self.calculate_chain_unrealized_pnl(chain_id, chain_status)

        with self.db.get_session() as session:
            chain_row = session.get(OC, chain_id)
            if chain_row:
                chain_row.total_pnl = total_pnl
                chain_row.realized_pnl = realized_pnl
                chain_row.unrealized_pnl = unrealized_pnl
                chain_row.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return total_pnl
    
    def get_order_statistics(self, account_number: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for orders and chains"""
        from sqlalchemy import func as sa_func, case
        from src.database.models import (
            Order as OrderModel, OrderChain as OC, OrderChainMember as OCM, OrderPosition as OP,
        )

        with self.db.get_session() as session:
            # Order stats
            oq = session.query(
                sa_func.count().label('total_orders'),
                sa_func.count(case((OrderModel.status == 'OPEN', 1))).label('open_orders'),
                sa_func.count(case((OrderModel.status == 'CLOSED', 1))).label('closed_orders'),
                sa_func.coalesce(sa_func.sum(OrderModel.total_pnl), 0).label('total_pnl'),
            )
            if account_number:
                oq = oq.filter(OrderModel.account_number == account_number)
            order_row = oq.one()
            order_stats = {
                'total_orders': order_row[0], 'open_orders': order_row[1],
                'closed_orders': order_row[2], 'total_pnl': order_row[3],
            }

            # Chain stats
            if account_number:
                cq = (
                    session.query(
                        sa_func.count(sa_func.distinct(OC.chain_id)).label('total_chains'),
                        sa_func.count(case((OC.chain_status == 'OPEN', 1))).label('open_chains'),
                        sa_func.count(case((OC.chain_status == 'CLOSED', 1))).label('closed_chains'),
                    )
                    .join(OCM, OC.chain_id == OCM.chain_id)
                    .join(OrderModel, OCM.order_id == OrderModel.order_id)
                    .filter(OrderModel.account_number == account_number)
                )
            else:
                cq = session.query(
                    sa_func.count().label('total_chains'),
                    sa_func.count(case((OC.chain_status == 'OPEN', 1))).label('open_chains'),
                    sa_func.count(case((OC.chain_status == 'CLOSED', 1))).label('closed_chains'),
                )
            chain_row = cq.one()
            chain_stats = {
                'total_chains': chain_row[0], 'open_chains': chain_row[1], 'closed_chains': chain_row[2],
            }

            # Position stats
            pq = session.query(
                sa_func.count().label('total_positions'),
                sa_func.count(case((OP.status == 'OPEN', 1))).label('open_positions'),
                sa_func.count(case((OP.status == 'CLOSED', 1))).label('closed_positions'),
            )
            if account_number:
                pq = pq.filter(OP.account_number == account_number)
            pos_row = pq.one()
            position_stats = {
                'total_positions': pos_row[0], 'open_positions': pos_row[1], 'closed_positions': pos_row[2],
            }

            return {**order_stats, **chain_stats, **position_stats}
    
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
        from src.database.models import OrderChainMember as OCM, OrderPosition as OP

        try:
            logger.info(f"Updating database for chain {chain_id} with {len(consolidated_positions)} consolidated positions")

            with self.db.get_session() as session:
                order_ids = [
                    row[0] for row in
                    session.query(OCM.order_id).filter(OCM.chain_id == chain_id).all()
                ]

                if not order_ids:
                    logger.warning(f"No order IDs found for chain {chain_id}")
                    return

                logger.info(f"Found order IDs for chain {chain_id}: {order_ids}")

                deleted_count = (
                    session.query(OP)
                    .filter(OP.order_id.in_(order_ids))
                    .delete(synchronize_session='fetch')
                )
                logger.info(f"Deleted {deleted_count} existing positions")

                inserted_count = 0
                for pos in consolidated_positions:
                    session.add(OP(
                        order_id=pos.order_id, account_number=pos.account_number,
                        symbol=pos.symbol, underlying=pos.underlying,
                        instrument_type=pos.instrument_type, option_type=pos.option_type,
                        strike=pos.strike, expiration=pos.expiration,
                        quantity=pos.quantity, opening_price=pos.opening_price,
                        closing_price=pos.closing_price,
                        opening_transaction_id=pos.opening_transaction_id,
                        closing_transaction_id=pos.closing_transaction_id,
                        opening_action=pos.opening_action, closing_action=pos.closing_action,
                        status=pos.status.value, pnl=pos.pnl,
                        opening_order_id=pos.opening_order_id,
                        closing_order_id=pos.closing_order_id,
                        opening_amount=pos.opening_amount, closing_amount=pos.closing_amount,
                        created_at=pos.created_at, updated_at=pos.updated_at,
                    ))
                    inserted_count += 1

                logger.info(f"Inserted {inserted_count} consolidated positions")
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
        from src.database.engine import dialect_insert
        from src.database.models import Order as OrderModel, OrderPosition as OP

        try:
            with self.db.get_session() as session:
                # Upsert order
                stmt = dialect_insert(OrderModel).values(
                    order_id=order.order_id, account_number=order.account_number,
                    underlying=order.underlying, order_type=order.order_type.value,
                    strategy_type=order.strategy_type, order_date=order.order_date,
                    status=order.status.value, total_quantity=order.total_quantity,
                    total_pnl=order.total_pnl, has_assignment=order.has_assignment,
                    has_expiration=order.has_expiration, has_exercise=order.has_exercise,
                    linked_order_id=order.linked_order_id,
                )
                session.execute(stmt.on_conflict_do_update(
                    index_elements=['order_id'],
                    set_={
                        'account_number': stmt.excluded.account_number,
                        'underlying': stmt.excluded.underlying,
                        'order_type': stmt.excluded.order_type,
                        'strategy_type': stmt.excluded.strategy_type,
                        'order_date': stmt.excluded.order_date,
                        'status': stmt.excluded.status,
                        'total_quantity': stmt.excluded.total_quantity,
                        'total_pnl': stmt.excluded.total_pnl,
                        'has_assignment': stmt.excluded.has_assignment,
                        'has_expiration': stmt.excluded.has_expiration,
                        'has_exercise': stmt.excluded.has_exercise,
                        'linked_order_id': stmt.excluded.linked_order_id,
                    },
                ))

                # Delete existing positions for this order, then insert new
                session.query(OP).filter(OP.order_id == order.order_id).delete()

                for position in order.positions:
                    session.add(OP(
                        order_id=position.order_id, account_number=position.account_number,
                        symbol=position.symbol, underlying=position.underlying,
                        instrument_type=position.instrument_type, option_type=position.option_type,
                        strike=position.strike, expiration=position.expiration,
                        quantity=position.quantity, opening_price=position.opening_price,
                        closing_price=position.closing_price,
                        opening_transaction_id=position.opening_transaction_id,
                        closing_transaction_id=position.closing_transaction_id,
                        opening_action=position.opening_action, closing_action=position.closing_action,
                        status=position.status.value, pnl=position.pnl,
                        opening_order_id=position.opening_order_id,
                        closing_order_id=position.closing_order_id,
                        opening_amount=position.opening_amount, closing_amount=position.closing_amount,
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
    
    def detect_multi_chain_closing_orders(self, group_orders: List[Order], used_orders: set) -> Dict[str, List[Order]]:
        """
        Detect closing orders that affect multiple chains and return the affected opening orders.
        Returns a mapping of closing_order_id -> [affected_opening_orders]
        """
        multi_chain_closings = {}
        
        # Find all closing orders
        closing_orders = [o for o in group_orders if o.order_type == OrderType.CLOSING and o.order_id not in used_orders]
        opening_orders = [o for o in group_orders if o.order_type == OrderType.OPENING and o.order_id not in used_orders]
        
        for closing_order in closing_orders:
            affected_opening_orders = []
            
            # For each position in the closing order, find which opening orders it could close
            for close_pos in closing_order.positions:
                close_action = self.get_position_attr(close_pos, 'opening_action')
                close_symbol = self.get_position_attr(close_pos, 'symbol')
                
                # Skip if not a closing action
                if 'CLOSE' not in close_action:
                    continue
                
                # Find opening orders with matching positions
                for opening_order in opening_orders:
                    if opening_order in affected_opening_orders:
                        continue  # Already found this opening order
                        
                    for open_pos in opening_order.positions:
                        open_action = self.get_position_attr(open_pos, 'opening_action')
                        open_symbol = self.get_position_attr(open_pos, 'symbol')
                        
                        # Check if this closing position matches this opening position
                        if (open_symbol == close_symbol and 
                            'OPEN' in open_action and
                            self.positions_match_for_closing(open_pos, close_pos)):
                            affected_opening_orders.append(opening_order)
                            break  # Found a match in this opening order
            
            # If this closing order affects multiple opening orders, it's a multi-chain closer
            if len(affected_opening_orders) > 1:
                multi_chain_closings[closing_order.order_id] = affected_opening_orders
                logger.info(f"Detected multi-chain closing order {closing_order.order_id} affecting {len(affected_opening_orders)} chains")
        
        return multi_chain_closings

    def get_position_attr(self, position, attr_name: str):
        """Safely get attribute from position (works with both objects and dicts)"""
        value = None
        if hasattr(position, attr_name):
            value = getattr(position, attr_name, '')
        elif hasattr(position, 'get'):
            value = position.get(attr_name, '')
        else:
            value = ''
        
        # Ensure we never return None for string operations
        return value if value is not None else ''

    def positions_match_for_closing(self, open_pos, close_pos) -> bool:
        """Check if a closing position can close an opening position"""
        open_action = self.get_position_attr(open_pos, 'opening_action')
        close_action = self.get_position_attr(close_pos, 'opening_action')
        
        # BUY_TO_OPEN can be closed by SELL_TO_CLOSE
        if 'BUY_TO_OPEN' in open_action and 'SELL_TO_CLOSE' in close_action:
            return True
        # SELL_TO_OPEN can be closed by BUY_TO_CLOSE  
        if 'SELL_TO_OPEN' in open_action and 'BUY_TO_CLOSE' in close_action:
            return True
        
        return False

    def merge_chains(self, opening_orders: List[Order], closing_order: Order) -> Dict:
        """
        Merge multiple opening orders into a single combined chain when closed together.
        Returns a merged chain dictionary.
        """
        if not opening_orders:
            return None
        
        # Sort opening orders by date to maintain chronological order
        opening_orders.sort(key=lambda o: o.order_date or date.min)
        
        # Use the earliest opening order as the base
        base_order = opening_orders[0]
        
        # Create merged chain ID using all opening order IDs
        opening_order_ids = [o.order_id[:8] for o in opening_orders]  # Truncate for brevity
        date_str = base_order.order_date.strftime('%Y%m%d') if base_order.order_date else 'UNKNOWN'
        chain_id = f"{base_order.underlying}_MERGED_{date_str}_{'_'.join(opening_order_ids)}"
        
        # Combine all orders (openings + closing)
        all_orders = opening_orders + [closing_order]
        
        # Calculate combined totals
        total_pnl = sum(order.total_pnl for order in all_orders)
        total_order_count = len(all_orders)
        
        # Determine strategy type
        strategy_types = [o.strategy_type for o in opening_orders if o.strategy_type]
        if len(set(strategy_types)) == 1:
            combined_strategy = strategy_types[0]
        else:
            combined_strategy = "Multi-Strategy"
        
        # Determine chain status based on position balance
        chain_fully_closed = self.is_chain_fully_closed(all_orders)
        chain_status = ChainStatus.CLOSED if chain_fully_closed else ChainStatus.OPEN
        closing_date = closing_order.order_date if chain_fully_closed else None
        
        # Create merged chain
        merged_chain = {
            'chain_id': chain_id,
            'underlying': base_order.underlying,
            'account_number': base_order.account_number,
            'opening_order_id': base_order.order_id,  # Use first opening order as primary
            'strategy_type': combined_strategy,
            'opening_date': base_order.order_date,
            'closing_date': closing_date,
            'chain_status': chain_status.value,
            'order_count': total_order_count,
            'total_pnl': total_pnl,
            'orders': all_orders
        }
        
        logger.info(f"Merged {len(opening_orders)} chains into combined chain {chain_id} with total P&L: ${total_pnl}")
        
        return merged_chain

    def build_chains_for_symbol_group(self, group_orders: List[Order], used_orders: set) -> List[Dict]:
        """Build chains for a specific underlying/account group using position matching"""
        chains = []
        
        # First, detect multi-chain closing orders
        multi_chain_closings = self.detect_multi_chain_closing_orders(group_orders, used_orders)
        
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
                action = self.get_position_attr(position, 'opening_action')
                    
                if 'BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action:
                    position_inventory[pos_key]['opens'].append((order, position))
                elif 'BUY_TO_CLOSE' in action or 'SELL_TO_CLOSE' in action:
                    position_inventory[pos_key]['closes'].append((order, position))
        
        # Handle multi-chain closing orders first (merge chains)
        for close_order_id, affected_opening_orders in multi_chain_closings.items():
            closing_order = next(o for o in group_orders if o.order_id == close_order_id)
            
            # Create merged chain from all affected opening orders + closing order
            merged_chain = self.merge_chains(affected_opening_orders, closing_order)
            if merged_chain:
                chains.append(merged_chain)
                
                # Mark all orders as used
                for order in affected_opening_orders:
                    used_orders.add(order.order_id)
                used_orders.add(close_order_id)
        
        # Build remaining chains using standard logic
        opening_orders = [o for o in group_orders if o.order_type == OrderType.OPENING and o.order_id not in used_orders]
        
        for opening_order in opening_orders:
            if opening_order.order_id in used_orders:
                continue
                
            # Standard chain building logic - OPENING orders ALWAYS create NEW chains
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
                
                # Note: Chain status will be determined by position balance calculation
                # Don't automatically close chains on expiration - let position balance decide
                
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
            
            # Note: Chain status will be determined by position balance calculation
            # Don't automatically close chains on expiration - let position balance decide
            
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
            strike = getattr(position, 'strike', None)
            expiration = getattr(position, 'expiration', None)
        else:
            # Position dict
            symbol = position.get('symbol', '')
            strike = position.get('strike', None)
            expiration = position.get('expiration', None)
        
        # For options, include strike and expiration to create unique keys
        # For stocks, just use the symbol
        if strike is not None and expiration is not None:
            return f"{symbol}_{strike}_{expiration}"
        else:
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
        
        # Generate chain ID
        date_str = opening_order.order_date.strftime('%Y%m%d') if opening_order.order_date else 'UNKNOWN'
        order_id_str = str(opening_order.order_id) if opening_order.order_id else 'UNKNOWN'
        chain_id = f"{opening_order.underlying}_{opening_order.order_type.value}_{date_str}_{order_id_str[:8]}"
        
        # Calculate chain totals
        total_pnl = sum(order.total_pnl for order in orders)
        
        # Determine chain status based on position balance
        chain_fully_closed = self.is_chain_fully_closed(orders)
        chain_status = ChainStatus.CLOSED if chain_fully_closed else ChainStatus.OPEN
        
        
        
        # Only set closing date if chain is actually fully closed
        # Find the latest order that could be considered a "closing" action
        closing_date = None
        if chain_fully_closed:
            # Look for the latest order that closes positions or is a system action
            for order in reversed(orders):
                if (order.order_type == OrderType.CLOSING or 
                    order.order_id.startswith('SYSTEM_') or
                    order.order_type == OrderType.ROLLING):
                    closing_date = order.order_date
                    break
            # If no specific closing order found, use the last order date
            if not closing_date and orders:
                closing_date = orders[-1].order_date
        
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
        from src.database.engine import dialect_insert
        from src.database.models import OrderChain as OC, OrderChainMember as OCM

        try:
            with self.db.get_session() as session:
                # Upsert chain
                stmt = dialect_insert(OC).values(
                    chain_id=chain['chain_id'], underlying=chain['underlying'],
                    account_number=chain['account_number'],
                    opening_order_id=chain['opening_order_id'],
                    strategy_type=chain['strategy_type'], opening_date=chain['opening_date'],
                    closing_date=chain['closing_date'], chain_status=chain['chain_status'],
                    order_count=chain['order_count'], total_pnl=chain['total_pnl'],
                )
                session.execute(stmt.on_conflict_do_update(
                    index_elements=['chain_id'],
                    set_={
                        'underlying': stmt.excluded.underlying,
                        'account_number': stmt.excluded.account_number,
                        'opening_order_id': stmt.excluded.opening_order_id,
                        'strategy_type': stmt.excluded.strategy_type,
                        'opening_date': stmt.excluded.opening_date,
                        'closing_date': stmt.excluded.closing_date,
                        'chain_status': stmt.excluded.chain_status,
                        'order_count': stmt.excluded.order_count,
                        'total_pnl': stmt.excluded.total_pnl,
                    },
                ))

                # Delete existing chain members
                session.query(OCM).filter(OCM.chain_id == chain['chain_id']).delete()

                # Insert chain members
                for i, order in enumerate(chain['orders']):
                    session.add(OCM(
                        chain_id=chain['chain_id'], order_id=order.order_id,
                        sequence_number=i + 1,
                    ))

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
        from src.database.models import RawTransaction

        try:
            with self.db.get_session() as session:
                rows = (
                    session.query(RawTransaction)
                    .filter(
                        RawTransaction.instrument_type.isnot(None),
                        RawTransaction.symbol.isnot(None),
                    )
                    .order_by(RawTransaction.executed_at)
                    .all()
                )
                transactions = [row.to_dict() for row in rows]
                print(f"Loaded {len(transactions)} raw transactions from database")
                return transactions

        except Exception as e:
            print(f"Error loading raw transactions: {e}")
            return []
    
    def reprocess_orders_and_chains_from_database(self) -> Dict:
        """Reprocess orders and chains using existing raw transactions"""
        from src.database.models import (
            Order as OrderModel, OrderChain as OC, OrderChainMember as OCM, OrderPosition as OP,
        )

        try:
            print("Starting reprocessing from database...")

            # Clear existing orders and chains (order matters for FK constraints)
            print("Clearing existing orders and chains...")
            with self.db.get_session() as session:
                session.query(OCM).delete()
                session.query(OC).delete()
                session.query(OP).delete()
                session.query(OrderModel).delete()
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
            
            # Post-processing: fix chain statuses that may have been missed
            print("Running post-processing to fix chain statuses...")
            fixed_count = self.fix_chain_statuses_after_reprocessing()
            if fixed_count > 0:
                print(f"Fixed {fixed_count} chain statuses")
            else:
                print("No chain status fixes needed")
            
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
    
    def process_new_transactions_incrementally(self, new_transactions: List[Dict]) -> Dict:
        """Process only new transactions without wiping existing data"""
        try:
            if not new_transactions:
                return {
                    'orders_processed': 0,
                    'orders_saved': 0,
                    'chains_updated': 0,
                    'message': 'No new transactions to process'
                }
            
            print(f"Processing {len(new_transactions)} new transactions incrementally...")
            
            # Create orders only from new transactions
            new_orders = self.create_orders_from_transactions(new_transactions)
            print(f"Created {len(new_orders)} new orders")
            
            # Save new orders
            saved_orders = 0
            for order in new_orders:
                try:
                    if self.save_order_to_database(order):
                        saved_orders += 1
                except Exception as e:
                    print(f"Error saving order: {e}")
            
            # Update affected chains only
            affected_underlyings = set()
            for order in new_orders:
                affected_underlyings.add((order.underlying, order.account_number))
            
            chains_updated = 0
            for underlying, account in affected_underlyings:
                # Count affected underlyings for stats
                # (The actual chain reconstruction happens via process_transactions_to_orders_and_chains)
                chains_updated += 1
            
            return {
                'orders_processed': len(new_orders),
                'orders_saved': saved_orders,
                'chains_updated': chains_updated,
                'message': f'Successfully processed {saved_orders} new orders'
            }
            
        except Exception as e:
            print(f"Error during incremental processing: {e}")
            return {
                'orders_processed': 0,
                'orders_saved': 0,
                'chains_updated': 0,
                'error': str(e)
            }
    
    def calculate_chain_position_balance(self, orders: List[Order]) -> Dict[str, float]:
        """
        Calculate net position quantities across all orders in a chain.
        Returns a dictionary mapping position_key -> net_quantity.
        Net quantity of 0 means position is fully closed.
        Non-zero means position is still open.
        
        Position tracking logic:
        - BUY_TO_OPEN: negative quantity (long position)
        - SELL_TO_OPEN: positive quantity (short position)  
        - BUY_TO_CLOSE: negative quantity (closes short position)
        - SELL_TO_CLOSE: positive quantity (closes long position)
        - EXPIRED: closes the position (expiration from system)
        """
        position_balances = {}
        
        for order in orders:
            for position in order.positions:
                # Create position key using symbol, strike, expiration
                pos_key = self.get_position_key(position)
                
                if pos_key not in position_balances:
                    position_balances[pos_key] = 0
                
                # Get opening action and quantity
                opening_action = self.get_position_attr(position, 'opening_action')
                closing_action = self.get_position_attr(position, 'closing_action')
                quantity = abs(position.quantity)
                
                # Handle opening actions
                if opening_action:
                    if 'BUY_TO_OPEN' in opening_action:
                        position_balances[pos_key] -= quantity  # Long position
                    elif 'SELL_TO_OPEN' in opening_action:
                        position_balances[pos_key] += quantity  # Short position
                    elif 'BUY_TO_CLOSE' in opening_action:
                        position_balances[pos_key] -= quantity  # Close short position
                    elif 'SELL_TO_CLOSE' in opening_action:
                        position_balances[pos_key] += quantity  # Close long position
                
                # Handle closing actions (system transactions like expiration)
                if closing_action:
                    if 'EXPIRED' in closing_action:
                        # For expired options, we need to determine if they were long or short
                        # Short options (credit) expire worthless - close the short position
                        # Long options (debit) expire worthless - close the long position
                        # We'll determine this based on the current balance
                        current_balance = position_balances[pos_key]
                        if current_balance > 0:
                            # Positive balance = short position, expiring worthless closes it
                            position_balances[pos_key] -= quantity
                        elif current_balance < 0:
                            # Negative balance = long position, expiring worthless closes it
                            position_balances[pos_key] += quantity
                        # If balance is 0, expiration has no effect
        
        return position_balances
    
    def is_chain_fully_closed(self, orders: List[Order]) -> bool:
        """
        Determine if all positions in a chain are fully closed.
        Returns True only if ALL positions have zero net quantity.
        """
        position_balances = self.calculate_chain_position_balance(orders)
        
        
        # Check if all positions have zero net quantity (fully closed)
        for net_quantity in position_balances.values():
            if abs(net_quantity) > 1e-6:  # Use small epsilon for floating point comparison
                return False  # Found an open position
        
        return True  # All positions are closed
    
    def fix_chain_statuses_after_reprocessing(self) -> int:
        """
        Post-processing step to fix chain statuses after reprocessing.
        This addresses bugs in the chain creation logic that miss expiration closures.
        Returns the number of chains fixed.
        """
        from src.database.models import (
            OrderChain as OC, OrderChainMember as OCM, Order as OrderModel, OrderPosition as OP,
        )

        with self.db.get_session() as session:
            # Find all chains that have expiration orders
            chains_with_exp = (
                session.query(OCM.chain_id, OC.chain_status)
                .join(OC, OCM.chain_id == OC.chain_id)
                .join(OrderModel, OCM.order_id == OrderModel.order_id)
                .filter(OrderModel.order_id.like('SYSTEM_EXPIRATION_%'))
                .distinct()
                .order_by(OCM.chain_id)
                .all()
            )

            if not chains_with_exp:
                return 0

            # Batch-load all positions for affected chains
            affected_chain_ids = [cid for cid, _ in chains_with_exp]
            pos_rows = (
                session.query(
                    OCM.chain_id, OP.symbol, OP.quantity, OP.opening_action,
                    OP.closing_action, OP.strike, OP.expiration, OrderModel.order_date,
                )
                .join(OCM, OP.order_id == OCM.order_id)
                .join(OrderModel, OP.order_id == OrderModel.order_id)
                .filter(OCM.chain_id.in_(affected_chain_ids))
                .order_by(OrderModel.order_date, OP.order_id)
                .all()
            )

            # Group by chain_id
            pos_by_chain: Dict[str, list] = {}
            for row in pos_rows:
                pos_by_chain.setdefault(row[0], []).append(row[1:])

            fixed_count = 0
            for chain_id, current_status in chains_with_exp:
                positions = pos_by_chain.get(chain_id, [])
                position_balances = {}
                latest_order_date = None

                for symbol, qty, open_action, close_action, strike, exp, order_date in positions:
                    if order_date:
                        if isinstance(order_date, str):
                            try:
                                order_date = datetime.strptime(order_date, '%Y-%m-%d').date()
                            except Exception:
                                pass
                        if latest_order_date is None or order_date > latest_order_date:
                            latest_order_date = order_date

                    pos_key = f"{symbol}_{strike}_{exp}" if strike is not None and exp is not None else symbol
                    if pos_key not in position_balances:
                        position_balances[pos_key] = 0
                    quantity = abs(qty)

                    if open_action:
                        if 'SELL_TO_OPEN' in open_action:
                            position_balances[pos_key] += quantity
                        elif 'BUY_TO_OPEN' in open_action:
                            position_balances[pos_key] -= quantity
                        elif 'BUY_TO_CLOSE' in open_action:
                            position_balances[pos_key] -= quantity
                        elif 'SELL_TO_CLOSE' in open_action:
                            position_balances[pos_key] += quantity

                    if close_action and 'EXPIRED' in close_action:
                        current_balance = position_balances[pos_key]
                        if current_balance > 0:
                            position_balances[pos_key] -= quantity
                        elif current_balance < 0:
                            position_balances[pos_key] += quantity

                has_open_positions = any(abs(b) > 1e-6 for b in position_balances.values())
                correct_status = 'OPEN' if has_open_positions else 'CLOSED'

                if correct_status != current_status:
                    chain_row = session.get(OC, chain_id)
                    if chain_row:
                        chain_row.chain_status = correct_status
                        chain_row.closing_date = latest_order_date if correct_status == 'CLOSED' else None
                    fixed_count += 1

            return fixed_count
    
