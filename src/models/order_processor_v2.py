"""
Order Processing Engine V2
Implements the new order chain processing rules
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Set, Tuple
from enum import Enum
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class OrderType(Enum):
    OPENING = "OPENING"
    ROLLING = "ROLLING"
    CLOSING = "CLOSING"


@dataclass
class Transaction:
    """Represents a single transaction/fill"""
    id: str
    account_number: str
    order_id: str
    symbol: str
    underlying_symbol: str
    action: str  # BTO, STO, BTC, STC
    quantity: int
    price: float
    executed_at: datetime
    transaction_type: str
    transaction_sub_type: str
    description: str
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[date] = None
    
    @property
    def is_opening(self) -> bool:
        return 'TO_OPEN' in (self.action or '')
    
    @property
    def is_closing(self) -> bool:
        return ('TO_CLOSE' in (self.action or '') or 
                self.is_expiration or 
                self.is_assignment or 
                self.is_exercise)
    
    @property
    def is_expiration(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'EXPIR' in sub_type
    
    @property
    def is_assignment(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'ASSIGNMENT' in sub_type
    
    @property
    def is_exercise(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'EXERCISE' in sub_type
    
    @property
    def is_buy(self) -> bool:
        return 'BUY' in (self.action or '')
    
    @property
    def is_sell(self) -> bool:
        return 'SELL' in (self.action or '')


@dataclass
class Order:
    """Represents an order (group of transactions)"""
    order_id: str
    account_number: str
    underlying: str
    executed_at: datetime
    order_type: OrderType
    transactions: List[Transaction] = field(default_factory=list)
    
    @property
    def opening_transactions(self) -> List[Transaction]:
        return [t for t in self.transactions if t.is_opening]
    
    @property
    def closing_transactions(self) -> List[Transaction]:
        return [t for t in self.transactions if t.is_closing]
    
    @property
    def symbols(self) -> Set[str]:
        return {t.symbol for t in self.transactions}


@dataclass
class Chain:
    """Represents a derived order chain"""
    chain_id: str
    underlying: str
    account_number: str
    orders: List[Order] = field(default_factory=list)
    status: str = "OPEN"  # OPEN or CLOSED
    
    @property
    def opening_date(self) -> Optional[date]:
        if self.orders:
            return self.orders[0].executed_at.date()
        return None
    
    @property
    def closing_date(self) -> Optional[date]:
        if self.status == "CLOSED" and self.orders:
            return self.orders[-1].executed_at.date()
        return None


class OrderProcessorV2:
    """New order processing engine based on simplified rules"""
    
    def __init__(self, db_manager, position_manager):
        self.db = db_manager
        self.position_manager = position_manager
    
    def process_transactions(self, raw_transactions: List[Dict]) -> Dict[str, List[Chain]]:
        """
        Main processing method - converts raw transactions to derived chains
        Returns chains grouped by account number
        """
        logger.info(f"Processing {len(raw_transactions)} transactions")
        
        # Step 1: Preprocess transactions
        transactions = self._preprocess_transactions(raw_transactions)
        
        # Step 2: Group by account, underlying, order_id
        grouped_orders = self._group_transactions(transactions)
        
        # Step 3: Create Order objects
        orders = self._create_orders(grouped_orders)
        
        # Step 4: Sort orders chronologically
        orders.sort(key=lambda o: o.executed_at)
        
        # Step 5: Process orders to update positions
        self._update_positions(orders)
        
        # Step 6: Derive chains from orders and positions
        chains = self._derive_chains(orders)
        
        # Group chains by account
        chains_by_account = defaultdict(list)
        for chain in chains:
            chains_by_account[chain.account_number].append(chain)
        
        return dict(chains_by_account)
    
    def _preprocess_transactions(self, raw_transactions: List[Dict]) -> List[Transaction]:
        """Convert raw transactions to Transaction objects, generating order IDs as needed"""
        transactions = []
        
        for raw_tx in raw_transactions:
            # Skip non-trading transactions (no symbol)
            # But keep assignment/exercise transactions even if action is None
            if not raw_tx.get('symbol'):
                continue
            
            # Skip transactions with no action, except assignment/exercise
            sub_type = raw_tx.get('transaction_sub_type', '').upper()
            if (not raw_tx.get('action') and 
                'ASSIGNMENT' not in sub_type and 
                'EXERCISE' not in sub_type):
                continue
            
            # Skip stock transactions that result from assignment/exercise (they have no order_id)
            # These are automatic stock transactions and shouldn't create chains
            # But keep expiration/assignment/exercise option transactions
            instrument_type = str(raw_tx.get('instrument_type', ''))
            if ('EQUITY' in instrument_type and 
                'EQUITY_OPTION' not in instrument_type and  # Only skip pure stock transactions
                not raw_tx.get('order_id') and 
                raw_tx.get('action')):
                continue
            
            # Only process options transactions for chain creation
            # Skip pure stock transactions (but keep assignment/exercise which are option-related)
            if (instrument_type and 'EQUITY_OPTION' not in instrument_type and 
                'ASSIGNMENT' not in sub_type and 
                'EXERCISE' not in sub_type and
                'EXPIR' not in sub_type):
                # Debug: Log what we're filtering out
                logger.debug(f"Filtering out transaction: {raw_tx.get('symbol')} - {instrument_type} - {sub_type}")
                continue
            # Generate order ID if missing
            order_id = raw_tx.get('order_id')
            if not order_id:
                # Generate ID for system events like expiration
                executed_at = raw_tx.get('executed_at', '')
                symbol = raw_tx.get('symbol', '')
                action = raw_tx.get('action', '')
                order_id = f"SYSTEM_{raw_tx.get('transaction_sub_type', 'UNKNOWN')}_{executed_at}_{symbol}_{action}"
                order_id = order_id.replace(' ', '_').replace(':', '')
            
            # Parse option details from symbol if needed
            symbol = raw_tx.get('symbol', '')
            option_type = None
            strike = None
            expiration = None
            
            instrument_type_str = str(raw_tx.get('instrument_type') or '')
            if ('OPTION' in instrument_type_str.upper() or 'option' in instrument_type_str) and ' ' in symbol:
                parts = symbol.split()
                if len(parts) >= 2:
                    option_part = parts[1]
                    if len(option_part) >= 8:
                        # Extract date
                        date_str = option_part[:6]
                        try:
                            expiration = datetime.strptime('20' + date_str, '%Y%m%d').date()
                        except:
                            pass
                        
                        # Extract type
                        if len(option_part) > 6:
                            option_type = 'Call' if option_part[6] == 'C' else 'Put'
                        
                        # Extract strike
                        if len(option_part) > 7:
                            try:
                                strike = float(option_part[7:]) / 1000
                            except:
                                pass
            
            # Create Transaction object
            tx = Transaction(
                id=str(raw_tx.get('id', '')),
                account_number=raw_tx.get('account_number', ''),
                order_id=order_id,
                symbol=symbol,
                underlying_symbol=raw_tx.get('underlying_symbol', symbol.split()[0] if symbol and ' ' in symbol else symbol),
                action=raw_tx.get('action') or '',
                quantity=int(raw_tx.get('quantity', 0)),
                price=float(raw_tx.get('price') or 0),
                executed_at=datetime.fromisoformat(raw_tx.get('executed_at', '').replace('Z', '+00:00')),
                transaction_type=raw_tx.get('transaction_type', ''),
                transaction_sub_type=raw_tx.get('transaction_sub_type', ''),
                description=raw_tx.get('description', ''),
                option_type=option_type,
                strike=strike,
                expiration=expiration
            )
            
            transactions.append(tx)
        
        return transactions
    
    def _group_transactions(self, transactions: List[Transaction]) -> Dict[Tuple, List[Transaction]]:
        """Group transactions by (account, underlying, order_id)"""
        grouped = defaultdict(list)
        
        for tx in transactions:
            # Extract underlying from symbol
            underlying = tx.underlying_symbol
            if ' ' in underlying:
                underlying = underlying.split()[0]
            
            key = (tx.account_number, underlying, tx.order_id)
            grouped[key].append(tx)
        
        return grouped
    
    def _create_orders(self, grouped_transactions: Dict[Tuple, List[Transaction]]) -> List[Order]:
        """Create Order objects from grouped transactions"""
        orders = []
        
        for (account, underlying, order_id), transactions in grouped_transactions.items():
            # Normalize transactions (aggregate same action/symbol/price)
            normalized = self._normalize_transactions(transactions)
            
            # Classify order type
            order_type = self._classify_order(normalized)
            
            # Get earliest execution time
            executed_at = min(tx.executed_at for tx in normalized)
            
            order = Order(
                order_id=order_id,
                account_number=account,
                underlying=underlying,
                executed_at=executed_at,
                order_type=order_type,
                transactions=normalized
            )
            
            orders.append(order)
        
        return orders
    
    def _normalize_transactions(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Normalize transactions by aggregating those with same action/symbol/price
        Note: We do NOT aggregate different prices per the rules
        """
        # Group by (action, symbol, option_type, strike, expiration, price)
        groups = defaultdict(list)
        
        for tx in transactions:
            key = (tx.action, tx.symbol, tx.option_type, tx.strike, tx.expiration, tx.price)
            groups[key].append(tx)
        
        normalized = []
        for key, group in groups.items():
            if len(group) == 1:
                normalized.append(group[0])
            else:
                # Aggregate into single transaction
                total_quantity = sum(tx.quantity for tx in group)
                first_tx = group[0]
                
                aggregated = Transaction(
                    id=','.join(tx.id for tx in group),
                    account_number=first_tx.account_number,
                    order_id=first_tx.order_id,
                    symbol=first_tx.symbol,
                    underlying_symbol=first_tx.underlying_symbol,
                    action=first_tx.action,
                    quantity=total_quantity,
                    price=first_tx.price,
                    executed_at=min(tx.executed_at for tx in group),
                    transaction_type=first_tx.transaction_type,
                    transaction_sub_type=first_tx.transaction_sub_type,
                    description=f"Aggregated {len(group)} fills",
                    option_type=first_tx.option_type,
                    strike=first_tx.strike,
                    expiration=first_tx.expiration
                )
                normalized.append(aggregated)
        
        return normalized
    
    def _classify_order(self, transactions: List[Transaction]) -> OrderType:
        """Classify order as OPENING, ROLLING, or CLOSING"""
        has_opening = any(tx.is_opening for tx in transactions)
        has_closing = any(tx.is_closing for tx in transactions)
        
        if has_opening and not has_closing:
            return OrderType.OPENING
        elif has_closing and not has_opening:
            return OrderType.CLOSING
        elif has_opening and has_closing:
            return OrderType.ROLLING
        else:
            # Should not happen, default to CLOSING for safety
            logger.warning(f"Could not classify order with transactions: {[tx.action for tx in transactions]}")
            return OrderType.CLOSING
    
    def _update_positions(self, orders: List[Order]):
        """Update position inventory based on orders"""
        for order in orders:
            for tx in order.transactions:
                # Convert Transaction to dict format expected by position manager
                tx_dict = {
                    'account_number': tx.account_number,
                    'symbol': tx.symbol,
                    'underlying_symbol': tx.underlying_symbol,
                    'action': tx.action,
                    'quantity': tx.quantity,
                    'price': tx.price,
                    'instrument_type': 'EQUITY_OPTION' if tx.option_type else 'EQUITY',
                    'transaction_sub_type': tx.transaction_sub_type
                }
                
                self.position_manager.update_position_from_transaction(tx_dict)
    
    def _derive_chains(self, orders: List[Order]) -> List[Chain]:
        """Derive chains from orders based on the rules"""
        chains = {}  # chain_id -> Chain
        order_to_chain = {}  # Track which chain each order belongs to
        
        for order in orders:
            if order.order_type == OrderType.OPENING:
                # OPENING orders always start a new chain
                chain_id = f"{order.underlying}_OPENING_{order.executed_at.strftime('%Y%m%d')}_{order.order_id[:8]}"
                chain = Chain(
                    chain_id=chain_id,
                    underlying=order.underlying,
                    account_number=order.account_number,
                    orders=[order]
                )
                chains[chain_id] = chain
                order_to_chain[order.order_id] = chain_id
                
            elif order.order_type in [OrderType.ROLLING, OrderType.CLOSING]:
                # Check if this is a system-generated assignment/exercise/expiration order
                is_system_closing = any(tx.is_assignment or tx.is_exercise or tx.is_expiration 
                                      for tx in order.transactions)
                
                if is_system_closing:
                    # Assignment/Exercise/Expiration: Add to existing chains but don't create separate chains
                    logger.info(f"Processing system closing event: {order.order_id}")
                    
                    # Find chains that contain positions affected by this system closing
                    affected_chain_ids = set()
                    
                    for tx in order.transactions:
                        # Find which chain contains orders that opened this position
                        for chain_id, chain in chains.items():
                            if (chain.underlying == order.underlying and 
                                chain.account_number == order.account_number):
                                
                                # Check if this chain has any orders that opened this position
                                for chain_order in chain.orders:
                                    if any(t.symbol == tx.symbol for t in chain_order.opening_transactions):
                                        affected_chain_ids.add(chain_id)
                                        break
                    
                    # Add this order to all affected chains
                    for chain_id in affected_chain_ids:
                        chains[chain_id].orders.append(order)
                        order_to_chain[order.order_id] = chain_id
                        logger.info(f"Added system closing order {order.order_id} to chain {chain_id}")
                    
                    continue
                
                # Find chains to update based on closing transactions
                affected_chain_ids = set()
                
                for tx in order.closing_transactions:
                    # Find which positions this transaction closes
                    position = self.position_manager.get_position(tx.account_number, tx.symbol)
                    
                    if position:
                        # Find which chain contains orders that opened this position
                        # For now, use FIFO - find the earliest chain with this underlying
                        for chain_id, chain in chains.items():
                            if (chain.underlying == order.underlying and 
                                chain.account_number == order.account_number and
                                chain.status == "OPEN"):
                                
                                # Check if this chain has any orders that could have opened this position
                                for chain_order in chain.orders:
                                    if any(t.symbol == tx.symbol for t in chain_order.opening_transactions):
                                        affected_chain_ids.add(chain_id)
                                        break
                
                if not affected_chain_ids:
                    # No matching chain found - this shouldn't happen in normal flow
                    logger.warning(f"No chain found for {order.order_type} order {order.order_id}")
                    # Create a new chain for safety
                    chain_id = f"{order.underlying}_ORPHAN_{order.executed_at.strftime('%Y%m%d')}_{order.order_id[:8]}"
                    chain = Chain(
                        chain_id=chain_id,
                        underlying=order.underlying,
                        account_number=order.account_number,
                        orders=[order]
                    )
                    chains[chain_id] = chain
                    
                elif len(affected_chain_ids) == 1:
                    # Single chain affected - just append the order
                    chain_id = affected_chain_ids.pop()
                    chains[chain_id].orders.append(order)
                    order_to_chain[order.order_id] = chain_id
                    
                else:
                    # Multiple chains affected - merge them
                    chains_to_merge = [chains[cid] for cid in affected_chain_ids]
                    merged_chain = self._merge_chains(chains_to_merge, order)
                    
                    # Remove old chains
                    for chain_id in affected_chain_ids:
                        del chains[chain_id]
                    
                    # Add merged chain
                    chains[merged_chain.chain_id] = merged_chain
                    order_to_chain[order.order_id] = merged_chain.chain_id
        
        # Update chain status based on positions
        for chain in chains.values():
            chain.status = self._determine_chain_status(chain)
        
        return list(chains.values())
    
    def _merge_chains(self, chains_to_merge: List[Chain], new_order: Order) -> Chain:
        """Merge multiple chains into one"""
        # Use the earliest chain's ID as base
        chains_to_merge.sort(key=lambda c: c.opening_date or date.min)
        base_chain = chains_to_merge[0]
        
        # Collect all orders
        all_orders = []
        for chain in chains_to_merge:
            all_orders.extend(chain.orders)
        all_orders.append(new_order)
        
        # Sort chronologically
        all_orders.sort(key=lambda o: o.executed_at)
        
        # Create merged chain
        merged_chain = Chain(
            chain_id=f"{base_chain.chain_id}_MERGED",
            underlying=base_chain.underlying,
            account_number=base_chain.account_number,
            orders=all_orders
        )
        
        return merged_chain
    
    def _determine_chain_status(self, chain: Chain) -> str:
        """Determine if chain is OPEN or CLOSED based on positions"""
        # Get all symbols traded in this chain
        all_symbols = set()
        for order in chain.orders:
            all_symbols.update(order.symbols)
        
        # Check if any positions are still open
        for symbol in all_symbols:
            position = self.position_manager.get_position(chain.account_number, symbol)
            if position and not position.is_closed:
                return "OPEN"
        
        return "CLOSED"