"""
Order Processing Engine
Implements order chain processing rules
Enhanced with lot-based position tracking
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Set, Tuple, TYPE_CHECKING
from enum import Enum
import logging
from collections import defaultdict

if TYPE_CHECKING:
    from src.models.lot_manager import LotManager

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
    commission: float = 0.0
    regulatory_fees: float = 0.0
    clearing_fees: float = 0.0
    value: float = 0.0
    net_value: float = 0.0
    
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

    @property
    def is_cash_settlement(self) -> bool:
        desc = (self.description or '').lower()
        return 'cash settlement' in desc


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


class OrderProcessor:
    """Order processing engine based on simplified rules

    Enhanced with lot-based position tracking for:
    - Overlapping positions (multiple trades on same symbol)
    - Vertical spread leg linking
    - Early assignment with stock lineage tracking
    - Partial closures with FIFO matching
    """

    def __init__(self, db_manager, position_manager, lot_manager: Optional['LotManager'] = None):
        self.db = db_manager
        self.position_manager = position_manager
        self.lot_manager = lot_manager
        self._use_lots = lot_manager is not None
        self._assignment_stock_transactions = []  # V3: Track stock txs from assignments
    
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

        # Step 5.5: V3 - Process assignments to create derived stock lots
        self._process_assignments(orders)

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
        self._assignment_stock_transactions = []  # V3: Reset for each processing run

        # Pre-scan: group Symbol Change transactions so close/open legs share order IDs
        symbol_change_overrides = {}
        sym_change_txs = [tx for tx in raw_transactions if tx.get('transaction_sub_type') == 'Symbol Change']
        if sym_change_txs:
            sc_groups = defaultdict(list)
            for tx in sym_change_txs:
                acct = tx.get('account_number', '')
                old_under = tx.get('underlying_symbol', '')
                date_str = tx.get('executed_at', '')[:10]
                sc_groups[(acct, old_under, date_str)].append(tx)

            for (acct, old_under, date_str), txs in sc_groups.items():
                close_txs = [t for t in txs if 'TO_CLOSE' in (t.get('action') or '')]
                open_txs = [t for t in txs if 'TO_OPEN' in (t.get('action') or '')]

                # Derive new underlying from open legs' symbol
                new_under = old_under
                if open_txs:
                    sym = open_txs[0].get('symbol', '')
                    if sym:
                        new_under = sym.split()[0]

                close_oid = f"SYMCHG_CLOSE_{acct}_{old_under}_{date_str}"
                open_oid = f"SYMCHG_OPEN_{acct}_{new_under}_{date_str}"

                for t in close_txs:
                    symbol_change_overrides[str(t.get('id', ''))] = {
                        'order_id': close_oid,
                        'underlying_symbol': old_under,
                    }
                for t in open_txs:
                    symbol_change_overrides[str(t.get('id', ''))] = {
                        'order_id': open_oid,
                        'underlying_symbol': new_under,
                    }

                if open_txs or close_txs:
                    logger.info(f"Symbol change: {old_under} -> {new_under}, "
                                f"{len(close_txs)} close legs, {len(open_txs)} open legs")

        for raw_tx in raw_transactions:
            # Skip non-trading transactions (no symbol)
            # But keep assignment/exercise transactions even if action is None
            if not raw_tx.get('symbol'):
                continue
            
            # Skip transactions with no action, except assignment/exercise/expiration
            sub_type = raw_tx.get('transaction_sub_type', '').upper()
            if (not raw_tx.get('action') and
                'ASSIGNMENT' not in sub_type and
                'EXERCISE' not in sub_type and
                'EXPIR' not in sub_type):
                continue
            
            # Skip stock transactions that result from assignment/exercise (they have no order_id)
            # These are automatic stock transactions and shouldn't create chains
            # But keep expiration/assignment/exercise option transactions
            # V3: Capture these for derived lot creation
            # ACAT transfers also have no order_id but are real stock positions —
            # let them flow through normal processing for proper chain linkage.
            instrument_type = str(raw_tx.get('instrument_type', ''))
            sub_type_upper = raw_tx.get('transaction_sub_type', '').upper()
            if ('EQUITY' in instrument_type and
                'EQUITY_OPTION' not in instrument_type and  # Only skip pure stock transactions
                not raw_tx.get('order_id') and
                raw_tx.get('action') and
                sub_type_upper != 'ACAT'):
                # V3: Save for assignment/exercise processing
                self._assignment_stock_transactions.append(raw_tx)
                continue

            # Generate order ID — use symbol change override if available
            tx_id_str = str(raw_tx.get('id', ''))
            sc_override = symbol_change_overrides.get(tx_id_str)
            if sc_override:
                order_id = sc_override['order_id']
            else:
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
                underlying_symbol=sc_override['underlying_symbol'] if sc_override else raw_tx.get('underlying_symbol', symbol.split()[0] if symbol and ' ' in symbol else symbol),
                action=raw_tx.get('action') or '',
                quantity=int(raw_tx.get('quantity', 0)),
                price=float(raw_tx.get('price') or 0),
                executed_at=datetime.fromisoformat(raw_tx.get('executed_at', '').replace('Z', '+00:00')),
                transaction_type=raw_tx.get('transaction_type', ''),
                transaction_sub_type=raw_tx.get('transaction_sub_type', ''),
                description=raw_tx.get('description', ''),
                option_type=option_type,
                strike=strike,
                expiration=expiration,
                commission=float(raw_tx.get('commission', 0)),
                regulatory_fees=float(raw_tx.get('regulatory_fees', 0)),
                clearing_fees=float(raw_tx.get('clearing_fees', 0)),
                value=float(raw_tx.get('value', 0)),
                net_value=float(raw_tx.get('net_value', 0))
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
                    expiration=first_tx.expiration,
                    commission=sum(tx.commission for tx in group),
                    regulatory_fees=sum(tx.regulatory_fees for tx in group),
                    clearing_fees=sum(tx.clearing_fees for tx in group),
                    value=sum(tx.value for tx in group),
                    net_value=sum(tx.net_value for tx in group)
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
        """Update position inventory based on orders

        If lot_manager is available, also creates/closes lots for V3 tracking.
        """
        # Track temporary chain assignments for lot creation
        # Will be finalized in _derive_chains
        order_to_temp_chain = {}

        # V3: Track which chains are affected by closing orders BEFORE closing the lots
        # This is critical for linking closing orders to their opening chains
        closing_order_to_chains = {}

        for order in orders:
            # Generate temporary chain ID for opening orders
            temp_chain_id = None
            if order.order_type == OrderType.OPENING:
                temp_chain_id = f"{order.underlying}_OPENING_{order.executed_at.strftime('%Y%m%d')}_{order.order_id[:8]}"
                order_to_temp_chain[order.order_id] = temp_chain_id

            # V3: For closing/rolling orders, find affected chains BEFORE closing lots
            if order.order_type in [OrderType.CLOSING, OrderType.ROLLING] and self._use_lots and self.lot_manager:
                affected_chains = set()
                for tx in order.closing_transactions:
                    # Find open lots for this symbol to get their chain_ids
                    open_lots = self.lot_manager.get_open_lots(
                        account_number=tx.account_number,
                        symbol=tx.symbol
                    )
                    for lot in open_lots:
                        if lot.chain_id:
                            affected_chains.add(lot.chain_id)
                if affected_chains:
                    closing_order_to_chains[order.order_id] = affected_chains
                    logger.debug(f"Order {order.order_id} will close lots in chains: {affected_chains}")

                    # For ROLLING orders, new positions should inherit the chain from closed positions
                    if order.order_type == OrderType.ROLLING:
                        # Use the first affected chain as the chain for new lots
                        temp_chain_id = list(affected_chains)[0]
                        order_to_temp_chain[order.order_id] = temp_chain_id
                        logger.debug(f"Rolling order {order.order_id} will create new lots in chain: {temp_chain_id}")

            for idx, tx in enumerate(order.transactions):
                # Convert Transaction to dict format expected by position manager
                tx_dict = {
                    'id': tx.id,
                    'account_number': tx.account_number,
                    'symbol': tx.symbol,
                    'underlying_symbol': tx.underlying_symbol,
                    'action': tx.action,
                    'quantity': tx.quantity,
                    'price': tx.price,
                    'executed_at': tx.executed_at.isoformat() if tx.executed_at else '',
                    'instrument_type': 'EQUITY_OPTION' if tx.option_type else 'EQUITY',
                    'transaction_sub_type': tx.transaction_sub_type
                }

                # Update position inventory (legacy system)
                self.position_manager.update_position_from_transaction(tx_dict)

                # V3 Lot-based tracking
                if self._use_lots and self.lot_manager:
                    if tx.is_opening:
                        # Create lot for opening transaction
                        self.lot_manager.create_lot(
                            transaction=tx_dict,
                            chain_id=temp_chain_id or '',
                            leg_index=idx,
                            opening_order_id=order.order_id
                        )
                    elif tx.is_closing:
                        # Determine closing direction for equity FIFO
                        close_long = None
                        if 'SELL_TO_CLOSE' in (tx.action or ''):
                            close_long = True
                        elif 'BUY_TO_CLOSE' in (tx.action or ''):
                            close_long = False

                        # Determine closing type
                        if tx.is_assignment:
                            closing_type = 'ASSIGNMENT'
                        elif tx.is_exercise:
                            closing_type = 'EXERCISE'
                        elif tx.is_expiration:
                            closing_type = 'EXPIRATION'
                        else:
                            closing_type = 'MANUAL'

                        # Close lots using FIFO
                        self.lot_manager.close_lot_fifo(
                            account_number=tx.account_number,
                            symbol=tx.symbol,
                            quantity_to_close=abs(tx.quantity),
                            closing_price=tx.price,
                            closing_order_id=order.order_id,
                            closing_transaction_id=tx.id,
                            closing_date=tx.executed_at,
                            closing_type=closing_type,
                            close_long=close_long
                        )

        # Store for use in _derive_chains
        self._order_to_temp_chain = order_to_temp_chain
        self._closing_order_to_chains = closing_order_to_chains
    
    def _detect_assignment_pairs(self, transactions: List[Transaction]) -> List[Tuple[Transaction, Transaction]]:
        """
        Match assignment option removal with corresponding stock creation.

        When an option is assigned, two transactions typically occur:
        1. Option removal (ASSIGNMENT sub-type)
        2. Stock receive/deliver (no order_id, near-simultaneous)

        Returns:
            List of (option_transaction, stock_transaction) pairs
        """
        pairs = []

        # Group transactions by timestamp (within ~1 second) and underlying
        # where we have both an option assignment and a stock transaction
        from collections import defaultdict

        # Find assignment transactions
        assignments = [tx for tx in transactions
                      if tx.is_assignment and tx.option_type is not None]

        # Find stock transactions that might be from assignment (no order_id)
        stock_txs = [tx for tx in transactions
                    if not tx.order_id.startswith('SYSTEM_') and
                    tx.option_type is None and
                    'EQUITY' in (tx.transaction_type or '').upper()]

        for assignment in assignments:
            underlying = assignment.underlying_symbol

            # Look for matching stock transaction within 1 minute
            for stock_tx in stock_txs:
                if stock_tx.underlying_symbol != underlying:
                    continue

                time_diff = abs((assignment.executed_at - stock_tx.executed_at).total_seconds())
                if time_diff > 60:  # 1 minute window
                    continue

                # Check quantity alignment (100 shares per option contract)
                expected_shares = abs(assignment.quantity) * 100
                if abs(stock_tx.quantity) != expected_shares:
                    continue

                # Match found
                pairs.append((assignment, stock_tx))
                logger.info(f"Found assignment pair: option {assignment.symbol} -> stock {stock_tx.symbol}")
                break

        return pairs

    def _process_assignments(self, orders: List[Order]):
        """
        V3: Process assignment pairs to create derived stock lots.

        After option lots are closed with type='ASSIGNMENT', this method:
        1. Matches assignment option transactions with corresponding stock transactions
        2. Finds the closed option lot
        3. Creates a derived stock lot linked to the same chain
        """
        if not self._use_lots or not self.lot_manager:
            return

        if not self._assignment_stock_transactions:
            return

        # Find all assignment transactions from processed orders
        assignment_txs = []
        for order in orders:
            for tx in order.transactions:
                if tx.is_assignment and tx.option_type is not None:
                    assignment_txs.append(tx)

        if not assignment_txs:
            return

        logger.info(f"Processing {len(assignment_txs)} assignments with {len(self._assignment_stock_transactions)} stock transactions")

        for assignment_tx in assignment_txs:
            underlying = assignment_tx.underlying_symbol

            # Find matching stock transaction
            matching_stock = None
            for stock_raw in self._assignment_stock_transactions:
                stock_underlying = stock_raw.get('underlying_symbol', stock_raw.get('symbol', ''))
                if stock_underlying != underlying:
                    continue

                # Parse executed_at for comparison
                stock_executed_str = stock_raw.get('executed_at', '')
                try:
                    stock_executed = datetime.fromisoformat(stock_executed_str.replace('Z', '+00:00'))
                except:
                    continue

                time_diff = abs((assignment_tx.executed_at - stock_executed).total_seconds())
                if time_diff > 60:  # 1 minute window
                    continue

                # Check quantity alignment (100 shares per option contract)
                expected_shares = abs(assignment_tx.quantity) * 100
                if abs(int(stock_raw.get('quantity', 0))) != expected_shares:
                    continue

                matching_stock = stock_raw
                break

            if not matching_stock:
                logger.warning(f"No matching stock transaction found for assignment: {assignment_tx.symbol}")
                continue

            # Find the option lot that was closed by this assignment
            # Query lot_closings for this symbol with type='ASSIGNMENT'
            from src.database.models import PositionLot as PL, LotClosing as LC
            with self.db.get_session() as session:
                result = (
                    session.query(PL.id, PL.chain_id, PL.option_type, PL.strike)
                    .join(LC, PL.id == LC.lot_id)
                    .filter(
                        PL.account_number == assignment_tx.account_number,
                        PL.symbol == assignment_tx.symbol,
                        LC.closing_type == 'ASSIGNMENT',
                        LC.resulting_lot_id.is_(None),
                    )
                    .order_by(LC.closing_date.desc())
                    .first()
                )

            if not result:
                logger.warning(f"No closed option lot found for assignment: {assignment_tx.symbol}")
                continue

            option_lot_id, chain_id, option_type, strike = result

            if not chain_id:
                logger.warning(f"Option lot {option_lot_id} has no chain_id, skipping derived lot creation")
                continue

            # Create derived stock lot
            stock_tx_dict = {
                'id': str(matching_stock.get('id', '')),
                'account_number': matching_stock.get('account_number', ''),
                'symbol': matching_stock.get('symbol', ''),
                'underlying_symbol': matching_stock.get('underlying_symbol', matching_stock.get('symbol', '')),
                'quantity': int(matching_stock.get('quantity', 0)),
                'price': float(matching_stock.get('price', 0)),
                'executed_at': matching_stock.get('executed_at', ''),
            }

            derivation_type = 'ASSIGNMENT'
            derived_lot_id = self.lot_manager.create_derived_lot(
                source_lot_id=option_lot_id,
                stock_transaction=stock_tx_dict,
                derivation_type=derivation_type,
                chain_id=chain_id
            )

            logger.info(f"Created derived stock lot {derived_lot_id} from option lot {option_lot_id} via {derivation_type}")

            # Remove the matched stock transaction so it's not matched again
            self._assignment_stock_transactions.remove(matching_stock)

    def _derive_chains(self, orders: List[Order]) -> List[Chain]:
        """Derive chains from orders based on the rules

        When lot_manager is available, uses lot-based chain matching for
        more accurate tracking of overlapping positions and assignments.
        """
        chains = {}  # chain_id -> Chain
        order_to_chain = {}  # Track which chain each order belongs to

        for order in orders:
            if order.order_type == OrderType.OPENING:
                # Check if this is a stock-only order that should merge into an existing chain
                merged_into = None
                is_stock_only = all(tx.strike is None for tx in order.transactions)

                if is_stock_only:
                    # Look for an existing open chain on this underlying+account that has stock lots
                    merged_into = self._find_stock_merge_target(
                        chains, order.underlying, order.account_number
                    )

                if merged_into:
                    # Merge into existing chain
                    chains[merged_into].orders.append(order)
                    order_to_chain[order.order_id] = merged_into
                    logger.info(f"Merged stock-only opening order {order.order_id} into chain {merged_into}")
                else:
                    # OPENING orders start a new chain
                    chain_id = f"{order.underlying}_OPENING_{order.executed_at.strftime('%Y%m%d')}_{order.order_id[:8]}"
                    chain = Chain(
                        chain_id=chain_id,
                        underlying=order.underlying,
                        account_number=order.account_number,
                        orders=[order]
                    )
                    chains[chain_id] = chain
                    order_to_chain[order.order_id] = chain_id

                    # V3: Update lot chain_ids if needed (they may have been created with temp chain_id)
                    if self._use_lots and self.lot_manager:
                        # Lots were already created in _update_positions with the same chain_id
                        pass

            elif order.order_type in [OrderType.ROLLING, OrderType.CLOSING]:
                # Check if this is a system-generated assignment/exercise/expiration order
                is_system_closing = any(tx.is_assignment or tx.is_exercise or tx.is_expiration
                                      for tx in order.transactions)

                if is_system_closing:
                    # Assignment/Exercise/Expiration: Add to existing chains but don't create separate chains
                    logger.info(f"Processing system closing event: {order.order_id}")

                    # Find chains that contain positions affected by this system closing
                    affected_chain_ids = set()

                    # V3: First check the pre-computed chain mapping
                    if hasattr(self, '_closing_order_to_chains') and order.order_id in self._closing_order_to_chains:
                        precomputed_chains = self._closing_order_to_chains[order.order_id]
                        for chain_id in precomputed_chains:
                            if chain_id in chains:
                                affected_chain_ids.add(chain_id)

                    # Fallback: Try other matching methods
                    if not affected_chain_ids:
                        for tx in order.transactions:
                            # V3: Use lot-based matching if available
                            if self._use_lots and self.lot_manager:
                                # Find lots for this symbol
                                lots = self.lot_manager.get_open_lots(
                                    account_number=tx.account_number,
                                    symbol=tx.symbol
                                )
                                for lot in lots:
                                    if lot.chain_id:
                                        affected_chain_ids.add(lot.chain_id)

                            # Legacy: Find which chain contains orders that opened this position
                            if not affected_chain_ids:
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
                        if chain_id in chains:
                            chains[chain_id].orders.append(order)
                            order_to_chain[order.order_id] = chain_id
                            logger.info(f"Added system closing order {order.order_id} to chain {chain_id}")

                    continue

                # Find chains to update based on closing transactions
                affected_chain_ids = set()

                # V3: First check the pre-computed chain mapping (captured BEFORE lots were closed)
                if hasattr(self, '_closing_order_to_chains') and order.order_id in self._closing_order_to_chains:
                    precomputed_chains = self._closing_order_to_chains[order.order_id]
                    # Only use chains that still exist
                    for chain_id in precomputed_chains:
                        if chain_id in chains:
                            affected_chain_ids.add(chain_id)
                    if affected_chain_ids:
                        logger.debug(f"Using pre-computed chain mapping for order {order.order_id}: {affected_chain_ids}")

                # Fallback: Try to find chains by other means if pre-computed mapping didn't work
                if not affected_chain_ids:
                    for tx in order.closing_transactions:
                        # V3: Use lot-based matching if available (may not work if lots already closed)
                        if self._use_lots and self.lot_manager:
                            # Find lots for this symbol that are open
                            lots = self.lot_manager.get_open_lots(
                                account_number=tx.account_number,
                                symbol=tx.symbol
                            )
                            for lot in lots:
                                if lot.chain_id and lot.chain_id in chains:
                                    affected_chain_ids.add(lot.chain_id)

                        # Also try legacy position-based matching
                        if not affected_chain_ids:
                            position = self.position_manager.get_position(tx.account_number, tx.symbol)

                            if position:
                                # Find which chain contains orders that opened this position
                                for chain_id, chain in chains.items():
                                    if (chain.underlying == order.underlying and
                                        chain.account_number == order.account_number and
                                        chain.status == "OPEN"):

                                        # Check if this chain has any orders that could have opened this position
                                        for chain_order in chain.orders:
                                            if any(t.symbol == tx.symbol for t in chain_order.opening_transactions):
                                                affected_chain_ids.add(chain_id)
                                                break

                        # Last resort: Find chain by symbol match in existing chains
                        if not affected_chain_ids:
                            for chain_id, chain in chains.items():
                                if (chain.underlying == order.underlying and
                                    chain.account_number == order.account_number):
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
    
    def _find_stock_merge_target(self, chains: dict, underlying: str, account_number: str) -> Optional[str]:
        """Find an existing open chain with stock lots for the same underlying+account.

        Returns chain_id to merge into, or None if no suitable target.
        Only merges stock-only opening orders — options always create new chains.
        """
        for chain_id, chain in chains.items():
            if (chain.underlying != underlying or
                chain.account_number != account_number or
                chain.status == 'CLOSED'):
                continue

            # Check if this chain has open stock lots (from assignments or direct stock purchases)
            has_open_stock = False
            for order in chain.orders:
                for tx in order.transactions:
                    # Stock transaction: no strike price
                    if tx.strike is None and tx.is_opening:
                        has_open_stock = True
                        break
                    # Also check for derived stock from assignments
                    if tx.is_assignment:
                        has_open_stock = True
                        break
                if has_open_stock:
                    break

            # V3: Also check lot manager for open stock lots
            if not has_open_stock and self._use_lots and self.lot_manager:
                lots = self.lot_manager.get_lots_for_chain(chain_id, include_derived=True)
                for lot in lots:
                    if (lot.status != 'CLOSED' and
                        lot.instrument_type in (None, 'EQUITY') and
                        lot.strike is None):
                        has_open_stock = True
                        break

            if has_open_stock:
                return chain_id

        return None

    def _merge_chains(self, chains_to_merge: List[Chain], new_order: Order) -> Chain:
        """Merge multiple chains into one

        When lot_manager is available, also updates lot chain_ids to point
        to the new merged chain.
        """
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
        merged_chain_id = f"{base_chain.chain_id}_MERGED"
        merged_chain = Chain(
            chain_id=merged_chain_id,
            underlying=base_chain.underlying,
            account_number=base_chain.account_number,
            orders=all_orders
        )

        # V3: Update lot chain_ids to point to merged chain
        if self._use_lots and self.lot_manager:
            for chain in chains_to_merge:
                lots = self.lot_manager.get_lots_for_chain(chain.chain_id)
                for lot in lots:
                    self.lot_manager.update_lot_chain(lot.id, merged_chain_id)
                logger.debug(f"Updated {len(lots)} lots from chain {chain.chain_id} to {merged_chain_id}")

        return merged_chain
    
    def _determine_chain_status(self, chain: Chain) -> str:
        """Determine if chain is OPEN or CLOSED based on positions

        When lot_manager is available, also checks for open lots and
        can return 'ASSIGNED' status when chain has assignment but open lots.
        """
        # Check for assignments in chain
        has_assignment = any(
            any(tx.is_assignment for tx in order.transactions)
            for order in chain.orders
        )

        # V3: Check lots if lot_manager is available
        if self._use_lots and self.lot_manager:
            open_lots = self.lot_manager.get_open_lots(
                account_number=chain.account_number,
                chain_id=chain.chain_id
            )

            if open_lots:
                # Has open lots
                if has_assignment:
                    # Has assignment and open lots (e.g., stock from assignment)
                    return "ASSIGNED"
                return "OPEN"
            else:
                # No open lots in this chain
                return "CLOSED"

        # Fallback: Check position inventory (legacy)
        all_symbols = set()
        for order in chain.orders:
            all_symbols.update(order.symbols)

        # Check if any positions are still open
        for symbol in all_symbols:
            position = self.position_manager.get_position(chain.account_number, symbol)
            if position and not position.is_closed:
                if has_assignment:
                    return "ASSIGNED"
                return "OPEN"

        return "CLOSED"