"""
Strategy Detection for V2 Order Chains
Analyzes positions within chains and account context to identify option strategies
"""

from typing import Dict, List, Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class StrategyDetector:
    """Detects option strategies based on positions and account context"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def detect_chain_strategy(self, chain, account_context: Optional[Dict] = None) -> str:
        """
        Detect the strategy for an order chain
        
        Args:
            chain: The order chain object
            account_context: Optional context about other positions in the account
            
        Returns:
            Strategy name (e.g., "Covered Call", "Iron Condor", "Short Put")
        """
        # Debug logging for specific chain
        if hasattr(chain, 'chain_id') and 'IBIT' in str(chain.chain_id):
            logger.info(f"DEBUG ZEBRA - Starting strategy detection for chain: {chain.chain_id}")
        
        # Critical debug for CSX - let's see what's happening
        if hasattr(chain, 'underlying') and chain.underlying == 'CSX':
            chain_id = getattr(chain, 'chain_id', 'unknown')
            logger.warning(f"[STRATEGY_DETECTOR] CSX chain {chain_id}: Starting detection")
            logger.warning(f"  Chain has {len(chain.orders)} orders")
            if chain.orders:
                for i, order in enumerate(chain.orders):
                    logger.warning(f"  Order {i}: type={order.order_type.value}, {len(order.transactions)} transactions")
                    for j, tx in enumerate(order.transactions):
                        logger.warning(f"    TX {j}: {tx.symbol}, option_type={tx.option_type}, strike={tx.strike}")
        
        if not chain.orders:
            logger.debug(f"Strategy detection: No orders in chain {getattr(chain, 'chain_id', 'unknown')}")
            return "Unknown"
        
        # For now, focus on the opening order to determine base strategy
        opening_order = None
        for order in chain.orders:
            if order.order_type.value == 'OPENING':
                opening_order = order
                break
        
        if not opening_order:
            logger.debug(f"Strategy detection: No opening order found in chain {getattr(chain, 'chain_id', 'unknown')}")
            return "Unknown"
        
        # Get all positions from the opening order and aggregate by symbol/strike/type
        position_map = {}
        for tx in opening_order.transactions:
            # Debug log for CSX/GOOG chains
            if hasattr(chain, 'underlying') and chain.underlying in ['CSX', 'GOOG', 'USO']:
                logger.warning(f"[STRATEGY_DETECTOR] Chain {chain.underlying}: Processing tx {tx.symbol}, option_type={tx.option_type}, strike={tx.strike}")
            
            if tx.option_type:  # Only options positions
                # Create unique key for aggregation (symbol includes strike and expiration info)
                key = f"{tx.symbol}_{tx.option_type}"
                
                if key in position_map:
                    # Aggregate quantities for same position (split fills)
                    position_map[key]['quantity'] += tx.quantity
                else:
                    # Create new aggregated position
                    position_map[key] = {
                        'symbol': tx.symbol,
                        'underlying': tx.underlying_symbol,
                        'option_type': tx.option_type,
                        'strike': tx.strike,
                        'expiration': tx.expiration,
                        'quantity': tx.quantity,
                        'action': tx.action,
                        'is_buy': tx.is_buy,
                        'is_sell': tx.is_sell
                    }
        
        positions = list(position_map.values())
        
        # Debug logging for IBIT chains
        if hasattr(chain, 'chain_id') and 'IBIT' in str(chain.chain_id):
            logger.info(f"DEBUG ZEBRA - Found {len(positions)} aggregated positions: {positions}")
        
        if not positions:
            return "Unknown"
        
        # Single position strategies
        if len(positions) == 1:
            return self._detect_single_position_strategy(positions[0], chain, account_context)
        
        # Multi-position strategies
        result = self._detect_multi_position_strategy(positions, chain)
        
        # Final debug for CSX
        if hasattr(chain, 'underlying') and chain.underlying == 'CSX':
            logger.warning(f"[STRATEGY_DETECTOR] CSX chain final result: {result}")
        
        return result
    
    def _detect_single_position_strategy(self, position: Dict, chain, account_context: Optional[Dict]) -> str:
        """Detect strategy for single option position"""
        option_type = position['option_type']
        is_buy = position['is_buy']
        is_sell = position['is_sell']
        underlying = position['underlying']
        quantity = abs(position['quantity'])
        
        # Basic single-leg strategies
        if option_type == 'Call':
            if is_buy:
                base_strategy = "Long Call"
            else:  # is_sell
                base_strategy = "Short Call"
                
                # Check for covered call
                if self._has_stock_coverage(underlying, quantity, chain.opening_date, chain.account_number):
                    return "Covered Call"
                
                return base_strategy
                
        elif option_type == 'Put':
            if is_buy:
                return "Long Put"
            else:  # is_sell
                base_strategy = "Short Put"
                
                # Check for cash-secured put (would need cash analysis)
                # For now, just return short put
                return base_strategy
        
        # Fallback for unrecognized option types
        logger.warning(f"Unrecognized option type in strategy detection: {option_type}")
        return "Unknown"
    
    def _detect_multi_position_strategy(self, positions: List[Dict], chain) -> str:
        """Detect strategy for multiple option positions"""
        if len(positions) == 2:
            return self._detect_two_leg_strategy(positions)
        elif len(positions) == 4:
            return self._detect_four_leg_strategy(positions)
        else:
            return f"{len(positions)}-Leg Strategy"
    
    def _detect_two_leg_strategy(self, positions: List[Dict]) -> str:
        """Detect 2-leg strategies (spreads and ZEBRA)"""
        pos1, pos2 = positions
        
        # Debug logging for specific order
        debug_order = any(
            pos.get('symbol', '').endswith('00047000') or pos.get('symbol', '').endswith('00061000')
            for pos in positions
        )
        if debug_order:
            logger.info(f"DEBUG ZEBRA - Two-leg detection for positions: {positions}")
        
        # Must be same underlying and expiration for spreads
        if (pos1['underlying'] != pos2['underlying'] or 
            pos1['expiration'] != pos2['expiration']):
            return "Multi-Leg Strategy"
        
        # Same option type = vertical spread or ZEBRA
        if pos1['option_type'] == pos2['option_type']:
            option_type = pos1['option_type']
            
            # Determine direction based on strikes and buy/sell
            strikes = [pos1['strike'], pos2['strike']]
            strikes.sort()
            low_strike, high_strike = strikes
            
            # Find which position has which strike
            if pos1['strike'] == low_strike:
                low_pos, high_pos = pos1, pos2
            else:
                low_pos, high_pos = pos2, pos1
            
            # Check for ZEBRA ratios (1:2 or 2:1)
            low_qty = abs(low_pos['quantity'])
            high_qty = abs(high_pos['quantity'])
            
            if option_type == 'Call':
                # Debug logging for ZEBRA detection
                if debug_order:
                    logger.info(f"DEBUG ZEBRA - Call analysis: low_qty={low_qty}, high_qty={high_qty}, low_is_buy={low_pos['is_buy']}, high_is_sell={high_pos['is_sell']}")
                    logger.info(f"DEBUG ZEBRA - Checking Bull ZEBRA: {low_pos['is_buy']} and {high_pos['is_sell']} and {low_qty} == 2 * {high_qty} = {low_qty == 2 * high_qty}")
                
                # Check for Bull ZEBRA (long 2x at lower strike, short 1x at higher strike)
                if (low_pos['is_buy'] and high_pos['is_sell'] and 
                    low_qty == 2 * high_qty):
                    if debug_order:
                        logger.info("DEBUG ZEBRA - Detected Bull ZEBRA!")
                    return "Bull ZEBRA"
                # Check for Bear ZEBRA (short 2x at lower strike, long 1x at higher strike) 
                elif (low_pos['is_sell'] and high_pos['is_buy'] and
                      low_qty == 2 * high_qty):
                    return "Bear ZEBRA"
                # Regular vertical spreads (1:1 ratio)
                elif low_qty == high_qty:
                    if low_pos['is_buy'] and high_pos['is_sell']:
                        return "Bull Call Spread"
                    elif low_pos['is_sell'] and high_pos['is_buy']:
                        return "Bear Call Spread"
            elif option_type == 'Put':
                # Check for Bull ZEBRA with puts (long 2x at higher strike, short 1x at lower strike)
                if (high_pos['is_buy'] and low_pos['is_sell'] and 
                    high_qty == 2 * low_qty):
                    return "Bull ZEBRA"
                # Check for Bear ZEBRA with puts (short 2x at higher strike, long 1x at lower strike)
                elif (high_pos['is_sell'] and low_pos['is_buy'] and
                      high_qty == 2 * low_qty):
                    return "Bear ZEBRA"
                # Regular vertical spreads (1:1 ratio)
                elif low_qty == high_qty:
                    if high_pos['is_sell'] and low_pos['is_buy']:
                        return "Bull Put Spread"
                    elif high_pos['is_buy'] and low_pos['is_sell']:
                        return "Bear Put Spread"
        
        # Different option types = straddle/strangle
        elif pos1['option_type'] != pos2['option_type']:
            if pos1['strike'] == pos2['strike']:
                if pos1['is_buy'] and pos2['is_buy']:
                    return "Long Straddle"
                elif pos1['is_sell'] and pos2['is_sell']:
                    return "Short Straddle"
            else:
                if pos1['is_buy'] and pos2['is_buy']:
                    return "Long Strangle"
                elif pos1['is_sell'] and pos2['is_sell']:
                    return "Short Strangle"
        
        return "2-Leg Strategy"
    
    def _detect_four_leg_strategy(self, positions: List[Dict]) -> str:
        """Detect 4-leg strategies (iron condors, etc.)"""
        # Group by option type
        calls = [pos for pos in positions if pos['option_type'] == 'Call']
        puts = [pos for pos in positions if pos['option_type'] == 'Put']
        
        if len(calls) == 2 and len(puts) == 2:
            return "Iron Condor"
        
        return "4-Leg Strategy"
    
    def _has_stock_coverage(self, underlying: str, call_contracts: int, 
                           option_date: Optional[date], account_number: str) -> bool:
        """Check if there's enough stock position to cover short calls"""
        if not option_date:
            return False
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get stock position at the time of the option order
                cursor.execute("""
                    SELECT SUM(CASE 
                        WHEN action LIKE '%BUY%' THEN quantity 
                        WHEN action LIKE '%SELL%' THEN -quantity 
                        ELSE 0 
                    END) as net_position
                    FROM raw_transactions 
                    WHERE underlying_symbol = ?
                    AND account_number = ?
                    AND instrument_type LIKE '%EQUITY'
                    AND instrument_type NOT LIKE '%OPTION%'
                    AND date(executed_at) <= ?
                """, (underlying, account_number, option_date.isoformat()))
                
                result = cursor.fetchone()
                net_stock_position = result[0] if result and result[0] else 0
                
                # Need 100 shares per call contract
                shares_needed = call_contracts * 100
                
                logger.debug(f"Coverage check for {underlying}: {net_stock_position} shares vs {shares_needed} needed")
                
                return net_stock_position >= shares_needed
                
        except Exception as e:
            logger.error(f"Error checking stock coverage: {str(e)}")
            return False