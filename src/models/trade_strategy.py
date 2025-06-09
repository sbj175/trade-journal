"""
Trade Strategy Recognition and Management
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re
import pytz
import logging

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    # Multi-leg Complex Strategies
    IRON_CONDOR = "Iron Condor"
    IRON_BUTTERFLY = "Iron Butterfly"
    BROKEN_WING_BUTTERFLY = "Broken Wing Butterfly"
    BUTTERFLY = "Butterfly"
    
    # Vertical Spreads
    BULL_PUT_SPREAD = "Bull Put Spread"
    BEAR_CALL_SPREAD = "Bear Call Spread"
    BULL_CALL_SPREAD = "Bull Call Spread"
    BEAR_PUT_SPREAD = "Bear Put Spread"
    VERTICAL_SPREAD = "Vertical Spread"  # Generic vertical
    
    # Time Spreads
    CALENDAR_SPREAD = "Calendar Spread"
    DIAGONAL_SPREAD = "Diagonal Spread"
    
    # Volatility Plays
    STRADDLE = "Straddle"
    STRANGLE = "Strangle"
    
    # Stock + Option Combos
    COVERED_CALL = "Covered Call"
    CASH_SECURED_PUT = "Cash Secured Put"
    
    # Position Management
    CALL_ROLL = "Call Roll"
    PUT_ROLL = "Put Roll"
    
    # Single Leg
    NAKED_PUT = "Naked Put"
    NAKED_CALL = "Naked Call"
    LONG_CALL = "Long Call"
    LONG_PUT = "Long Put"
    
    # Stock Only
    LONG_STOCK = "Long Stock"
    SHORT_STOCK = "Short Stock"
    
    # Other
    COMPLEX_STRATEGY = "Complex Strategy"
    UNKNOWN = "Unknown"


class StrategyDirection(Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"
    VOLATILITY = "Volatility"


class TradeStatus(Enum):
    OPEN = "Open"
    CLOSED = "Closed"
    ROLLED = "Rolled"
    EXPIRED = "Expired"
    ASSIGNED = "Assigned"
    PARTIALLY_CLOSED = "Partially Closed"


@dataclass
class OptionLeg:
    """Represents a single option leg in a strategy"""
    symbol: str
    underlying: str
    option_type: str  # 'Call' or 'Put'
    strike: float
    expiration: date
    quantity: int  # Positive for long, negative for short
    entry_price: float
    exit_price: Optional[float] = None
    transaction_ids: List[str] = field(default_factory=list)
    transaction_actions: List[str] = field(default_factory=list)
    transaction_timestamps: List[str] = field(default_factory=list)
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0


@dataclass
class StockLeg:
    """Represents a stock position leg"""
    symbol: str
    quantity: int  # Positive for long, negative for short
    entry_price: float
    exit_price: Optional[float] = None
    transaction_ids: List[str] = field(default_factory=list)
    transaction_actions: List[str] = field(default_factory=list)
    transaction_timestamps: List[str] = field(default_factory=list)


@dataclass
class Trade:
    """Represents a complete trading strategy"""
    trade_id: str
    underlying: str
    strategy_type: StrategyType
    entry_date: date
    exit_date: Optional[date] = None
    status: TradeStatus = TradeStatus.OPEN
    account_number: str = "UNKNOWN"  # Account this trade belongs to
    option_legs: List[OptionLeg] = field(default_factory=list)
    stock_legs: List[StockLeg] = field(default_factory=list)
    original_notes: str = ""  # Initial strategy/thesis
    current_notes: str = ""   # Latest analysis/plan
    tags: List[str] = field(default_factory=list)
    strategy_direction: Optional[str] = None
    includes_roll: bool = False  # True if this trade involves rolling a position
    
    @property
    def days_in_trade(self) -> Optional[int]:
        if self.exit_date:
            return (self.exit_date - self.entry_date).days
        else:
            return (date.today() - self.entry_date).days
    
    @property
    def total_premium_collected(self) -> float:
        """Calculate total premium collected (credit strategies)"""
        premium = 0
        for leg in self.option_legs:
            if leg.is_short:
                premium += abs(leg.quantity) * leg.entry_price * 100
        return premium
    
    @property
    def total_premium_paid(self) -> float:
        """Calculate total premium paid (debit strategies)"""
        premium = 0
        for leg in self.option_legs:
            if leg.is_long:
                premium += leg.quantity * leg.entry_price * 100
        return premium
    
    @property
    def net_premium(self) -> float:
        """Net premium (positive = credit, negative = debit)"""
        return self.total_premium_collected - self.total_premium_paid
    
    @property
    def current_pnl(self) -> float:
        """Calculate current P&L for the trade"""
        pnl = 0
        
        # Options P&L
        for leg in self.option_legs:
            if leg.exit_price is not None:
                # Closed position - calculate realized P&L
                # For long options: P&L = (exit - entry) * quantity * 100
                # For short options: P&L = (entry - exit) * |quantity| * 100
                if leg.is_long:
                    pnl += (leg.exit_price - leg.entry_price) * leg.quantity * 100
                else:
                    pnl += (leg.entry_price - leg.exit_price) * abs(leg.quantity) * 100
            # For open positions, P&L remains 0 until closed
        
        # Stock P&L
        for leg in self.stock_legs:
            if leg.exit_price is not None:
                # Closed position
                if leg.quantity > 0:
                    pnl += (leg.exit_price - leg.entry_price) * leg.quantity
                else:
                    pnl += (leg.entry_price - leg.exit_price) * abs(leg.quantity)
        
        return pnl


class StrategyRecognizer:
    """Recognizes trading strategies from transaction data"""
    
    @staticmethod
    def parse_option_symbol(symbol: str) -> Dict:
        """Parse option symbol to extract components"""
        # Format: UNDERLYING YYMMDD[C/P]STRIKE
        # Example: AAPL 241220C00220000
        
        pattern = r'^([A-Z]+)\s+(\d{6})([CP])(\d{8})$'
        match = re.match(pattern, symbol)
        
        if not match:
            return {}
        
        underlying, date_str, option_type, strike_str = match.groups()
        
        # Parse date (YYMMDD format)
        year = 2000 + int(date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        expiration = date(year, month, day)
        
        # Parse strike (8 digits with implied decimal)
        strike = float(strike_str) / 1000
        
        return {
            'underlying': underlying,
            'expiration': expiration,
            'option_type': 'Call' if option_type == 'C' else 'Put',
            'strike': strike
        }
    
    @classmethod
    def get_stock_positions(cls, transactions: List[Dict]) -> Dict[str, int]:
        """
        Calculate cumulative stock positions from transactions
        
        Returns:
            Dict of symbol -> share count
        """
        positions = {}
        
        # Sort by date to process in order
        sorted_txs = sorted(transactions, key=lambda x: x.get('executed_at', ''))
        
        for tx in sorted_txs:
            instrument_type = str(tx.get('instrument_type', ''))
            # Check for stock transactions (EQUITY but not EQUITY_OPTION)
            if 'EQUITY' in instrument_type and 'OPTION' not in instrument_type:
                symbol = tx.get('symbol', '')
                quantity = tx.get('quantity', 0) or 0
                
                # Handle sell transactions (make them negative)
                action = str(tx.get('action', ''))
                if 'SELL' in action:
                    quantity = -quantity
                
                if symbol not in positions:
                    positions[symbol] = 0
                positions[symbol] += quantity
        
        return positions
    
    @classmethod
    def get_stock_positions_at_time(cls, transactions: List[Dict], cutoff_time: str, underlying: str, account_number: str = None) -> int:
        """
        Calculate stock position for a specific underlying at a specific point in time
        
        Args:
            transactions: All account transactions
            cutoff_time: ISO timestamp - only consider transactions before this time
            underlying: Symbol to calculate position for
            account_number: Only consider transactions from this account (optional)
            
        Returns:
            Share count for the underlying at the cutoff time
        """
        position = 0
        
        # Sort by date to process in order
        sorted_txs = sorted(transactions, key=lambda x: x.get('executed_at', ''))
        
        for tx in sorted_txs:
            # Only consider transactions before the cutoff time
            tx_time = tx.get('executed_at', '')
            if tx_time and tx_time >= cutoff_time:
                break
            
            # Filter by account if specified
            if account_number and tx.get('account_number') != account_number:
                continue
                
            instrument_type = str(tx.get('instrument_type', ''))
            # Check for stock transactions (EQUITY but not EQUITY_OPTION)
            if ('EQUITY' in instrument_type and 'OPTION' not in instrument_type and 
                tx.get('symbol', '') == underlying):
                
                quantity = tx.get('quantity', 0) or 0
                
                # Handle sell transactions (make them negative)
                action = str(tx.get('action', ''))
                if 'SELL' in action:
                    quantity = -quantity
                
                position += quantity
        
        return position
    
    @classmethod
    def group_transactions_into_trades(cls, transactions: List[Dict]) -> List[Trade]:
        """Group individual transactions into logical trades"""
        
        # Global duplicate prevention - remove duplicate transactions by ID first
        seen_transaction_ids = set()
        unique_transactions = []
        
        for tx in transactions:
            tx_id = str(tx.get('id', ''))
            if tx_id and tx_id not in seen_transaction_ids:
                seen_transaction_ids.add(tx_id)
                unique_transactions.append(tx)
        
        # Use deduplicated transactions for the rest of the process
        transactions = unique_transactions
        
        # Process each account separately to prevent cross-account grouping
        accounts = {}
        for tx in transactions:
            account_number = tx.get('account_number', 'UNKNOWN')
            if account_number not in accounts:
                accounts[account_number] = []
            accounts[account_number].append(tx)
        
        all_trades = []
        
        # Process each account independently
        for account_number, account_txs in accounts.items():
            logger.info(f"Processing {len(account_txs)} transactions for account {account_number}")
            
            # Calculate stock positions for this account only
            stock_positions = cls.get_stock_positions(account_txs)
            
            # Group transactions by underlying within this account
            grouped_by_underlying = {}
            
            for tx in account_txs:
                instrument_type = str(tx.get('instrument_type', ''))
                if 'EQUITY' not in instrument_type:
                    continue
                    
                underlying = tx.get('underlying_symbol', tx.get('symbol', ''))
                if not underlying:
                    continue
                    
                if underlying not in grouped_by_underlying:
                    grouped_by_underlying[underlying] = []
                
                grouped_by_underlying[underlying].append(tx)
            
            # Process each underlying within this account
            for underlying, txs in grouped_by_underlying.items():
                # Sort by date
                txs.sort(key=lambda x: x.get('executed_at', ''))
                
                # Group transactions that likely belong to the same strategy
                trade_groups = cls._group_related_transactions(txs)
                
                # Convert each group to a Trade object
                for group in trade_groups:
                    trade = cls._create_trade_from_transactions(underlying, group, stock_positions, account_txs)
                    if trade:
                        all_trades.append(trade)
        
        logger.info(f"Created {len(all_trades)} trades from {len(transactions)} transactions across {len(accounts)} accounts")
        return all_trades
    
    @classmethod
    def _group_related_transactions(cls, transactions: List[Dict]) -> List[List[Dict]]:
        """Group transactions that likely belong to the same trade
        
        This improved algorithm:
        1. Identifies all opening transactions first
        2. When it finds a closing transaction, looks for matching opening transactions
        3. Groups all related transactions together
        4. Prevents orphaned closing transactions by finding their opening trades
        5. Prevents duplicate transaction processing
        """
        
        # Remove duplicate transactions based on transaction ID
        seen_transaction_ids = set()
        unique_transactions = []
        
        for tx in transactions:
            tx_id = str(tx.get('id', ''))
            if tx_id and tx_id not in seen_transaction_ids:
                seen_transaction_ids.add(tx_id)
                unique_transactions.append(tx)
        
        # Use the deduplicated transactions
        transactions = unique_transactions
        
        groups = []
        processed_indices = set()
        
        # Build an index of ALL opening transactions by option details (including already processed ones)
        opening_index = {}
        for i, tx in enumerate(transactions):
            if not cls._is_closing_transaction(tx):
                instrument_type = str(tx.get('instrument_type', ''))
                if 'EQUITY_OPTION' in instrument_type:
                    symbol = tx.get('symbol', '')
                    option_info = cls.parse_option_symbol(symbol)
                    if option_info:
                        key = (option_info['underlying'], option_info['expiration'], 
                               option_info['strike'], option_info['option_type'])
                        if key not in opening_index:
                            opening_index[key] = []
                        opening_index[key].append(i)
        
        # Track which group each transaction belongs to
        transaction_to_group = {}
        
        # Process transactions
        for i, tx in enumerate(transactions):
            if i in processed_indices:
                continue
                
            # If this is a closing transaction, try to find its opening transaction
            if cls._is_closing_transaction(tx):
                instrument_type = str(tx.get('instrument_type', ''))
                if 'EQUITY_OPTION' in instrument_type:
                    symbol = tx.get('symbol', '')
                    option_info = cls.parse_option_symbol(symbol)
                    if option_info:
                        key = (option_info['underlying'], option_info['expiration'],
                               option_info['strike'], option_info['option_type'])
                        
                        # Find matching opening transactions (even if already processed)
                        found_existing_group = False
                        if key in opening_index:
                            for opening_idx in opening_index[key]:
                                # Check if this opening transaction is already in a group
                                if opening_idx in transaction_to_group:
                                    # Add this closing transaction to the existing group
                                    existing_group_idx = transaction_to_group[opening_idx]
                                    groups[existing_group_idx].append(tx)
                                    transaction_to_group[i] = existing_group_idx
                                    processed_indices.add(i)
                                    found_existing_group = True
                                    break
                                elif opening_idx not in processed_indices:
                                    # Create new group with opening and closing transactions
                                    group = [tx, transactions[opening_idx]]
                                    processed_indices.add(i)
                                    processed_indices.add(opening_idx)
                                    
                                    # Track group membership
                                    group_idx = len(groups)
                                    transaction_to_group[i] = group_idx
                                    transaction_to_group[opening_idx] = group_idx
                                    
                                    # Include other options opened on the same day (for multi-leg strategies)
                                    opening_tx = transactions[opening_idx]
                                    opening_date = cls._get_transaction_date(opening_tx)
                                    
                                    for j, other_tx in enumerate(transactions):
                                        if (j not in processed_indices and 
                                            not cls._is_closing_transaction(other_tx) and
                                            cls._get_transaction_date(other_tx) == opening_date):
                                            other_type = str(other_tx.get('instrument_type', ''))
                                            if 'EQUITY_OPTION' in other_type:
                                                other_symbol = other_tx.get('symbol', '')
                                                other_info = cls.parse_option_symbol(other_symbol)
                                                if (other_info and 
                                                    other_info['underlying'] == option_info['underlying'] and
                                                    other_info['expiration'] == option_info['expiration']):
                                                    group.append(other_tx)
                                                    processed_indices.add(j)
                                                    transaction_to_group[j] = group_idx
                                    
                                    # Sort group by date and add to groups
                                    group.sort(key=lambda x: x.get('executed_at', ''))
                                    groups.append(group)
                                    found_existing_group = True
                                    break
                        
                        # If no matching opening transaction found, this is likely an orphaned closing transaction
                        # Skip it to prevent creating single-leg trades
                        if not found_existing_group:
                            processed_indices.add(i)
                            continue
            
            # If this is an opening transaction and not yet processed
            elif i not in processed_indices:
                group = [tx]
                processed_indices.add(i)
                group_idx = len(groups)
                transaction_to_group[i] = group_idx
                
                # Group related transactions more conservatively
                # Allow multi-leg strategies but prevent massive over-grouping
                tx_date = cls._get_transaction_date(tx)
                for j in range(i + 1, len(transactions)):
                    if j not in processed_indices:
                        other_tx = transactions[j]
                        if cls._should_group_conservatively(group, other_tx):
                            group.append(other_tx)
                            processed_indices.add(j)
                            transaction_to_group[j] = group_idx
                
                # Sort group by date and add to groups
                group.sort(key=lambda x: x.get('executed_at', ''))
                groups.append(group)
        
        return groups
    
    @classmethod
    def _get_transaction_date(cls, transaction: Dict) -> date:
        """Get the date of a transaction with timezone handling"""
        et_tz = pytz.timezone('America/New_York')
        executed_at = transaction.get('executed_at', '')
        if executed_at:
            dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
            et_dt = dt.astimezone(et_tz)
            return et_dt.date()
        return date.today()
    
    @classmethod
    def _should_group_conservatively(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """
        Conservative grouping that allows multi-leg strategies but prevents over-grouping
        
        Rules:
        1. Same exact contract (expiration/strike/type) - always group
        2. Same expiration, different strikes - allow (vertical spreads, iron condors)
        3. Same day, limited legs (≤4) - allow (complex strategies)
        4. Multiple expirations with many legs - prevent over-grouping
        """
        
        # Get the first transaction in the group for comparison
        first_tx = current_group[0]
        
        # Same exact contract - always group
        if cls._is_same_contract(first_tx, new_tx):
            return True
        
        # Check if both are options
        first_type = str(first_tx.get('instrument_type', ''))
        new_type = str(new_tx.get('instrument_type', ''))
        
        if 'EQUITY_OPTION' in first_type and 'EQUITY_OPTION' in new_type:
            first_option = cls.parse_option_symbol(first_tx.get('symbol', ''))
            new_option = cls.parse_option_symbol(new_tx.get('symbol', ''))
            
            if first_option and new_option and first_option['underlying'] == new_option['underlying']:
                # Same expiration - allow (vertical spreads, butterflies)
                if first_option['expiration'] == new_option['expiration']:
                    return True
                
                # Different expirations - be extremely conservative
                # Only allow calendar spreads (same strike, different expiration) or diagonal spreads
                if (len(current_group) == 1 and  # Only pair transactions, no big groups
                    first_option['strike'] == new_option['strike']):  # Same strike = calendar/diagonal
                    # Check if transactions are very close in time (within 1 hour)
                    import datetime
                    first_time = datetime.datetime.fromisoformat(first_tx.get('executed_at', '').replace('Z', '+00:00'))
                    new_time = datetime.datetime.fromisoformat(new_tx.get('executed_at', '').replace('Z', '+00:00'))
                    time_diff = abs((new_time - first_time).total_seconds())
                    if time_diff <= 3600:  # Within 1 hour
                        return True
        
        # Stock transactions with same symbol
        elif ('EQUITY' in first_type and 'OPTION' not in first_type and 
              'EQUITY' in new_type and 'OPTION' not in new_type):
            return first_tx.get('symbol', '') == new_tx.get('symbol', '')
        
        return False
    
    @classmethod
    def _is_same_contract(cls, tx1: Dict, tx2: Dict) -> bool:
        """Check if two transactions are for the same contract"""
        
        type1 = str(tx1.get('instrument_type', ''))
        type2 = str(tx2.get('instrument_type', ''))
        
        # Stock transactions: same symbol
        if ('EQUITY' in type1 and 'OPTION' not in type1 and 
            'EQUITY' in type2 and 'OPTION' not in type2):
            return tx1.get('symbol', '') == tx2.get('symbol', '')
        
        # Option transactions: same underlying, expiration, strike, type
        if 'EQUITY_OPTION' in type1 and 'EQUITY_OPTION' in type2:
            option1 = cls.parse_option_symbol(tx1.get('symbol', ''))
            option2 = cls.parse_option_symbol(tx2.get('symbol', ''))
            
            if option1 and option2:
                return (option1['underlying'] == option2['underlying'] and
                        option1['expiration'] == option2['expiration'] and
                        option1['strike'] == option2['strike'] and
                        option1['option_type'] == option2['option_type'])
        
        return False
    
    @classmethod
    def _should_group_transactions(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """Determine if a transaction should be grouped with existing transactions"""
        
        # Get the last transaction date in current group
        last_tx = current_group[-1]
        last_date = datetime.fromisoformat(last_tx.get('executed_at', ''))
        new_date = datetime.fromisoformat(new_tx.get('executed_at', ''))
        
        # Check for roll pattern: closing transaction followed immediately by opening transaction
        # with different expiration (should NOT be grouped)
        if cls._is_roll_pattern(current_group, new_tx):
            return False
        
        # Special handling for covered calls: Don't group stock with unrelated options
        if cls._is_covered_call_candidate(current_group, new_tx):
            # Only group if the option is a short call on the same underlying
            # and happens reasonably close in time (within 30 days)
            time_diff_days = abs((new_date - last_date).days)
            if time_diff_days <= 30:
                return True
            else:
                return False
        
        # Group if transactions are within same day or very close
        time_diff = abs((new_date - last_date).total_seconds())
        # Don't group if it's just time-based and involves mixing stock and options
        # (unless it's a covered call candidate)
        if time_diff <= 3600:  # Within 1 hour
            # Check if this would create an invalid grouping
            has_stock_in_group = any(str(tx.get('instrument_type', '')).upper() == 'EQUITY' for tx in current_group)
            new_is_stock = str(new_tx.get('instrument_type', '')).upper() == 'EQUITY'
            has_option_in_group = any('EQUITY_OPTION' in str(tx.get('instrument_type', '')).upper() for tx in current_group)
            new_is_option = 'EQUITY_OPTION' in str(new_tx.get('instrument_type', '')).upper()
            
            # If mixing stock and options, only allow if it's a valid covered call pattern
            if (has_stock_in_group and new_is_option) or (has_option_in_group and new_is_stock):
                # Don't group just based on time - need covered call pattern
                return False
            
            return True
        
        # Group if they're opening/closing positions on same expiration
        if cls._same_expiration_group(current_group, new_tx):
            return True
        
        # Group closing transactions with their opening transactions
        if cls._is_closing_transaction(new_tx):
            # Check if this closing transaction matches any open position in the group
            for tx in current_group:
                if cls._matches_opening_transaction(tx, new_tx):
                    return True
        
        return False
    
    @classmethod
    def _is_covered_call_candidate(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """Check if this could be a covered call (stock + short call)"""
        
        # Check if current group has stock and new tx is option (or vice versa)
        has_stock = any(str(tx.get('instrument_type', '')).upper() == 'EQUITY' for tx in current_group)
        has_option = any('EQUITY_OPTION' in str(tx.get('instrument_type', '')).upper() for tx in current_group)
        
        new_is_stock = str(new_tx.get('instrument_type', '')).upper() == 'EQUITY'
        new_is_option = 'EQUITY_OPTION' in str(new_tx.get('instrument_type', '')).upper()
        
        # Case 1: Group has stock, new tx is short call
        if has_stock and new_is_option:
            action = str(new_tx.get('action', ''))
            if 'SELL' in action and 'OPEN' in action:
                # Check if it's a call option on the same underlying
                option_info = cls.parse_option_symbol(new_tx.get('symbol', ''))
                if option_info and option_info['option_type'] == 'Call':
                    # Check if underlying matches stock in group
                    for tx in current_group:
                        if str(tx.get('instrument_type', '')).upper() == 'EQUITY':
                            stock_symbol = tx.get('symbol', '')
                            if stock_symbol == option_info['underlying']:
                                return True
        
        # Case 2: Group has short call, new tx is stock
        elif has_option and new_is_stock:
            # Check if group has short calls
            for tx in current_group:
                if 'EQUITY_OPTION' in str(tx.get('instrument_type', '')):
                    action = str(tx.get('action', ''))
                    if 'SELL' in action and 'OPEN' in action:
                        option_info = cls.parse_option_symbol(tx.get('symbol', ''))
                        if option_info and option_info['option_type'] == 'Call':
                            # Check if new stock matches the underlying
                            if new_tx.get('symbol', '') == option_info['underlying']:
                                return True
        
        return False
    
    @classmethod
    def _is_roll_pattern(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """Check if this looks like a roll pattern (closing + opening different expiration)"""
        
        # Only check if the new transaction is an opening transaction
        if cls._is_closing_transaction(new_tx):
            return False
        
        # Check if the current group contains any closing transactions
        has_closing = any(cls._is_closing_transaction(tx) for tx in current_group)
        if not has_closing:
            return False
        
        # Check if both are options
        new_instrument_type = str(new_tx.get('instrument_type', ''))
        if 'EQUITY_OPTION' not in new_instrument_type:
            return False
        
        # Parse new transaction option info
        new_option_info = cls.parse_option_symbol(new_tx.get('symbol', ''))
        if not new_option_info:
            return False
        
        # Check if any closing transaction in the group has different expiration
        for tx in current_group:
            if cls._is_closing_transaction(tx):
                tx_instrument_type = str(tx.get('instrument_type', ''))
                if 'EQUITY_OPTION' in tx_instrument_type:
                    tx_option_info = cls.parse_option_symbol(tx.get('symbol', ''))
                    if (tx_option_info and 
                        tx_option_info['underlying'] == new_option_info['underlying'] and
                        tx_option_info['option_type'] == new_option_info['option_type'] and
                        tx_option_info['strike'] == new_option_info['strike'] and
                        tx_option_info['expiration'] != new_option_info['expiration']):
                        # This looks like a roll: same underlying/type/strike, different expiration
                        return True
        
        return False
    
    @classmethod
    def _same_expiration_group(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """Check if transactions involve the same option expiration"""
        
        # Extract option info from symbols
        for tx in current_group:
            if tx.get('instrument_type') == 'Equity Option':
                current_option = cls.parse_option_symbol(tx.get('symbol', ''))
                new_option = cls.parse_option_symbol(new_tx.get('symbol', ''))
                
                if (current_option and new_option and 
                    current_option.get('expiration') == new_option.get('expiration')):
                    return True
        
        return False
    
    @classmethod
    def _create_trade_from_transactions(cls, underlying: str, transactions: List[Dict], stock_positions: Dict[str, int] = None, all_account_transactions: List[Dict] = None) -> Optional[Trade]:
        """Create a Trade object from a group of transactions"""
        
        if not transactions:
            return None
        
        # Generate trade ID with timezone handling
        first_tx = transactions[0]
        # Convert to Eastern time for consistent date representation
        et_tz = pytz.timezone('America/New_York')
        executed_at = first_tx.get('executed_at', '')
        # Parse the timestamp and convert to Eastern time
        if executed_at:
            dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
            et_dt = dt.astimezone(et_tz)
            entry_date = et_dt.date()
        else:
            entry_date = date.today()
        
        # Extract account number from first transaction
        account_number = first_tx.get('account_number', 'UNKNOWN')
        
        # Include account suffix to prevent ID collisions across accounts
        account_suffix = account_number[-3:] if account_number != 'UNKNOWN' else 'UNK'
        trade_id = f"{underlying}_{entry_date.strftime('%Y%m%d')}_{len(transactions)}legs_{account_suffix}"
        
        # Create trade object
        trade = Trade(
            trade_id=trade_id,
            underlying=underlying,
            strategy_type=StrategyType.UNKNOWN,
            entry_date=entry_date,
            account_number=account_number
        )
        
        # Process each transaction into legs
        for tx in transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'EQUITY_OPTION' in instrument_type:
                cls._add_option_leg(trade, tx)
            elif 'EQUITY' in instrument_type and 'OPTION' not in instrument_type:
                cls._add_stock_leg(trade, tx)
        
        # Recognize the strategy
        if stock_positions and all_account_transactions:
            trade.strategy_type = cls._recognize_strategy_with_positions(trade, stock_positions, all_account_transactions)
        elif stock_positions:
            trade.strategy_type = cls._recognize_strategy_with_positions(trade, stock_positions)
        else:
            trade.strategy_type = cls._recognize_strategy(trade)
        direction = cls._determine_strategy_direction(trade)
        trade.strategy_direction = direction.value if direction else None
        
        # Determine if trade is closed and find the latest closing date
        if cls._is_trade_closed(trade):
            trade.status = TradeStatus.CLOSED
            # Find the latest closing transaction date with timezone handling
            et_tz = pytz.timezone('America/New_York')
            latest_date = None
            for tx in transactions:
                if cls._is_closing_transaction(tx):
                    executed_at = tx.get('executed_at', '')
                    if executed_at:
                        dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                        et_dt = dt.astimezone(et_tz)
                        tx_date = et_dt.date()
                        if latest_date is None or tx_date > latest_date:
                            latest_date = tx_date
            
            trade.exit_date = latest_date or entry_date
        
        return trade
    
    @classmethod
    def _add_option_leg(cls, trade: Trade, transaction: Dict):
        """Add an option leg to the trade"""
        
        symbol = transaction.get('symbol', '')
        option_info = cls.parse_option_symbol(symbol)
        
        if not option_info:
            return
        
        quantity = int(transaction.get('quantity', 0))
        action_str = str(transaction.get('action', ''))
        if 'SELL' in action_str:
            quantity = -abs(quantity)  # Short position
        
        price = transaction.get('price')
        entry_price = float(price) if price is not None else 0.0
        
        # Check if this is a closing transaction
        is_closing = cls._is_closing_transaction(transaction)
        
        # Find existing leg with same strike/type/expiration
        existing_leg = None
        for leg in trade.option_legs:
            if (leg.strike == option_info['strike'] and
                leg.option_type == option_info['option_type'] and
                leg.expiration == option_info['expiration']):
                existing_leg = leg
                break
        
        if is_closing and existing_leg:
            # This is a closing transaction - update the existing leg
            existing_leg.exit_price = entry_price
            existing_leg.transaction_ids.append(str(transaction.get('id', '')))
            
            # Normalize and add action (avoid duplicates)
            normalized_action = cls._normalize_action(action_str, transaction)
            if normalized_action not in existing_leg.transaction_actions:
                existing_leg.transaction_actions.append(normalized_action)
            
            if transaction.get('executed_at'):
                existing_leg.transaction_timestamps.append(transaction.get('executed_at'))
        elif is_closing and not existing_leg:
            # This is a closing transaction with no existing leg to close
            # Likely closing a position from a previous trade - skip creating a new leg
            return
        else:
            # This is an opening transaction - create new leg
            normalized_action = cls._normalize_action(action_str, transaction)
            leg = OptionLeg(
                symbol=symbol,
                underlying=option_info['underlying'],
                option_type=option_info['option_type'],
                strike=option_info['strike'],
                expiration=option_info['expiration'],
                quantity=quantity,
                entry_price=entry_price,
                transaction_ids=[str(transaction.get('id', ''))],
                transaction_actions=[normalized_action],
                transaction_timestamps=[transaction.get('executed_at')] if transaction.get('executed_at') else []
            )
            
            trade.option_legs.append(leg)
    
    @classmethod
    def _add_stock_leg(cls, trade: Trade, transaction: Dict):
        """Add a stock leg to the trade"""
        
        quantity = int(transaction.get('quantity', 0))
        action_str = str(transaction.get('action', ''))
        if 'SELL' in action_str:
            quantity = -abs(quantity)
        
        price = transaction.get('price')
        entry_price = float(price) if price is not None else 0.0
        
        # Check if this is a closing transaction
        is_closing = cls._is_closing_transaction(transaction)
        
        # Find existing leg with same symbol
        existing_leg = None
        for leg in trade.stock_legs:
            if leg.symbol == transaction.get('symbol', ''):
                existing_leg = leg
                break
        
        if is_closing and existing_leg:
            # This is a closing transaction - update the existing leg
            existing_leg.exit_price = entry_price
            existing_leg.transaction_ids.append(str(transaction.get('id', '')))
            
            # Normalize and add action (avoid duplicates)
            normalized_action = cls._normalize_action(action_str, transaction)
            if normalized_action not in existing_leg.transaction_actions:
                existing_leg.transaction_actions.append(normalized_action)
            
            if transaction.get('executed_at'):
                existing_leg.transaction_timestamps.append(transaction.get('executed_at'))
        else:
            # This is an opening transaction - create new leg
            normalized_action = cls._normalize_action(action_str, transaction)
            leg = StockLeg(
                symbol=transaction.get('symbol', ''),
                quantity=quantity,
                entry_price=entry_price,
                transaction_ids=[str(transaction.get('id', ''))],
                transaction_actions=[normalized_action],
                transaction_timestamps=[transaction.get('executed_at')] if transaction.get('executed_at') else []
            )
            
            trade.stock_legs.append(leg)
    
    @classmethod
    def _recognize_strategy_with_positions(cls, trade: Trade, stock_positions: Dict[str, int], all_account_transactions: List[Dict] = None) -> StrategyType:
        """
        Enhanced strategy recognition that considers existing stock positions
        for covered call determination
        """
        
        option_legs = trade.option_legs
        stock_legs = trade.stock_legs
        
        if not option_legs and not stock_legs:
            return StrategyType.UNKNOWN
        
        # Stock only strategies
        if stock_legs and not option_legs:
            if stock_legs[0].quantity > 0:
                return StrategyType.LONG_STOCK
            else:
                return StrategyType.SHORT_STOCK
        
        # Single option strategies
        if len(option_legs) == 1 and not stock_legs:
            leg = option_legs[0]
            
            # Check if this is a short call that could be covered
            if leg.is_short and leg.option_type == 'Call':
                underlying = trade.underlying
                contracts = abs(leg.quantity)
                shares_needed = contracts * 100
                
                # If we have all account transactions, check position at time of option trade
                if all_account_transactions and leg.transaction_timestamps:
                    # Get the timestamp of the first option transaction (when the call was sold)
                    option_time = leg.transaction_timestamps[0]
                    # Calculate stock position at that time for the same account
                    existing_shares = cls.get_stock_positions_at_time(all_account_transactions, option_time, underlying, trade.account_number)
                    
                    if existing_shares >= shares_needed:
                        return StrategyType.COVERED_CALL
                    else:
                        return StrategyType.NAKED_CALL
                else:
                    # Fallback to current position calculation
                    existing_shares = stock_positions.get(underlying, 0)
                    
                    if existing_shares >= shares_needed:
                        return StrategyType.COVERED_CALL
                    else:
                        return StrategyType.NAKED_CALL
            
            # Other single options - use regular recognition
            return cls._recognize_strategy(trade)
        
        # For all other cases, use regular recognition
        return cls._recognize_strategy(trade)
    
    @classmethod
    def _recognize_strategy(cls, trade: Trade) -> StrategyType:
        """Enhanced strategy recognition based on comprehensive coding system"""
        
        option_legs = trade.option_legs
        stock_legs = trade.stock_legs
        
        if not option_legs and not stock_legs:
            return StrategyType.UNKNOWN
        
        # Stock only strategies
        if stock_legs and not option_legs:
            if stock_legs[0].quantity > 0:
                return StrategyType.LONG_STOCK
            else:
                return StrategyType.SHORT_STOCK
        
        # Single option strategies
        if len(option_legs) == 1 and not stock_legs:
            leg = option_legs[0]
            if leg.is_long:
                return StrategyType.LONG_CALL if leg.option_type == 'Call' else StrategyType.LONG_PUT
            else:
                # Short single options
                if leg.option_type == 'Call':
                    return StrategyType.NAKED_CALL
                else:  # Put
                    return StrategyType.CASH_SECURED_PUT  # Prefer CSP over Naked Put
        
        # Covered call
        if (len(option_legs) == 1 and len(stock_legs) == 1 and
            option_legs[0].is_short and option_legs[0].option_type == 'Call' and
            stock_legs[0].quantity > 0):
            return StrategyType.COVERED_CALL
        
        # Two-leg strategies
        if len(option_legs) == 2 and not stock_legs:
            return cls._recognize_two_leg_strategy(option_legs)
        
        # Three-leg strategies (Butterflies)
        if len(option_legs) == 3 and not stock_legs:
            return cls._recognize_butterfly_strategy(option_legs)
        
        # Four-leg strategies
        if len(option_legs) == 4 and not stock_legs:
            return cls._recognize_four_leg_strategy(option_legs)
        
        # Default for complex strategies
        if len(option_legs) > 4:
            return StrategyType.COMPLEX_STRATEGY
        
        return StrategyType.UNKNOWN
    
    @classmethod
    def _recognize_two_leg_strategy(cls, legs: List[OptionLeg]) -> StrategyType:
        """Recognize two-leg strategies"""
        leg1, leg2 = sorted(legs, key=lambda x: x.strike)
        
        # Same expiration check
        if leg1.expiration == leg2.expiration:
            # Same option type = Vertical Spread
            if leg1.option_type == leg2.option_type:
                # Put spreads
                if leg1.option_type == 'Put':
                    if leg1.is_long and leg2.is_short:
                        return StrategyType.BULL_PUT_SPREAD
                    elif leg1.is_short and leg2.is_long:
                        return StrategyType.BEAR_PUT_SPREAD
                # Call spreads
                else:  # Call
                    if leg1.is_long and leg2.is_short:
                        return StrategyType.BULL_CALL_SPREAD
                    elif leg1.is_short and leg2.is_long:
                        return StrategyType.BEAR_CALL_SPREAD
                
                return StrategyType.VERTICAL_SPREAD
            
            # Different option types = Straddle/Strangle
            else:
                if leg1.strike == leg2.strike:
                    return StrategyType.STRADDLE
                else:
                    return StrategyType.STRANGLE
        
        # Different expirations
        else:
            if leg1.option_type == leg2.option_type:
                if leg1.strike == leg2.strike:
                    return StrategyType.CALENDAR_SPREAD
                else:
                    return StrategyType.DIAGONAL_SPREAD
        
        return StrategyType.VERTICAL_SPREAD
    
    @classmethod
    def _recognize_butterfly_strategy(cls, legs: List[OptionLeg]) -> StrategyType:
        """Recognize butterfly strategies"""
        # Sort by strike
        sorted_legs = sorted(legs, key=lambda x: x.strike)
        
        # Check if all same expiration and option type
        if (all(leg.expiration == sorted_legs[0].expiration for leg in sorted_legs) and
            all(leg.option_type == sorted_legs[0].option_type for leg in sorted_legs)):
            
            # Classic butterfly: long-short-short-long or similar pattern
            strikes = [leg.strike for leg in sorted_legs]
            
            # Check for butterfly pattern (1 long low, 2 short middle, 1 long high)
            if len(set(strikes)) == 3:  # Three unique strikes
                # Count legs at each strike
                strike_counts = {}
                for leg in sorted_legs:
                    if leg.strike not in strike_counts:
                        strike_counts[leg.strike] = {'long': 0, 'short': 0}
                    if leg.is_long:
                        strike_counts[leg.strike]['long'] += 1
                    else:
                        strike_counts[leg.strike]['short'] += 1
                
                # Check for butterfly pattern
                strikes_list = sorted(strike_counts.keys())
                if len(strikes_list) == 3:
                    low_count = strike_counts[strikes_list[0]]
                    mid_count = strike_counts[strikes_list[1]]
                    high_count = strike_counts[strikes_list[2]]
                    
                    # Classic butterfly
                    if (low_count['long'] == 1 and mid_count['short'] == 2 and high_count['long'] == 1):
                        return StrategyType.BUTTERFLY
                    
                    # Broken wing butterfly (uneven strikes)
                    if (low_count['long'] == 1 and mid_count['short'] == 1 and high_count['long'] == 1):
                        # Check if strikes are uneven
                        if (strikes_list[1] - strikes_list[0]) != (strikes_list[2] - strikes_list[1]):
                            return StrategyType.BROKEN_WING_BUTTERFLY
        
        return StrategyType.COMPLEX_STRATEGY
    
    @classmethod
    def _recognize_four_leg_strategy(cls, legs: List[OptionLeg]) -> StrategyType:
        """Recognize four-leg strategies"""
        # Group by option type
        calls = [leg for leg in legs if leg.option_type == 'Call']
        puts = [leg for leg in legs if leg.option_type == 'Put']
        
        # Check same expiration
        if all(leg.expiration == legs[0].expiration for leg in legs):
            # Check for Iron Butterfly first (more specific pattern)
            if len(calls) == 2 and len(puts) == 2:
                # Get all strikes
                all_strikes = sorted(set(leg.strike for leg in legs))
                
                # Iron butterfly has only 3 unique strikes
                if len(all_strikes) == 3:
                    # Check if middle strike has both call and put
                    middle_strike = all_strikes[1]
                    middle_calls = [c for c in calls if c.strike == middle_strike]
                    middle_puts = [p for p in puts if p.strike == middle_strike]
                    
                    if middle_calls and middle_puts:
                        # Verify it's sold at the middle
                        if middle_calls[0].is_short and middle_puts[0].is_short:
                            return StrategyType.IRON_BUTTERFLY
            
            # Iron Condor: 2 calls + 2 puts (4 different strikes)
            if len(calls) == 2 and len(puts) == 2:
                calls_sorted = sorted(calls, key=lambda x: x.strike)
                puts_sorted = sorted(puts, key=lambda x: x.strike)
                
                # Classic iron condor pattern
                # Lower put is long, higher put is short
                # Lower call is short, higher call is long
                if (puts_sorted[0].is_long and puts_sorted[1].is_short and 
                    calls_sorted[0].is_short and calls_sorted[1].is_long):
                    return StrategyType.IRON_CONDOR
            
            # Regular butterfly (all same type)
            if len(calls) == 4 or len(puts) == 4:
                return cls._recognize_butterfly_strategy(legs)
        
        return StrategyType.COMPLEX_STRATEGY
    
    @classmethod
    def _determine_strategy_direction(cls, trade: Trade) -> StrategyDirection:
        """Determine the directional bias of a strategy"""
        strategy_type = trade.strategy_type
        
        # Bullish strategies
        if strategy_type in [StrategyType.BULL_PUT_SPREAD, StrategyType.BULL_CALL_SPREAD,
                           StrategyType.COVERED_CALL, StrategyType.LONG_CALL]:
            return StrategyDirection.BULLISH
        
        # Bearish strategies  
        elif strategy_type in [StrategyType.BEAR_PUT_SPREAD, StrategyType.BEAR_CALL_SPREAD,
                             StrategyType.LONG_PUT]:
            return StrategyDirection.BEARISH
        
        # Neutral strategies
        elif strategy_type in [StrategyType.IRON_CONDOR, StrategyType.IRON_BUTTERFLY,
                             StrategyType.CASH_SECURED_PUT]:
            return StrategyDirection.NEUTRAL
        
        # Volatility plays
        elif strategy_type in [StrategyType.STRADDLE, StrategyType.STRANGLE]:
            # Check if long or short volatility
            if trade.option_legs:
                if all(leg.is_long for leg in trade.option_legs):
                    return StrategyDirection.VOLATILITY  # Long volatility
                elif all(leg.is_short for leg in trade.option_legs):
                    return StrategyDirection.NEUTRAL  # Short volatility
        
        # Butterfly strategies - typically neutral
        elif strategy_type in [StrategyType.BUTTERFLY, StrategyType.BROKEN_WING_BUTTERFLY]:
            return StrategyDirection.NEUTRAL
        
        # Calendar/Diagonal - typically neutral
        elif strategy_type in [StrategyType.CALENDAR_SPREAD, StrategyType.DIAGONAL_SPREAD]:
            return StrategyDirection.NEUTRAL
        
        # Stock positions
        elif strategy_type == StrategyType.LONG_STOCK:
            return StrategyDirection.BULLISH
        elif strategy_type == StrategyType.SHORT_STOCK:
            return StrategyDirection.BEARISH
        
        return StrategyDirection.NEUTRAL
    
    @classmethod
    def _normalize_action(cls, action_str: str, transaction: Dict = None) -> str:
        """Normalize transaction action to clean format"""
        if not action_str or action_str == 'None':
            # Check if this is an assignment/expiration based on other fields
            if transaction:
                description = str(transaction.get('description', '')).upper()
                sub_type = str(transaction.get('transaction_sub_type', '')).upper()
                
                # Check for specific assignment/expiration indicators
                if any(indicator in description for indicator in ['CASH SETTLEMENT', 'CASH SETTLED']):
                    return 'CASH_SETTLED'
                elif any(indicator in description for indicator in ['REMOVAL OF OPTION DUE TO EXERCISE', 'REMOVAL OF OPTION']):
                    return 'EXERCISED'
                elif any(indicator in description for indicator in ['ASSIGNMENT', 'ASSIGNED']):
                    return 'ASSIGNED'
                elif any(indicator in description for indicator in ['EXPIRATION', 'EXPIRED']):
                    return 'EXPIRED'
                elif any(indicator in description for indicator in ['EXERCISE', 'EXERCISED']):
                    return 'EXERCISED'
                elif any(indicator in description for indicator in ['RECEIVE_DELIVER', 'RECEIVE DELIVER']):
                    return 'ASSIGNED/EXPIRED'
                
                # Check transaction_sub_type  
                if any(indicator in sub_type for indicator in ['CASH SETTLEMENT', 'CASH SETTLED']):
                    return 'CASH_SETTLED'
                elif any(indicator in sub_type for indicator in ['ASSIGNMENT', 'ASSIGNED']):
                    return 'ASSIGNED'
                elif any(indicator in sub_type for indicator in ['EXPIRATION', 'EXPIRED']):
                    return 'EXPIRED'
                elif any(indicator in sub_type for indicator in ['EXERCISE', 'EXERCISED']):
                    return 'EXERCISED'
                
                # Check if the price is 0 or equals strike price (strong indicator of assignment/expiration)
                price = transaction.get('price')
                if price is not None:
                    try:
                        price_float = float(price)
                        if price_float == 0:
                            return 'EXERCISED'  # Zero price usually means removal/exercise
                        elif price_float > 1000 and 'SPX' in str(transaction.get('symbol', '')):  # SPX strikes are high
                            return 'CASH_SETTLED'  # High price likely cash settlement value
                    except (ValueError, TypeError):
                        pass
            
            return 'UNKNOWN'
        
        action = str(action_str).upper()
        
        # Handle specific patterns
        if 'CASH SETTLEMENT' in action or 'CASH SETTLED' in action:
            return 'CASH_SETTLED'
        elif 'REMOVAL OF OPTION' in action:
            return 'EXERCISED'
        elif 'RECEIVE_DELIVER' in action or 'RECEIVE DELIVER' in action:
            return 'ASSIGNED/EXPIRED'
        elif 'EXERCISE' in action or 'EXERCISED' in action:
            return 'EXERCISED'
        elif 'ASSIGNMENT' in action or 'ASSIGNED' in action:
            return 'ASSIGNED'
        elif 'EXPIRATION' in action or 'EXPIRED' in action:
            return 'EXPIRED'
        elif 'BUY_TO_OPEN' in action or 'BTO' in action:
            return 'BTO'
        elif 'BUY_TO_CLOSE' in action or 'BTC' in action:
            # Check if this is actually an expiration before returning BTC
            if transaction:
                description = str(transaction.get('description', '')).upper()
                sub_type = str(transaction.get('transaction_sub_type', '')).upper()
                
                # If description or sub_type indicates expiration, return EXPIRED instead
                if any(indicator in description for indicator in ['REMOVAL', 'EXPIRATION', 'EXPIRED']):
                    return 'EXPIRED'
                elif 'EXPIRATION' in sub_type:
                    return 'EXPIRED'
            return 'BTC'
        elif 'SELL_TO_OPEN' in action or 'STO' in action:
            return 'STO'
        elif 'SELL_TO_CLOSE' in action or 'STC' in action:
            return 'STC'
        elif 'ORDERACTION.' in action:
            # Handle OrderAction.BUY_TO_OPEN format
            return action.split('.')[-1].replace('_', '').replace('TO', '_TO_')
        
        return action
    
    @classmethod
    def _is_closing_transaction(cls, transaction: Dict) -> bool:
        """Check if a transaction is a closing transaction based on indicators"""
        
        # Check description field for closing indicators
        description = str(transaction.get('description', '')).upper()
        closing_indicators = [
            'BOUGHT TO CLOSE',
            'BTC',
            'SOLD TO CLOSE',
            'SOLD TO COVER',
            'STC',
            'CLOSE',
            'RECEIVE_DELIVER',
            'RECEIVE DELIVER',
            'ASSIGNED',
            'ASSIGNMENT',
            'CASH SETTLED ASSIGNMENT',
            'CASH SETTLEMENT',
            'REMOVAL OF OPTION DUE TO EXERCISE',
            'REMOVAL OF OPTION',
            'EXERCISE',
            'EXERCISED',
            'EXPIRED',
            'EXPIRATION'
        ]
        
        for indicator in closing_indicators:
            if indicator in description:
                return True
        
        # Check transaction_sub_type for closing indicators
        sub_type = str(transaction.get('transaction_sub_type', '')).upper()
        if 'CLOSE' in sub_type or 'COVER' in sub_type:
            return True
        
        # Check action field for specific patterns
        action = str(transaction.get('action', '')).upper()
        if 'CLOSE' in action:
            return True
        
        # Enhanced detection for assignment/expiration transactions
        # Use the same logic as _normalize_action for consistency
        if not transaction.get('action') or transaction.get('action') == 'None':
            # Check for assignment/expiration based on price patterns
            price = transaction.get('price')
            if price is not None:
                try:
                    price_float = float(price)
                    # Zero price or strike-like price (for SPX) indicates assignment/expiration
                    if price_float == 0 or (price_float > 1000 and 'SPX' in str(transaction.get('symbol', ''))):
                        return True
                except (ValueError, TypeError):
                    pass
            
            # Check sub_type and description for assignment indicators
            assignment_indicators = [
                'RECEIVE_DELIVER', 'RECEIVE DELIVER', 'ASSIGNED', 'ASSIGNMENT',
                'CASH SETTLED ASSIGNMENT', 'CASH SETTLEMENT', 'REMOVAL OF OPTION DUE TO EXERCISE',
                'REMOVAL OF OPTION', 'EXERCISE', 'EXERCISED', 'EXPIRED', 'EXPIRATION'
            ]
            if any(indicator in description for indicator in assignment_indicators):
                return True
            if any(indicator in sub_type for indicator in assignment_indicators):
                return True
        
        return False
    
    @classmethod
    def _is_trade_closed(cls, trade: Trade) -> bool:
        """Determine if a trade is closed based on net position and exit prices"""
        
        # Check if all option positions have exit prices
        all_options_have_exits = all(leg.exit_price is not None for leg in trade.option_legs)
        
        # Check if all stock positions have exit prices
        all_stocks_have_exits = all(leg.exit_price is not None for leg in trade.stock_legs)
        
        # If all legs have exit prices, the trade is closed
        if trade.option_legs and all_options_have_exits:
            return True
        if trade.stock_legs and all_stocks_have_exits:
            return True
        
        # Also check net positions as a fallback
        option_net = {}
        for leg in trade.option_legs:
            key = (leg.strike, leg.option_type, leg.expiration)
            option_net[key] = option_net.get(key, 0) + leg.quantity
        
        stock_net = sum(leg.quantity for leg in trade.stock_legs)
        
        # Trade is closed if all net positions are zero
        all_options_closed = all(abs(qty) < 1 for qty in option_net.values())
        all_stocks_closed = abs(stock_net) < 1
        
        return all_options_closed and all_stocks_closed
    
    @classmethod
    def _matches_opening_transaction(cls, opening_tx: Dict, closing_tx: Dict) -> bool:
        """Check if a closing transaction matches an opening transaction"""
        
        # Must be same underlying symbol
        if opening_tx.get('underlying_symbol') != closing_tx.get('underlying_symbol'):
            return False
        
        # For options, check if same strike/type/expiration
        if 'EQUITY_OPTION' in str(opening_tx.get('instrument_type', '')):
            opening_info = cls.parse_option_symbol(opening_tx.get('symbol', ''))
            closing_info = cls.parse_option_symbol(closing_tx.get('symbol', ''))
            
            if (opening_info and closing_info and
                opening_info['strike'] == closing_info['strike'] and
                opening_info['option_type'] == closing_info['option_type'] and
                opening_info['expiration'] == closing_info['expiration']):
                return True
        
        # For stocks, just check symbol
        elif opening_tx.get('symbol') == closing_tx.get('symbol'):
            return True
        
        return False
    
    @classmethod
    def _create_trade_from_strategy_match(cls, strategy_match) -> Optional[Trade]:
        """
        Convert a StrategyMatch object from TransactionMatcher into a Trade object
        
        Args:
            strategy_match: StrategyMatch object containing strategy identification and transactions
            
        Returns:
            Trade object or None if conversion fails
        """
        try:
            from .transaction_matcher import StrategyMatch
            
            if not isinstance(strategy_match, StrategyMatch):
                logger.error(f"Expected StrategyMatch object, got {type(strategy_match)}")
                return None
                
            transactions = strategy_match.transactions
            if not transactions:
                logger.warning("StrategyMatch has no transactions")
                return None
                
            # Extract basic trade information
            first_tx = transactions[0]
            underlying = first_tx.get('underlying_symbol', '').upper()
            account_number = first_tx.get('account_number', 'UNKNOWN')
            
            if not underlying:
                logger.warning("No underlying symbol found in transactions")
                return None
            
            # Determine entry date (earliest transaction date)
            et_tz = pytz.timezone('America/New_York')
            entry_date = None
            exit_date = None
            
            for tx in transactions:
                executed_at = tx.get('executed_at', '')
                if executed_at:
                    try:
                        # Parse and convert to Eastern Time
                        dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                        et_dt = dt.astimezone(et_tz)
                        tx_date = et_dt.date()
                        
                        if entry_date is None or tx_date < entry_date:
                            entry_date = tx_date
                            
                        # Track latest closing transaction for exit date
                        if cls._is_closing_transaction(tx):
                            if exit_date is None or tx_date > exit_date:
                                exit_date = tx_date
                                
                    except Exception as e:
                        logger.warning(f"Failed to parse transaction date {executed_at}: {e}")
                        continue
            
            if not entry_date:
                entry_date = date.today()
            
            # Generate trade ID
            # Include account suffix to prevent ID collisions across accounts
            account_suffix = account_number[-3:] if account_number != 'UNKNOWN' else 'UNK'
            trade_id = f"{underlying}_{entry_date.strftime('%Y%m%d')}_{len(transactions)}legs_{account_suffix}"
            
            # Determine trade status based on StrategyMatch metadata
            trade_status = cls._determine_trade_status_from_strategy_match(strategy_match, exit_date)
            
            # Update exit_date based on strategy metadata
            if hasattr(strategy_match, 'roll_closure_info'):
                roll_info = strategy_match.roll_closure_info
                if roll_info.get('closed_by_roll'):
                    exit_date = roll_info.get('closure_timestamp')
                    if exit_date and hasattr(exit_date, 'date'):
                        exit_date = exit_date.date()
            
            # Clear exit_date if strategy is forced open
            if hasattr(strategy_match, 'status_info'):
                status_info = strategy_match.status_info
                if status_info.get('force_open'):
                    exit_date = None
            
            # Create trade object
            trade = Trade(
                trade_id=trade_id,
                underlying=underlying,
                strategy_type=strategy_match.strategy_type,
                entry_date=entry_date,
                exit_date=exit_date,
                account_number=account_number,
                status=trade_status,
                includes_roll=getattr(strategy_match, 'includes_roll', False)
            )
            
            # Process transactions into legs
            for tx in transactions:
                instrument_type = str(tx.get('instrument_type', ''))
                if 'EQUITY_OPTION' in instrument_type:
                    cls._add_option_leg(trade, tx)
                elif 'EQUITY' in instrument_type and 'OPTION' not in instrument_type:
                    cls._add_stock_leg(trade, tx)
            
            # Set strategy direction
            direction = cls._determine_strategy_direction(trade)
            trade.strategy_direction = direction.value if direction else None
            
            # Add metadata from StrategyMatch
            confidence_notes = f"Confidence: {strategy_match.confidence.value}"
            if strategy_match.quality_flags:
                flag_str = ", ".join([flag.value for flag in strategy_match.quality_flags])
                confidence_notes += f", Flags: {flag_str}"
            
            trade.original_notes = confidence_notes
            
            logger.info(f"Successfully created trade {trade_id} from StrategyMatch: {strategy_match.strategy_type.value}")
            return trade
            
        except Exception as e:
            logger.error(f"Failed to create trade from StrategyMatch: {e}")
            return None
    
    @classmethod
    def _determine_trade_status_from_strategy_match(cls, strategy_match, exit_date) -> TradeStatus:
        """Determine trade status based on StrategyMatch metadata and exit date"""
        
        # Check for roll closure metadata
        if hasattr(strategy_match, 'roll_closure_info'):
            roll_info = strategy_match.roll_closure_info
            if roll_info.get('closed_by_roll'):
                return TradeStatus.CLOSED
        
        # Check for forced status metadata
        if hasattr(strategy_match, 'status_info'):
            status_info = strategy_match.status_info
            if status_info.get('force_open'):
                return TradeStatus.OPEN
            elif status_info.get('force_closed'):
                return TradeStatus.CLOSED
        
        # Default logic: closed if has exit date, otherwise open
        return TradeStatus.CLOSED if exit_date else TradeStatus.OPEN