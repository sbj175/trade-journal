#!/usr/bin/env python3
"""
Fix Zebra strategy recognition in the order position model
"""

import sqlite3
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def determine_strategy_from_positions_with_zebra(positions):
    """Enhanced strategy determination that recognizes Zebra and other ratio spreads"""
    option_positions = [p for p in positions if 'OPTION' in str(p[5])]  # instrument_type
    stock_positions = [p for p in positions if 'EQUITY' in str(p[5]) and 'OPTION' not in str(p[5])]
    
    # Single position strategies
    if len(positions) == 1:
        pos = positions[0]
        if 'OPTION' in str(pos[5]):  # option position
            if pos[9] > 0:  # quantity positive = long
                return 'Long Call' if pos[6] == 'Call' else 'Long Put'  # option_type
            else:  # short
                return 'Naked Call' if pos[6] == 'Call' else 'Cash Secured Put'
        else:  # stock position
            return 'Long Stock' if pos[9] > 0 else 'Short Stock'
    
    # Two position strategies
    elif len(positions) == 2:
        if len(option_positions) == 2:
            # Both options - check for spreads/straddles/strangles
            opt1, opt2 = sorted(option_positions, key=lambda x: x[7] or 0)  # sort by strike
            
            # Same expiration
            if opt1[8] == opt2[8]:  # same expiration
                if opt1[6] == opt2[6]:  # same option type
                    # Check quantities for ratio spreads
                    qty1, qty2 = abs(opt1[9]), abs(opt2[9])
                    
                    # Check for Zebra pattern (2:1 ratio with long at lower strike)
                    if opt1[6] == 'Call' and opt1[9] > 0 and opt2[9] < 0:
                        # Long calls at lower strike, short calls at higher strike
                        if qty1 == 2 * qty2:  # 2:1 ratio
                            return 'Zebra'
                        elif qty1 != qty2:  # Other ratio
                            return f'Call Ratio Spread ({qty1}:{qty2})'
                        else:  # 1:1 ratio
                            return 'Bull Call Spread'
                    
                    # Check for Put ratio spreads
                    elif opt1[6] == 'Put' and opt1[9] > 0 and opt2[9] < 0:
                        if qty1 != qty2:
                            return f'Put Ratio Spread ({qty1}:{qty2})'
                        else:
                            return 'Bull Put Spread'
                    
                    # Standard vertical spreads
                    elif opt1[9] > 0 and opt2[9] < 0:  # long/short
                        return 'Bull Call Spread' if opt1[6] == 'Call' else 'Bull Put Spread'
                    elif opt1[9] < 0 and opt2[9] > 0:  # short/long
                        return 'Bear Call Spread' if opt1[6] == 'Call' else 'Bear Put Spread'
                else:
                    # Different types
                    if opt1[7] == opt2[7]:  # same strike
                        return 'Straddle'
                    else:
                        return 'Strangle'
            else:
                # Different expirations
                return 'Calendar Spread' if opt1[7] == opt2[7] else 'Diagonal Spread'
        
        elif len(option_positions) == 1 and len(stock_positions) == 1:
            # Stock + option combo
            opt = option_positions[0]
            if opt[6] == 'Call' and opt[9] < 0:  # short call
                return 'Covered Call'
            else:
                return 'Complex Strategy'
    
    # Three position strategies
    elif len(option_positions) == 3:
        # Check for modified butterflies and other 3-leg strategies
        calls = [p for p in option_positions if p[6] == 'Call']
        puts = [p for p in option_positions if p[6] == 'Put']
        
        if len(calls) == 3:
            # All calls - could be a broken wing butterfly or other ratio spread
            sorted_calls = sorted(calls, key=lambda x: x[7] or 0)
            
            # Check quantities
            qty_pattern = [p[9] for p in sorted_calls]
            
            # Standard butterfly: +1, -2, +1
            if qty_pattern[0] > 0 and qty_pattern[1] < 0 and qty_pattern[2] > 0:
                if abs(qty_pattern[1]) == abs(qty_pattern[0]) + abs(qty_pattern[2]):
                    return 'Call Butterfly'
                else:
                    return 'Broken Wing Butterfly'
            else:
                return 'Complex Call Spread'
        
        elif len(puts) == 3:
            # Similar logic for puts
            return 'Put Butterfly'
        
        else:
            return 'Complex Strategy'
    
    # Multi-leg strategies
    elif len(option_positions) == 4:
        calls = [p for p in option_positions if p[6] == 'Call']
        puts = [p for p in option_positions if p[6] == 'Put']
        
        if len(calls) == 2 and len(puts) == 2:
            # Check for Iron Condor/Butterfly
            all_strikes = sorted(set(p[7] for p in option_positions if p[7]))
            if len(all_strikes) == 3:
                return 'Iron Butterfly'
            elif len(all_strikes) == 4:
                return 'Iron Condor'
    
    return 'Complex Strategy'


def update_order_strategies(conn):
    """Update all orders with the enhanced strategy recognition"""
    cursor = conn.cursor()
    
    # Get all orders
    cursor.execute("SELECT order_id FROM orders")
    order_ids = [row[0] for row in cursor.fetchall()]
    
    updated_count = 0
    for order_id in order_ids:
        # Get positions for this order
        cursor.execute("""
            SELECT * FROM positions_new WHERE order_id = ?
            ORDER BY symbol
        """, (order_id,))
        
        positions = cursor.fetchall()
        if not positions:
            continue
        
        # Get current strategy
        cursor.execute("SELECT strategy_type FROM orders WHERE order_id = ?", (order_id,))
        current_strategy = cursor.fetchone()[0]
        
        # Determine new strategy
        new_strategy = determine_strategy_from_positions_with_zebra(positions)
        
        # Update if different
        if new_strategy != current_strategy:
            cursor.execute("""
                UPDATE orders SET strategy_type = ? WHERE order_id = ?
            """, (new_strategy, order_id))
            
            logger.info(f"Updated order {order_id}: '{current_strategy}' -> '{new_strategy}'")
            updated_count += 1
    
    conn.commit()
    logger.info(f"Updated {updated_count} orders with corrected strategies")


def main():
    """Main function to apply the fix"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        logger.error("Database not found!")
        return
    
    with sqlite3.connect(db_path) as conn:
        # Update strategies
        update_order_strategies(conn)
        
        # Check specific order
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.order_id, o.strategy_type, o.underlying,
                   COUNT(p.position_id) as position_count
            FROM orders o
            JOIN positions_new p ON o.order_id = p.order_id
            WHERE o.order_id = '388512672'
            GROUP BY o.order_id
        """)
        
        result = cursor.fetchone()
        if result:
            logger.info(f"\nOrder 388512672 now shows as: {result[1]}")


if __name__ == "__main__":
    main()