"""
Enhanced Transaction Matching System for Trade Strategy Identification
Implements precedence-based strategy recognition with conflict resolution
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import logging

from .trade_strategy import StrategyType

logger = logging.getLogger(__name__)


class ConfidenceLevel(Enum):
    HIGH = "HIGH"           # Order ID match + logical consistency
    MEDIUM = "MEDIUM"       # Timing match + logical consistency  
    LOW = "LOW"             # Partial match or conflicts resolved by precedence


class QualityFlag(Enum):
    VERIFIED = "VERIFIED"           # All transactions match expected pattern
    ASSUMED = "ASSUMED"             # Missing order ID but timing/logic consistent
    CONFLICTED = "CONFLICTED"       # Resolved by precedence rules
    PARTIAL = "PARTIAL"             # Some transactions unmatched
    MANUAL_REVIEW = "MANUAL_REVIEW" # Requires human verification


@dataclass
class TransactionGroup:
    """Group of transactions that may form a strategy"""
    transactions: List[Dict]
    grouping_method: str  # 'order_id' or 'timing'
    group_key: str
    timestamps: List[datetime] = field(default_factory=list)
    
    @property
    def earliest_timestamp(self) -> datetime:
        return min(self.timestamps) if self.timestamps else datetime.now()
    
    @property
    def latest_timestamp(self) -> datetime:
        return max(self.timestamps) if self.timestamps else datetime.now()
    
    @property 
    def time_span(self) -> timedelta:
        return self.latest_timestamp - self.earliest_timestamp


@dataclass
class StrategyMatch:
    """Identified strategy with metadata"""
    strategy_type: StrategyType
    transactions: List[Dict]
    confidence: ConfidenceLevel
    quality_flags: List[QualityFlag]
    precedence_score: int
    group: TransactionGroup
    components: Dict[str, List[Dict]]  # 'options', 'stock', etc.
    

class TransactionMatcher:
    """Enhanced transaction matching system with precedence rules"""
    
    # Strategy precedence hierarchy (higher = takes priority)
    STRATEGY_PRECEDENCE = {
        StrategyType.IRON_CONDOR: 100,
        StrategyType.BROKEN_WING_BUTTERFLY: 95,
        StrategyType.IRON_BUTTERFLY: 90,
        StrategyType.BUTTERFLY: 85,
        StrategyType.BEAR_CALL_SPREAD: 80,
        StrategyType.BEAR_PUT_SPREAD: 80,
        StrategyType.BULL_CALL_SPREAD: 80,
        StrategyType.BULL_PUT_SPREAD: 80,
        StrategyType.VERTICAL_SPREAD: 80,
        StrategyType.STRADDLE: 75,
        StrategyType.STRANGLE: 75,
        StrategyType.CALL_ROLL: 75,
        StrategyType.PUT_ROLL: 75,
        StrategyType.CALENDAR_SPREAD: 70,
        StrategyType.DIAGONAL_SPREAD: 70,
        StrategyType.COVERED_CALL: 60,
        StrategyType.CASH_SECURED_PUT: 60,
        StrategyType.LONG_CALL: 10,
        StrategyType.LONG_PUT: 10,
        StrategyType.NAKED_CALL: 10,
        StrategyType.NAKED_PUT: 10,
        StrategyType.LONG_STOCK: 5,
        StrategyType.SHORT_STOCK: 5,
        StrategyType.UNKNOWN: 0
    }
    
    # Timing windows for different strategy types
    TIMING_WINDOWS = {
        'SAME_SECOND': timedelta(seconds=1),
        'SAME_MINUTE': timedelta(minutes=1),
        'RAPID_EXECUTION': timedelta(minutes=5),
        'SAME_SESSION': timedelta(hours=1),
        'SAME_DAY': timedelta(hours=24)
    }
    
    def __init__(self):
        self.existing_positions = {}  # Will be populated from database
        
    def match_transactions_to_strategies(
        self, 
        raw_transactions: List[Dict], 
        existing_positions: Dict[str, Dict] = None
    ) -> List[StrategyMatch]:
        """
        Complete procedure for matching transactions to strategies
        
        Args:
            raw_transactions: List of transaction dictionaries
            existing_positions: Dict of symbol -> {'stock': quantity, 'options': {...}}
            
        Returns:
            List of identified strategies with metadata
        """
        if existing_positions:
            self.existing_positions = existing_positions
            
        # Phase 1: Prepare data
        consolidated = self._consolidate_transactions(raw_transactions)
        order_groups, ungrouped = self._group_by_order_id(consolidated)
        timing_groups = self._group_by_timing(ungrouped)
        
        all_groups = list(order_groups.values()) + timing_groups
        
        # Phase 2: Detect strategies in each group
        potential_strategies = []
        for group in all_groups:
            if len(group.transactions) > 0:
                strategies = self._detect_strategies_in_group(group)
                potential_strategies.extend(strategies)
        
        # Phase 3: Match cross-order-ID closing transactions
        cross_order_matched = self._match_closing_transactions(potential_strategies)
        
        # Phase 4: Resolve conflicts
        resolved_strategies = self._resolve_conflicts(cross_order_matched)
        
        # Phase 5: Handle remaining single transactions
        unmatched = self._find_unmatched_transactions(raw_transactions, resolved_strategies)
        single_strategies = self._process_single_transactions(unmatched)
        
        # Phase 6: Link roll chains and update statuses
        all_strategies = resolved_strategies + single_strategies
        roll_linked_strategies = self._link_roll_chains(all_strategies)
        
        # Phase 7: Final validation
        validated_strategies = self._validate_strategies(roll_linked_strategies)
        
        return validated_strategies
    
    def _consolidate_transactions(self, raw_transactions: List[Dict]) -> List[Dict]:
        """
        Combine partial fills into logical transaction groups
        Preserves timing information for analysis
        """
        consolidated = {}
        
        for txn in raw_transactions:
            # Create consolidation key
            key = (
                txn.get('symbol', ''),
                txn.get('executed_at', '')[:10],  # Date only
                txn.get('action', ''),
                txn.get('strike'),  # None for stocks
                txn.get('option_type'),  # None for stocks  
                txn.get('order_id', '')
            )
            
            if key in consolidated:
                # Aggregate quantities
                current_qty = consolidated[key].get('quantity') or 0
                txn_qty = txn.get('quantity') or 0
                consolidated[key]['quantity'] = current_qty + txn_qty
                consolidated[key]['timestamps'].append(txn.get('executed_at', ''))
                consolidated[key]['ids'].append(txn.get('id', ''))
            else:
                # Create new consolidated transaction
                consolidated[key] = txn.copy()
                consolidated[key]['quantity'] = txn.get('quantity') or 0
                consolidated[key]['timestamps'] = [txn.get('executed_at', '')]
                consolidated[key]['ids'] = [txn.get('id', '')]
                
        return list(consolidated.values())
    
    def _group_by_order_id(self, transactions: List[Dict]) -> Tuple[Dict[str, TransactionGroup], List[Dict]]:
        """Group transactions with matching order/group identifiers"""
        groups = {}
        ungrouped = []
        
        for txn in transactions:
            order_id = str(txn.get('order_id', '') or '').strip()
            if order_id and order_id != '':
                if order_id not in groups:
                    groups[order_id] = TransactionGroup(
                        transactions=[],
                        grouping_method='order_id',
                        group_key=order_id
                    )
                groups[order_id].transactions.append(txn)
                # Add all timestamps from this transaction
                for ts in txn.get('timestamps', [txn.get('executed_at')]):
                    if ts:
                        groups[order_id].timestamps.append(
                            datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        )
            else:
                ungrouped.append(txn)
                
        return groups, ungrouped
    
    def _group_by_timing(self, ungrouped_transactions: List[Dict]) -> List[TransactionGroup]:
        """Group remaining transactions by timing windows"""
        if not ungrouped_transactions:
            return []
            
        # Sort by timestamp
        sorted_txns = sorted(
            ungrouped_transactions, 
            key=lambda x: x.get('executed_at', '')
        )
        
        timing_groups = []
        current_group = None
        
        for txn in sorted_txns:
            txn_time = datetime.fromisoformat(
                txn.get('executed_at', '').replace('Z', '+00:00')
            )
            
            if not current_group:
                current_group = TransactionGroup(
                    transactions=[txn],
                    grouping_method='timing',
                    group_key=f"timing_{txn_time.isoformat()}"
                )
                current_group.timestamps.append(txn_time)
            else:
                # Check if transaction is within timing window
                time_diff = txn_time - current_group.latest_timestamp
                symbol_match = (txn.get('underlying_symbol', txn.get('symbol', '')) == 
                              current_group.transactions[0].get('underlying_symbol', 
                              current_group.transactions[0].get('symbol', '')))
                
                # Determine appropriate timing window
                window = self._determine_timing_window(current_group.transactions, txn)
                
                if symbol_match and time_diff <= window:
                    current_group.transactions.append(txn)
                    current_group.timestamps.append(txn_time)
                else:
                    timing_groups.append(current_group)
                    current_group = TransactionGroup(
                        transactions=[txn],
                        grouping_method='timing',
                        group_key=f"timing_{txn_time.isoformat()}"
                    )
                    current_group.timestamps.append(txn_time)
        
        if current_group:
            timing_groups.append(current_group)
            
        return timing_groups
    
    def _determine_timing_window(self, existing_transactions: List[Dict], new_transaction: Dict) -> timedelta:
        """Dynamically determine appropriate timing window based on transaction types"""
        # Check if we're building a complex multi-leg strategy
        has_options = any('OPTION' in str(t.get('instrument_type', '')) for t in existing_transactions)
        new_is_option = 'OPTION' in str(new_transaction.get('instrument_type', ''))
        
        if has_options and new_is_option:
            # Count different strikes/expirations
            unique_strikes = set()
            unique_expirations = set()
            
            for txn in existing_transactions + [new_transaction]:
                if 'OPTION' in str(txn.get('instrument_type', '')):
                    # Parse option symbol to get strike/expiration
                    symbol = txn.get('symbol', '')
                    parts = symbol.split()
                    if len(parts) >= 2:
                        unique_expirations.add(parts[1][:6])  # YYMMDD
                        # Extract strike from symbol
                        if len(parts[1]) > 6:
                            strike_part = parts[1][6:]
                            if strike_part[-4:].isdigit():
                                unique_strikes.add(strike_part)
            
            # If different expirations, be very strict - likely separate trades
            if len(unique_expirations) > 1:
                return self.TIMING_WINDOWS['SAME_SECOND']  # Extremely tight
            # Complex strategies (4+ legs) need tight timing
            elif len(existing_transactions) >= 3:
                return self.TIMING_WINDOWS['RAPID_EXECUTION']
            # Multi-strike strategies need moderate timing
            elif len(unique_strikes) > 1:
                return self.TIMING_WINDOWS['SAME_MINUTE']
            # Simple strategies can have longer windows
            else:
                return self.TIMING_WINDOWS['SAME_SESSION']
        
        # Stock + option combinations (potential covered calls/puts)
        elif has_options != new_is_option:
            # Don't group stock with options based on timing alone
            # Covered calls can happen any time
            return self.TIMING_WINDOWS['SAME_SECOND']  # Very tight window
            
        # Stock-only transactions
        else:
            return self.TIMING_WINDOWS['SAME_DAY']
    
    def _detect_strategies_in_group(self, group: TransactionGroup) -> List[StrategyMatch]:
        """Identify all possible strategies within a transaction group"""
        strategies = []
        
        # Separate by instrument type
        options_txns = [t for t in group.transactions 
                       if 'OPTION' in str(t.get('instrument_type', ''))]
        stock_txns = [t for t in group.transactions 
                     if t.get('instrument_type', '') == 'Equity']
        
        # Try to identify option strategies first (higher precedence)
        if options_txns:
            option_strategies = self._identify_option_strategies(options_txns, group)
            strategies.extend(option_strategies)
        
        # Then check for stock+option combinations
        if stock_txns and options_txns:
            combo_strategies = self._identify_stock_option_combos(
                stock_txns, options_txns, group
            )
            strategies.extend(combo_strategies)
        
        # Finally, simple stock positions
        if stock_txns and not options_txns:
            stock_strategies = self._identify_stock_strategies(stock_txns, group)
            strategies.extend(stock_strategies)
            
        return strategies
        
    def _identify_option_strategies(self, options_txns: List[Dict], group: TransactionGroup) -> List[StrategyMatch]:
        """Identify option-only strategies"""
        strategies = []
        
        # Parse option details for analysis
        option_details = []
        for txn in options_txns:
            symbol = txn.get('symbol', '')
            # Parse option symbol (e.g., "AAPL  250117C00200000")
            parts = symbol.split()
            if len(parts) >= 2:
                underlying = parts[0]
                option_code = parts[1]
                
                # Extract components from option code
                if len(option_code) >= 7:
                    expiration = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[7:] if len(option_code) > 7 else '0'
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    option_details.append({
                        'transaction': txn,
                        'underlying': underlying,
                        'expiration': expiration,
                        'option_type': option_type,
                        'strike': strike,
                        'action': txn.get('action', ''),
                        'quantity': txn.get('quantity', 0)
                    })
        
        # Sort by strike for easier pattern matching
        option_details.sort(key=lambda x: (x['expiration'], x['strike'], x['option_type']))
        
        # Identify based on number of legs
        if len(option_details) == 1:
            strategy = self._identify_single_option(option_details[0], group)
            if strategy:
                strategies.append(strategy)
                
        elif len(option_details) == 2:
            strategy = self._identify_two_option_strategy(option_details, group)
            if strategy:
                strategies.append(strategy)
                
        elif len(option_details) == 3:
            strategy = self._identify_three_option_strategy(option_details, group)
            if strategy:
                strategies.append(strategy)
                
        elif len(option_details) == 4:
            strategy = self._identify_four_option_strategy(option_details, group)
            if strategy:
                strategies.append(strategy)
                
        elif len(option_details) > 4:
            # Complex multi-leg strategy
            strategy = StrategyMatch(
                strategy_type=StrategyType.COMPLEX_STRATEGY,
                transactions=options_txns,
                confidence=ConfidenceLevel.LOW,
                quality_flags=[QualityFlag.MANUAL_REVIEW],
                precedence_score=self.STRATEGY_PRECEDENCE.get(StrategyType.COMPLEX_STRATEGY, 0),
                group=group,
                components={'options': options_txns}
            )
            strategies.append(strategy)
            
        return strategies
    
    def _identify_single_option(self, option_detail: Dict, group: TransactionGroup) -> Optional[StrategyMatch]:
        """Identify single option strategies"""
        txn = option_detail['transaction']
        action = option_detail['action']
        
        # Determine if long or short
        is_long = 'BUY' in action and 'OPEN' in action
        is_short = 'SELL' in action and 'OPEN' in action
        
        if is_long:
            strategy_type = (StrategyType.LONG_CALL if option_detail['option_type'] == 'Call' 
                           else StrategyType.LONG_PUT)
        elif is_short:
            # Check if this could be a covered call or cash-secured put
            underlying = option_detail['underlying']
            if option_detail['option_type'] == 'Call':
                # Check existing stock position for covered call
                stock_position = self.existing_positions.get(underlying, {}).get('stock', 0)
                contracts = abs(option_detail['quantity'])
                shares_needed = contracts * 100
                
                if stock_position >= shares_needed:
                    strategy_type = StrategyType.COVERED_CALL
                else:
                    strategy_type = StrategyType.NAKED_CALL
            else:  # Put
                strategy_type = StrategyType.CASH_SECURED_PUT
        else:
            return None
            
        confidence = (ConfidenceLevel.HIGH if group.grouping_method == 'order_id' 
                     else ConfidenceLevel.MEDIUM)
        
        return StrategyMatch(
            strategy_type=strategy_type,
            transactions=[txn],
            confidence=confidence,
            quality_flags=[QualityFlag.VERIFIED],
            precedence_score=self.STRATEGY_PRECEDENCE.get(strategy_type, 0),
            group=group,
            components={'options': [txn]}
        )
    
    def _identify_two_option_strategy(self, option_details: List[Dict], group: TransactionGroup) -> Optional[StrategyMatch]:
        """Identify two-option strategies (spreads, straddles, strangles)"""
        opt1, opt2 = option_details
        
        # Same expiration strategies
        if opt1['expiration'] == opt2['expiration']:
            # Same option type = Vertical Spread
            if opt1['option_type'] == opt2['option_type']:
                # Determine spread type based on actions
                if self._is_long(opt1) and self._is_short(opt2):
                    if opt1['option_type'] == 'Call':
                        strategy_type = StrategyType.BULL_CALL_SPREAD
                    else:
                        strategy_type = StrategyType.BULL_PUT_SPREAD
                elif self._is_short(opt1) and self._is_long(opt2):
                    if opt1['option_type'] == 'Call':
                        strategy_type = StrategyType.BEAR_CALL_SPREAD
                    else:
                        strategy_type = StrategyType.BEAR_PUT_SPREAD
                else:
                    strategy_type = StrategyType.VERTICAL_SPREAD
            
            # Different option types
            else:
                if opt1['strike'] == opt2['strike']:
                    # Same strike = Straddle
                    strategy_type = StrategyType.STRADDLE
                else:
                    # Different strikes = Strangle
                    strategy_type = StrategyType.STRANGLE
        
        # Different expirations
        else:
            # Check for ROLL pattern first (closing one position, opening another)
            if (opt1['option_type'] == opt2['option_type'] and 
                self._is_closing(opt1) and self._is_opening(opt2)):
                # Closing one position and opening another = ROLL
                if opt1['option_type'] == 'Call':
                    strategy_type = StrategyType.CALL_ROLL
                else:
                    strategy_type = StrategyType.PUT_ROLL
            elif (opt1['option_type'] == opt2['option_type'] and 
                  self._is_opening(opt1) and self._is_closing(opt2)):
                # Opening one position and closing another = ROLL (reverse order)
                if opt1['option_type'] == 'Call':
                    strategy_type = StrategyType.CALL_ROLL
                else:
                    strategy_type = StrategyType.PUT_ROLL
            elif opt1['strike'] == opt2['strike'] and opt1['option_type'] == opt2['option_type']:
                # Same strike and type = Calendar Spread
                strategy_type = StrategyType.CALENDAR_SPREAD
            else:
                # Different strikes = Diagonal Spread
                strategy_type = StrategyType.DIAGONAL_SPREAD
        
        confidence = (ConfidenceLevel.HIGH if group.grouping_method == 'order_id' 
                     else ConfidenceLevel.MEDIUM)
        
        return StrategyMatch(
            strategy_type=strategy_type,
            transactions=[opt1['transaction'], opt2['transaction']],
            confidence=confidence,
            quality_flags=[QualityFlag.VERIFIED],
            precedence_score=self.STRATEGY_PRECEDENCE.get(strategy_type, 0),
            group=group,
            components={'options': [opt1['transaction'], opt2['transaction']]}
        )
    
    def _identify_four_option_strategy(self, option_details: List[Dict], group: TransactionGroup) -> Optional[StrategyMatch]:
        """Identify four-option strategies (Iron Condor, Iron Butterfly, Double-leg Rolls)"""
        # Check for double-leg roll first (2 closing + 2 opening transactions)
        closing_txns = [opt for opt in option_details if self._is_closing(opt)]
        opening_txns = [opt for opt in option_details if self._is_opening(opt)]
        
        if len(closing_txns) == 2 and len(opening_txns) == 2:
            # Check if it's a spread roll (same option types on each side)
            closing_types = set(opt['option_type'] for opt in closing_txns)
            opening_types = set(opt['option_type'] for opt in opening_txns)
            
            # Double-leg roll: closing and opening same types
            if closing_types == opening_types:
                if len(closing_types) == 1:
                    # Single option type roll (e.g., rolling a vertical spread)
                    option_type = list(closing_types)[0]
                    if option_type == 'Call':
                        strategy_type = StrategyType.CALL_ROLL
                    else:
                        strategy_type = StrategyType.PUT_ROLL
                elif len(closing_types) == 2:
                    # Both calls and puts being rolled (e.g., rolling an Iron Condor)
                    # For now, classify as the more generic "Complex Strategy" 
                    # Could add specific Iron Condor Roll type later
                    strategy_type = StrategyType.COMPLEX_STRATEGY
                else:
                    strategy_type = StrategyType.COMPLEX_STRATEGY
            else:
                # Mixed closing/opening different types - complex strategy
                strategy_type = StrategyType.COMPLEX_STRATEGY
        else:
            # Not a roll pattern, check for standard 4-leg strategies
            # Separate by option type
            calls = [opt for opt in option_details if opt['option_type'] == 'Call']
            puts = [opt for opt in option_details if opt['option_type'] == 'Put']
            
            # Check if all same expiration
            expirations = set(opt['expiration'] for opt in option_details)
            if len(expirations) == 1 and len(calls) == 2 and len(puts) == 2:
                # Get unique strikes
                all_strikes = sorted(set(opt['strike'] for opt in option_details))
                
                if len(all_strikes) == 3:
                    # Iron Butterfly: 3 unique strikes
                    strategy_type = StrategyType.IRON_BUTTERFLY
                elif len(all_strikes) == 4:
                    # Iron Condor: 4 unique strikes
                    strategy_type = StrategyType.IRON_CONDOR
                else:
                    strategy_type = StrategyType.COMPLEX_STRATEGY
            else:
                strategy_type = StrategyType.COMPLEX_STRATEGY
            
        # Calculate confidence based on grouping method and strategy type
        if group.grouping_method == 'order_id':
            confidence = ConfidenceLevel.HIGH
        elif 'ROLL' in strategy_type.value:
            confidence = ConfidenceLevel.MEDIUM  # Rolls without order ID are less certain
        else:
            expirations = set(opt['expiration'] for opt in option_details)
            confidence = (ConfidenceLevel.MEDIUM if len(expirations) == 1
                         else ConfidenceLevel.LOW)
        
        quality_flags = ([QualityFlag.VERIFIED] if confidence == ConfidenceLevel.HIGH
                        else [QualityFlag.ASSUMED])
        
        return StrategyMatch(
            strategy_type=strategy_type,
            transactions=[opt['transaction'] for opt in option_details],
            confidence=confidence,
            quality_flags=quality_flags,
            precedence_score=self.STRATEGY_PRECEDENCE.get(strategy_type, 0),
            group=group,
            components={'options': [opt['transaction'] for opt in option_details]}
        )
    
    def _identify_stock_option_combos(self, stock_txns: List[Dict], options_txns: List[Dict], 
                                    group: TransactionGroup) -> List[StrategyMatch]:
        """Identify stock + option combination strategies"""
        strategies = []
        
        # For covered calls, timing doesn't matter - only position
        # But we still check if they're in the same group for other strategies
        
        for option_txn in options_txns:
            # Parse option details
            symbol = option_txn.get('symbol', '')
            parts = symbol.split()
            if len(parts) < 2:
                continue
                
            option_code = parts[1]
            option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
            
            # Check for covered call (short call + stock position)
            if (option_type == 'Call' and 
                'SELL' in option_txn.get('action', '') and 
                'OPEN' in option_txn.get('action', '')):
                
                underlying = option_txn.get('underlying_symbol', '')
                stock_position = self.existing_positions.get(underlying, {}).get('stock', 0)
                contracts = abs(option_txn.get('quantity', 0))
                shares_needed = contracts * 100
                
                if stock_position >= shares_needed:
                    # This is a covered call
                    strategy = StrategyMatch(
                        strategy_type=StrategyType.COVERED_CALL,
                        transactions=[option_txn],  # Only the option leg
                        confidence=ConfidenceLevel.HIGH,
                        quality_flags=[QualityFlag.VERIFIED],
                        precedence_score=self.STRATEGY_PRECEDENCE[StrategyType.COVERED_CALL],
                        group=group,
                        components={'options': [option_txn], 'stock_context': stock_position}
                    )
                    strategies.append(strategy)
        
        return strategies
    
    def _is_long(self, option_detail: Dict) -> bool:
        """Check if option position is long"""
        action = str(option_detail.get('action', '') or '')
        return 'BUY' in action and 'OPEN' in action
    
    def _is_short(self, option_detail: Dict) -> bool:
        """Check if option position is short"""  
        action = str(option_detail.get('action', '') or '')
        return 'SELL' in action and 'OPEN' in action
    
    def _is_closing(self, option_detail: Dict) -> bool:
        """Check if this is a closing transaction"""
        action = str(option_detail.get('action', '') or '')
        return 'CLOSE' in action
    
    def _is_opening(self, option_detail: Dict) -> bool:
        """Check if this is an opening transaction"""
        action = str(option_detail.get('action', '') or '')
        return 'OPEN' in action
    
    def _identify_three_option_strategy(self, option_details: List[Dict], group: TransactionGroup) -> Optional[StrategyMatch]:
        """Identify three-option strategies (butterflies, broken wing butterflies)"""
        # Check if all same expiration and option type
        expirations = set(opt['expiration'] for opt in option_details)
        option_types = set(opt['option_type'] for opt in option_details)
        
        if len(expirations) == 1 and len(option_types) == 1:
            # Sort by strike
            sorted_opts = sorted(option_details, key=lambda x: x['strike'])
            
            # Check for butterfly pattern
            if len(set(opt['strike'] for opt in sorted_opts)) == 3:
                # Classic butterfly: long-short-short-long pattern
                strategy_type = StrategyType.BUTTERFLY
            else:
                strategy_type = StrategyType.COMPLEX_STRATEGY
        else:
            strategy_type = StrategyType.COMPLEX_STRATEGY
            
        confidence = (ConfidenceLevel.HIGH if group.grouping_method == 'order_id'
                     else ConfidenceLevel.MEDIUM)
        
        return StrategyMatch(
            strategy_type=strategy_type,
            transactions=[opt['transaction'] for opt in option_details],
            confidence=confidence,
            quality_flags=[QualityFlag.ASSUMED],
            precedence_score=self.STRATEGY_PRECEDENCE.get(strategy_type, 0),
            group=group,
            components={'options': [opt['transaction'] for opt in option_details]}
        )
    
    def _identify_stock_strategies(self, stock_txns: List[Dict], group: TransactionGroup) -> List[StrategyMatch]:
        """Identify stock-only strategies"""
        strategies = []
        
        # Consolidate stock transactions
        net_quantity = sum(txn.get('quantity', 0) for txn in stock_txns)
        
        if net_quantity > 0:
            strategy_type = StrategyType.LONG_STOCK
        elif net_quantity < 0:
            strategy_type = StrategyType.SHORT_STOCK
        else:
            # Net zero position - likely a completed trade
            return strategies
            
        strategy = StrategyMatch(
            strategy_type=strategy_type,
            transactions=stock_txns,
            confidence=ConfidenceLevel.HIGH,
            quality_flags=[QualityFlag.VERIFIED],
            precedence_score=self.STRATEGY_PRECEDENCE.get(strategy_type, 0),
            group=group,
            components={'stock': stock_txns}
        )
        strategies.append(strategy)
        
        return strategies
    
    def _resolve_conflicts(self, potential_strategies: List[StrategyMatch]) -> List[StrategyMatch]:
        """Apply precedence rules to resolve conflicts between overlapping strategies"""
        if not potential_strategies:
            return []
            
        # Find overlapping transactions
        transaction_to_strategies = defaultdict(list)
        for i, strategy in enumerate(potential_strategies):
            for txn in strategy.transactions:
                txn_id = txn.get('id', '')
                if txn_id:
                    transaction_to_strategies[txn_id].append(i)
        
        # Identify conflicts (transactions claimed by multiple strategies)
        conflicts = []
        for txn_id, strategy_indices in transaction_to_strategies.items():
            if len(strategy_indices) > 1:
                conflicts.append({
                    'transaction_id': txn_id,
                    'strategy_indices': strategy_indices
                })
        
        # Resolve conflicts by precedence
        strategies_to_keep = set(range(len(potential_strategies)))
        
        for conflict in conflicts:
            competing_indices = conflict['strategy_indices']
            competing_strategies = [potential_strategies[i] for i in competing_indices]
            
            # Rule 1: Higher precedence wins
            best_strategy_idx = max(competing_indices, 
                                  key=lambda i: potential_strategies[i].precedence_score)
            
            # Rule 2: If tied, strategy with more legs wins
            tied_strategies = [i for i in competing_indices 
                             if potential_strategies[i].precedence_score == 
                                potential_strategies[best_strategy_idx].precedence_score]
            
            if len(tied_strategies) > 1:
                best_strategy_idx = max(tied_strategies,
                                      key=lambda i: len(potential_strategies[i].transactions))
            
            # Rule 3: If still tied, more recent wins
            if len([i for i in tied_strategies 
                   if len(potential_strategies[i].transactions) == 
                      len(potential_strategies[best_strategy_idx].transactions)]) > 1:
                best_strategy_idx = max(tied_strategies,
                                      key=lambda i: potential_strategies[i].group.latest_timestamp)
            
            # Mark losing strategies
            for idx in competing_indices:
                if idx != best_strategy_idx:
                    strategies_to_keep.discard(idx)
                    # Add conflict flag to the winning strategy
                    potential_strategies[best_strategy_idx].quality_flags.append(
                        QualityFlag.CONFLICTED
                    )
        
        # Return only non-conflicted strategies
        resolved_strategies = [potential_strategies[i] for i in sorted(strategies_to_keep)]
        
        return resolved_strategies
    
    def _find_unmatched_transactions(self, raw_transactions: List[Dict], 
                                    matched_strategies: List[StrategyMatch]) -> List[Dict]:
        """Find transactions not included in any matched strategy"""
        matched_ids = set()
        for strategy in matched_strategies:
            for txn in strategy.transactions:
                # Handle both individual IDs and consolidated ID lists
                if 'ids' in txn:
                    matched_ids.update(txn['ids'])
                else:
                    matched_ids.add(txn.get('id', ''))
        
        unmatched = []
        for txn in raw_transactions:
            if txn.get('id', '') not in matched_ids:
                unmatched.append(txn)
                
        return unmatched
    
    def _process_single_transactions(self, unmatched_transactions: List[Dict]) -> List[StrategyMatch]:
        """Process remaining single transactions"""
        strategies = []
        
        for txn in unmatched_transactions:
            # Create single-transaction group
            group = TransactionGroup(
                transactions=[txn],
                grouping_method='single',
                group_key=f"single_{txn.get('id', '')}"
            )
            
            if txn.get('executed_at'):
                group.timestamps.append(
                    datetime.fromisoformat(txn.get('executed_at', '').replace('Z', '+00:00'))
                )
            
            # Identify strategy
            instrument_type = str(txn.get('instrument_type', ''))
            
            if 'OPTION' in instrument_type:
                option_strategies = self._identify_option_strategies([txn], group)
                strategies.extend(option_strategies)
            elif instrument_type == 'Equity':
                stock_strategies = self._identify_stock_strategies([txn], group)
                strategies.extend(stock_strategies)
                
        return strategies
    
    def _validate_strategies(self, strategies: List[StrategyMatch]) -> List[StrategyMatch]:
        """Final validation of identified strategies"""
        validated = []
        
        for strategy in strategies:
            # Validate quantities
            if self._validate_quantities(strategy):
                # Validate logical consistency
                if self._validate_logic(strategy):
                    # Validate timing
                    if self._validate_timing(strategy):
                        validated.append(strategy)
                    else:
                        strategy.quality_flags.append(QualityFlag.MANUAL_REVIEW)
                        strategy.confidence = ConfidenceLevel.LOW
                        validated.append(strategy)
                else:
                    logger.warning(f"Logic validation failed for {strategy.strategy_type}")
                    strategy.quality_flags.append(QualityFlag.MANUAL_REVIEW)
                    strategy.confidence = ConfidenceLevel.LOW
                    validated.append(strategy)
            else:
                logger.warning(f"Quantity validation failed for {strategy.strategy_type}")
                strategy.quality_flags.append(QualityFlag.MANUAL_REVIEW)
                strategy.confidence = ConfidenceLevel.LOW
                validated.append(strategy)
                
        return validated
    
    def _validate_quantities(self, strategy: StrategyMatch) -> bool:
        """Validate quantity consistency for the strategy"""
        if strategy.strategy_type == StrategyType.IRON_CONDOR:
            # All legs should have same absolute quantity
            quantities = [abs(txn.get('quantity', 0)) for txn in strategy.transactions]
            return len(set(quantities)) == 1
            
        elif strategy.strategy_type in [StrategyType.VERTICAL_SPREAD, 
                                       StrategyType.BULL_CALL_SPREAD,
                                       StrategyType.BEAR_PUT_SPREAD]:
            # Two legs with equal quantities
            if len(strategy.transactions) == 2:
                q1 = abs(strategy.transactions[0].get('quantity', 0))
                q2 = abs(strategy.transactions[1].get('quantity', 0))
                return q1 == q2
                
        return True  # Default to valid
    
    def _validate_logic(self, strategy: StrategyMatch) -> bool:
        """Validate logical consistency of the strategy"""
        if strategy.strategy_type == StrategyType.COVERED_CALL:
            # Already validated during identification
            return True
            
        elif strategy.strategy_type == StrategyType.IRON_CONDOR:
            # Should have 4 legs, 2 calls and 2 puts
            options = strategy.components.get('options', [])
            if len(options) != 4:
                return False
            # Additional iron condor validation...
            
        return True  # Default to valid
    
    def _validate_timing(self, strategy: StrategyMatch) -> bool:
        """Validate timing consistency"""
        if strategy.group.grouping_method == 'order_id':
            # Order ID grouping is always valid
            return True
            
        # Check if timing span is reasonable for the strategy type
        time_span = strategy.group.time_span
        
        if strategy.strategy_type in [StrategyType.IRON_CONDOR, StrategyType.IRON_BUTTERFLY]:
            # Complex strategies should execute quickly
            return time_span <= self.TIMING_WINDOWS['RAPID_EXECUTION']
            
        elif strategy.strategy_type in [StrategyType.VERTICAL_SPREAD, StrategyType.BULL_CALL_SPREAD]:
            # Simple spreads can have moderate timing
            return time_span <= self.TIMING_WINDOWS['SAME_SESSION']
            
        return True  # Default to valid
    
    def _match_closing_transactions(self, potential_strategies: List[StrategyMatch]) -> List[StrategyMatch]:
        """
        Match orphaned closing transactions to their opening trades across different order IDs
        
        This handles cases where closing transactions have different order IDs than opening transactions
        but represent the closing of the same position (e.g., AFRM Bull Put Spread case)
        """
        if not potential_strategies:
            return potential_strategies
        
        # Separate strategies into open positions and potential closings
        open_strategies = []
        closing_strategies = []
        
        for strategy in potential_strategies:
            if self._is_orphaned_closing_strategy(strategy):
                closing_strategies.append(strategy)
            else:
                open_strategies.append(strategy)
        
        # Try to match each closing strategy to an open strategy
        matched_strategies = []
        unmatched_closings = []
        
        for closing_strategy in closing_strategies:
            best_match = None
            best_score = 0.0
            
            for open_strategy in open_strategies:
                score = self._calculate_closing_match_score(open_strategy, closing_strategy)
                if score > best_score and score >= 0.9:  # 90% confidence threshold
                    best_score = score
                    best_match = open_strategy
            
            if best_match:
                # Merge the closing strategy into the opening strategy
                merged_strategy = self._merge_closing_strategy(best_match, closing_strategy)
                matched_strategies.append(merged_strategy)
                
                # Remove the matched opening strategy from future matching
                if best_match in open_strategies:
                    open_strategies.remove(best_match)
            else:
                # Keep orphaned closing as-is (might be a standalone trade)
                unmatched_closings.append(closing_strategy)
        
        # Return all unmatched open strategies + matched strategies + unmatched closings
        return open_strategies + matched_strategies + unmatched_closings
    
    def _is_orphaned_closing_strategy(self, strategy: StrategyMatch) -> bool:
        """
        Check if this strategy looks like an orphaned closing transaction
        (same-day entry/exit with only closing actions)
        """
        # Check if all transactions are closing actions
        all_closing = True
        for tx in strategy.transactions:
            action = tx.get('action', '')
            if not any(closing_action in str(action) for closing_action in ['BTC', 'STC', 'CLOSE']):
                all_closing = False
                break
        
        if not all_closing:
            return False
        
        # Check if it's same-day entry/exit (likely orphaned closing)
        group = strategy.group
        if hasattr(group, 'time_span') and group.time_span.total_seconds() < 86400:  # Same day
            return True
        
        # Alternative check: Look at timestamps directly
        timestamps = []
        for tx in strategy.transactions:
            if tx.get('executed_at'):
                timestamps.append(tx.get('executed_at'))
        
        if len(timestamps) > 0:
            dates = set(ts[:10] for ts in timestamps)  # Extract dates
            if len(dates) == 1:  # All on same date
                return True
        
        return False
    
    def _calculate_closing_match_score(self, open_strategy: StrategyMatch, closing_strategy: StrategyMatch) -> float:
        """
        Calculate how well a closing strategy matches an opening strategy
        """
        # Must be same underlying
        open_underlying = self._get_strategy_underlying(open_strategy)
        closing_underlying = self._get_strategy_underlying(closing_strategy)
        
        if open_underlying != closing_underlying:
            return 0.0
        
        # Get option positions from each strategy
        open_positions = self._extract_option_positions(open_strategy)
        closing_positions = self._extract_option_positions(closing_strategy)
        
        if len(open_positions) != len(closing_positions):
            return 0.0
        
        # Calculate match score based on strike/expiration/type matching
        matches = 0
        total = len(open_positions)
        
        for open_pos in open_positions:
            for closing_pos in closing_positions:
                if (open_pos['strike'] == closing_pos['strike'] and
                    open_pos['expiration'] == closing_pos['expiration'] and
                    open_pos['option_type'] == closing_pos['option_type']):
                    
                    # Check if quantities are opposite (closing should reverse opening)
                    open_qty = open_pos['quantity']
                    closing_qty = closing_pos['quantity']
                    
                    if abs(open_qty) == abs(closing_qty) and (open_qty * closing_qty) < 0:
                        matches += 1
                        break
        
        return matches / total if total > 0 else 0.0
    
    def _get_strategy_underlying(self, strategy: StrategyMatch) -> str:
        """Get the underlying symbol from a strategy"""
        if strategy.transactions:
            return strategy.transactions[0].get('underlying_symbol', '')
        return ''
    
    def _extract_option_positions(self, strategy: StrategyMatch) -> List[Dict]:
        """Extract option positions from a strategy"""
        positions = []
        
        for tx in strategy.transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'OPTION' in instrument_type:
                # Parse option symbol
                symbol = tx.get('symbol', '')
                # Basic parsing - could be enhanced
                if ' ' in symbol:
                    parts = symbol.split()
                    if len(parts) >= 2:
                        option_code = parts[1]
                        if len(option_code) >= 7:
                            expiration = option_code[:6]  # YYMMDD
                            option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                            strike_str = option_code[7:] if len(option_code) > 7 else '0'
                            strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                            
                            # Apply proper quantity sign based on action
                            quantity = int(tx.get('quantity', 0))
                            action_str = str(tx.get('action', ''))
                            if 'SELL' in action_str:
                                quantity = -abs(quantity)  # Short position
                            
                            positions.append({
                                'strike': strike,
                                'expiration': expiration,
                                'option_type': option_type,
                                'quantity': quantity
                            })
        
        return positions
    
    def _merge_closing_strategy(self, open_strategy: StrategyMatch, closing_strategy: StrategyMatch) -> StrategyMatch:
        """
        Merge a closing strategy into an opening strategy to create a complete closed trade
        """
        # Create new strategy with combined transactions
        combined_transactions = open_strategy.transactions + closing_strategy.transactions
        
        # Update the group to include closing transactions
        combined_group = TransactionGroup(
            transactions=combined_transactions,
            grouping_method='cross_order_matched',
            group_key=f"{open_strategy.group.group_key}_merged_{closing_strategy.group.group_key}"
        )
        
        # Add timestamps from both groups
        if hasattr(open_strategy.group, 'timestamps'):
            combined_group.timestamps.extend(open_strategy.group.timestamps)
        if hasattr(closing_strategy.group, 'timestamps'):
            combined_group.timestamps.extend(closing_strategy.group.timestamps)
        
        # Create merged strategy
        merged_strategy = StrategyMatch(
            strategy_type=open_strategy.strategy_type,  # Keep original strategy type
            transactions=combined_transactions,
            confidence=ConfidenceLevel.HIGH,  # High confidence for matched closing
            quality_flags=[QualityFlag.VERIFIED],
            precedence_score=open_strategy.precedence_score,
            group=combined_group,
            components=open_strategy.components  # Keep original components
        )
        
        return merged_strategy
    
    def _link_roll_chains(self, strategies: List[StrategyMatch]) -> List[StrategyMatch]:
        """
        Link roll chains and update trade statuses based on position closure/opening logic
        
        This identifies when a roll closes a previous position and opens a new one,
        updating the statuses accordingly (previous trade -> ROLLED, roll -> OPEN)
        """
        if len(strategies) < 2:
            return strategies
        
        # Group strategies by underlying symbol for roll chain analysis
        by_underlying = defaultdict(list)
        for strategy in strategies:
            underlying = self._get_strategy_underlying(strategy)
            if underlying:
                by_underlying[underlying].append(strategy)
        
        updated_strategies = []
        
        for underlying, underlying_strategies in by_underlying.items():
            if len(underlying_strategies) < 2:
                updated_strategies.extend(underlying_strategies)
                continue
            
            # Sort by earliest transaction timestamp (chronological order)
            underlying_strategies.sort(key=lambda s: s.group.earliest_timestamp)
            
            # Identify and link roll chains
            roll_linked = self._process_roll_chains_for_underlying(underlying_strategies)
            updated_strategies.extend(roll_linked)
        
        return updated_strategies
    
    def _process_roll_chains_for_underlying(self, strategies: List[StrategyMatch]) -> List[StrategyMatch]:
        """Process roll chains for a single underlying symbol"""
        # Create a working copy that we can modify
        working_strategies = strategies.copy()
        
        # First pass: Handle roll strategies that open new positions (regardless of chain relationships)
        for i in range(len(working_strategies)):
            strategy = working_strategies[i]
            
            # If this is a roll strategy, check if it opens new positions
            if 'ROLL' in strategy.strategy_type.value.upper():
                if self._roll_opens_new_position(strategy):
                    # Mark as open since it contains opening transactions
                    working_strategies[i] = self._mark_strategy_as_open(strategy)
                else:
                    # Mark as closed since it only contains closing transactions
                    working_strategies[i] = self._mark_strategy_as_closed(strategy)
        
        # Second pass: Handle chain relationships (only if multiple strategies)
        if len(working_strategies) >= 2:
            # Look for roll patterns between different strategies
            for i in range(len(working_strategies)):
                current_strategy = working_strategies[i]
                
                # Look for subsequent rolls that might close this position
                for j in range(i + 1, len(working_strategies)):
                    potential_roll = working_strategies[j]
                    
                    # Check if this is a roll that closes the current strategy
                    if self._roll_closes_position(current_strategy, potential_roll):
                        # Update the current strategy to show it was closed by the roll
                        current_strategy = self._mark_strategy_as_rolled(current_strategy, potential_roll)
                        working_strategies[i] = current_strategy
                        break  # Found the roll for this position
        
        return working_strategies
    
    def _roll_closes_position(self, original_strategy: StrategyMatch, roll_strategy: StrategyMatch) -> bool:
        """
        Check if a roll strategy closes the position opened by the original strategy
        """
        # Must be a roll strategy
        if 'ROLL' not in roll_strategy.strategy_type.value.upper():
            return False
        
        # Get positions opened by original strategy
        original_positions = self._get_opened_positions_from_strategy(original_strategy)
        
        # Get positions closed by roll strategy  
        roll_closed_positions = self._get_closed_positions_from_strategy(roll_strategy)
        
        # Check if any position opened by original is closed by roll
        for orig_pos in original_positions:
            for roll_pos in roll_closed_positions:
                if self._positions_match(orig_pos, roll_pos):
                    return True
        
        return False
    
    def _roll_opens_new_position(self, roll_strategy: StrategyMatch) -> bool:
        """Check if a roll opens new positions (contains STO/BTO opening actions)"""
        opening_actions = ['STO', 'BTO', 'SELL_TO_OPEN', 'BUY_TO_OPEN']
        
        for tx in roll_strategy.transactions:
            action = str(tx.get('action', '')).upper()
            if any(opening_action in action for opening_action in opening_actions):
                return True
        
        return False
    
    def _get_opened_positions_from_strategy(self, strategy: StrategyMatch) -> List[Dict]:
        """Get positions opened by a strategy"""
        opened_positions = []
        opening_actions = ['STO', 'BTO', 'SELL_TO_OPEN', 'BUY_TO_OPEN']
        
        for tx in strategy.transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'OPTION' in instrument_type:
                action = str(tx.get('action', '')).upper()
                if any(opening_action in action for opening_action in opening_actions):
                    position = self._extract_position_from_transaction(tx)
                    if position:
                        opened_positions.append(position)
        
        return opened_positions
    
    def _get_closed_positions_from_strategy(self, strategy: StrategyMatch) -> List[Dict]:
        """Get positions closed by a strategy"""
        closed_positions = []
        closing_actions = ['BTC', 'STC', 'BUY_TO_CLOSE', 'SELL_TO_CLOSE']
        
        for tx in strategy.transactions:
            instrument_type = str(tx.get('instrument_type', ''))
            if 'OPTION' in instrument_type:
                action = str(tx.get('action', '')).upper()
                if any(closing_action in action for closing_action in closing_actions):
                    position = self._extract_position_from_transaction(tx)
                    if position:
                        closed_positions.append(position)
        
        return closed_positions
    
    def _extract_position_from_transaction(self, tx: Dict) -> Optional[Dict]:
        """Extract position details from a transaction"""
        symbol = tx.get('symbol', '')
        if ' ' in symbol:
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                if len(option_code) >= 7:
                    expiration = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[7:] if len(option_code) > 7 else '0'
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    return {
                        'strike': strike,
                        'expiration': expiration,
                        'option_type': option_type,
                        'underlying': parts[0]
                    }
        return None
    
    def _positions_match(self, pos1: Dict, pos2: Dict) -> bool:
        """Check if two positions represent the same contract"""
        return (pos1.get('strike') == pos2.get('strike') and
                pos1.get('expiration') == pos2.get('expiration') and
                pos1.get('option_type') == pos2.get('option_type') and
                pos1.get('underlying') == pos2.get('underlying'))
    
    def _mark_strategy_as_rolled(self, strategy: StrategyMatch, roll_strategy: StrategyMatch) -> StrategyMatch:
        """Mark a strategy as rolled (closed by a subsequent roll)"""
        # Create updated strategy with ROLLED status indication
        # We'll add metadata to indicate this was closed by a roll
        updated_strategy = StrategyMatch(
            strategy_type=strategy.strategy_type,
            transactions=strategy.transactions,
            confidence=strategy.confidence,
            quality_flags=strategy.quality_flags + [QualityFlag.VERIFIED],
            precedence_score=strategy.precedence_score,
            group=strategy.group,
            components=strategy.components
        )
        
        # Add roll closure metadata
        if not hasattr(updated_strategy, 'roll_closure_info'):
            updated_strategy.roll_closure_info = {
                'closed_by_roll': True,
                'closing_roll_group_key': roll_strategy.group.group_key,
                'closure_timestamp': roll_strategy.group.earliest_timestamp
            }
        
        return updated_strategy
    
    def _mark_strategy_as_open(self, strategy: StrategyMatch) -> StrategyMatch:
        """Mark a strategy as open (has unclosed positions)"""
        updated_strategy = StrategyMatch(
            strategy_type=strategy.strategy_type,
            transactions=strategy.transactions,
            confidence=strategy.confidence,
            quality_flags=strategy.quality_flags + [QualityFlag.VERIFIED],
            precedence_score=strategy.precedence_score,
            group=strategy.group,
            components=strategy.components
        )
        
        # Add open status metadata
        if not hasattr(updated_strategy, 'status_info'):
            updated_strategy.status_info = {
                'force_open': True,
                'reason': 'Contains opening transactions (STO/BTO)'
            }
        
        return updated_strategy
    
    def _mark_strategy_as_closed(self, strategy: StrategyMatch) -> StrategyMatch:
        """Mark a strategy as closed"""
        updated_strategy = StrategyMatch(
            strategy_type=strategy.strategy_type,
            transactions=strategy.transactions,
            confidence=strategy.confidence,
            quality_flags=strategy.quality_flags + [QualityFlag.VERIFIED],
            precedence_score=strategy.precedence_score,
            group=strategy.group,
            components=strategy.components
        )
        
        # Add closed status metadata
        if not hasattr(updated_strategy, 'status_info'):
            updated_strategy.status_info = {
                'force_closed': True,
                'reason': 'No opening transactions found'
            }
        
        return updated_strategy