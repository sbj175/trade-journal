"""
Trade Strategy Recognition and Management
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re


class StrategyType(Enum):
    IRON_CONDOR = "Iron Condor"
    IRON_BUTTERFLY = "Iron Butterfly"
    BROKEN_WING_BUTTERFLY = "Broken Wing Butterfly"
    VERTICAL_SPREAD = "Vertical Spread"
    CALENDAR_SPREAD = "Calendar Spread"
    DIAGONAL_SPREAD = "Diagonal Spread"
    STRADDLE = "Straddle"
    STRANGLE = "Strangle"
    COVERED_CALL = "Covered Call"
    CASH_SECURED_PUT = "Cash Secured Put"
    NAKED_PUT = "Naked Put"
    NAKED_CALL = "Naked Call"
    LONG_STOCK = "Long Stock"
    SHORT_STOCK = "Short Stock"
    COMPLEX_STRATEGY = "Complex Strategy"
    UNKNOWN = "Unknown"


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


@dataclass
class Trade:
    """Represents a complete trading strategy"""
    trade_id: str
    underlying: str
    strategy_type: StrategyType
    entry_date: date
    exit_date: Optional[date] = None
    status: TradeStatus = TradeStatus.OPEN
    option_legs: List[OptionLeg] = field(default_factory=list)
    stock_legs: List[StockLeg] = field(default_factory=list)
    original_notes: str = ""  # Initial strategy/thesis
    current_notes: str = ""   # Latest analysis/plan
    tags: List[str] = field(default_factory=list)
    
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
    def group_transactions_into_trades(cls, transactions: List[Dict]) -> List[Trade]:
        """Group individual transactions into logical trades"""
        
        # First, separate transactions by underlying and date
        grouped_by_underlying = {}
        
        for tx in transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'EQUITY' not in instrument_type:
                continue
                
            underlying = tx.get('underlying_symbol', tx.get('symbol', ''))
            if not underlying:
                continue
                
            if underlying not in grouped_by_underlying:
                grouped_by_underlying[underlying] = []
            
            grouped_by_underlying[underlying].append(tx)
        
        trades = []
        
        # Process each underlying separately
        for underlying, txs in grouped_by_underlying.items():
            # Sort by date
            txs.sort(key=lambda x: x.get('executed_at', ''))
            
            # Group transactions that likely belong to the same strategy
            trade_groups = cls._group_related_transactions(txs)
            
            # Convert each group to a Trade object
            for group in trade_groups:
                trade = cls._create_trade_from_transactions(underlying, group)
                if trade:
                    trades.append(trade)
        
        return trades
    
    @classmethod
    def _group_related_transactions(cls, transactions: List[Dict]) -> List[List[Dict]]:
        """Group transactions that likely belong to the same trade"""
        
        groups = []
        current_group = []
        
        for i, tx in enumerate(transactions):
            if not current_group:
                current_group = [tx]
                continue
            
            # Check if this transaction should be grouped with current group
            should_group = cls._should_group_transactions(current_group, tx)
            
            if should_group:
                current_group.append(tx)
            else:
                # Start new group
                if current_group:
                    groups.append(current_group)
                current_group = [tx]
        
        # Don't forget the last group
        if current_group:
            groups.append(current_group)
        
        return groups
    
    @classmethod
    def _should_group_transactions(cls, current_group: List[Dict], new_tx: Dict) -> bool:
        """Determine if a transaction should be grouped with existing transactions"""
        
        # Get the last transaction date in current group
        last_tx = current_group[-1]
        last_date = datetime.fromisoformat(last_tx.get('executed_at', ''))
        new_date = datetime.fromisoformat(new_tx.get('executed_at', ''))
        
        # Group if transactions are within same day or very close
        time_diff = abs((new_date - last_date).total_seconds())
        if time_diff <= 3600:  # Within 1 hour
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
    def _create_trade_from_transactions(cls, underlying: str, transactions: List[Dict]) -> Optional[Trade]:
        """Create a Trade object from a group of transactions"""
        
        if not transactions:
            return None
        
        # Generate trade ID
        first_tx = transactions[0]
        entry_date = datetime.fromisoformat(first_tx.get('executed_at', '')).date()
        trade_id = f"{underlying}_{entry_date.strftime('%Y%m%d')}_{len(transactions)}legs"
        
        # Create trade object
        trade = Trade(
            trade_id=trade_id,
            underlying=underlying,
            strategy_type=StrategyType.UNKNOWN,
            entry_date=entry_date
        )
        
        # Process each transaction into legs
        for tx in transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'EQUITY_OPTION' in instrument_type:
                cls._add_option_leg(trade, tx)
            elif 'EQUITY' in instrument_type and 'OPTION' not in instrument_type:
                cls._add_stock_leg(trade, tx)
        
        # Recognize the strategy
        trade.strategy_type = cls._recognize_strategy(trade)
        
        # Determine if trade is closed
        if cls._is_trade_closed(trade):
            trade.status = TradeStatus.CLOSED
            trade.exit_date = datetime.fromisoformat(transactions[-1].get('executed_at', '')).date()
        
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
        else:
            # This is an opening transaction - create new leg
            leg = OptionLeg(
                symbol=symbol,
                underlying=option_info['underlying'],
                option_type=option_info['option_type'],
                strike=option_info['strike'],
                expiration=option_info['expiration'],
                quantity=quantity,
                entry_price=entry_price,
                transaction_ids=[str(transaction.get('id', ''))]
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
        else:
            # This is an opening transaction - create new leg
            leg = StockLeg(
                symbol=transaction.get('symbol', ''),
                quantity=quantity,
                entry_price=entry_price,
                transaction_ids=[str(transaction.get('id', ''))]
            )
            
            trade.stock_legs.append(leg)
    
    @classmethod
    def _recognize_strategy(cls, trade: Trade) -> StrategyType:
        """Recognize the strategy type from the legs"""
        
        option_legs = trade.option_legs
        stock_legs = trade.stock_legs
        
        # Stock-only strategies
        if not option_legs and stock_legs:
            if len(stock_legs) == 1:
                return StrategyType.LONG_STOCK if stock_legs[0].quantity > 0 else StrategyType.SHORT_STOCK
        
        # Single option strategies
        if len(option_legs) == 1 and not stock_legs:
            leg = option_legs[0]
            if leg.is_short:
                return StrategyType.NAKED_CALL if leg.option_type == 'Call' else StrategyType.NAKED_PUT
        
        # Covered call
        if (len(option_legs) == 1 and len(stock_legs) == 1 and
            option_legs[0].is_short and option_legs[0].option_type == 'Call' and
            stock_legs[0].quantity > 0):
            return StrategyType.COVERED_CALL
        
        # Cash-secured put
        if (len(option_legs) == 1 and not stock_legs and
            option_legs[0].is_short and option_legs[0].option_type == 'Put'):
            return StrategyType.CASH_SECURED_PUT
        
        # Vertical spreads
        if len(option_legs) == 2 and not stock_legs:
            leg1, leg2 = option_legs
            if (leg1.option_type == leg2.option_type and 
                leg1.expiration == leg2.expiration and
                leg1.strike != leg2.strike):
                return StrategyType.VERTICAL_SPREAD
        
        # Straddle/Strangle
        if len(option_legs) == 2 and not stock_legs:
            leg1, leg2 = option_legs
            if (leg1.expiration == leg2.expiration and
                leg1.option_type != leg2.option_type):
                if leg1.strike == leg2.strike:
                    return StrategyType.STRADDLE
                else:
                    return StrategyType.STRANGLE
        
        # Iron Condor (4 legs: short strangle + long strangle)
        if len(option_legs) == 4 and not stock_legs:
            # Group by option type
            calls = [leg for leg in option_legs if leg.option_type == 'Call']
            puts = [leg for leg in option_legs if leg.option_type == 'Put']
            
            if len(calls) == 2 and len(puts) == 2:
                # Check if it forms an iron condor pattern
                calls.sort(key=lambda x: x.strike)
                puts.sort(key=lambda x: x.strike)
                
                if (calls[0].is_long and calls[1].is_short and 
                    puts[0].is_long and puts[1].is_short):
                    return StrategyType.IRON_CONDOR
        
        # Default for complex strategies
        if len(option_legs) > 2:
            return StrategyType.COMPLEX_STRATEGY
        
        return StrategyType.UNKNOWN
    
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
            'CLOSE'
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