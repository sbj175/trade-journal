#!/usr/bin/env python3
"""
Update Order Strategies
Reapply strategy recognition to fix Zebra and other ratio spread detection
"""

import sys
import sqlite3
from pathlib import Path

# Simple logger replacement
class Logger:
    def info(self, msg):
        print(f"INFO: {msg}")
    def warning(self, msg):
        print(f"WARNING: {msg}")
    def error(self, msg):
        print(f"ERROR: {msg}")

logger = Logger()

# Add project root to path
sys.path.append(str(Path(__file__).parent))

def determine_strategy_from_positions(positions):
    """Determine strategy type from position data - UPDATED with Zebra fix"""
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
                        # Check for 2:1 ratio (allowing for multiples like 8:4, 6:3, etc.)
                        ratio = qty1 / qty2 if qty2 > 0 else 0
                        if abs(ratio - 2.0) < 0.1:  # 2:1 ratio (with small tolerance)
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
    
    elif len(option_positions) == 3:
        # Check for butterfly
        if all(p[6] == option_positions[0][6] for p in option_positions):  # same type
            return 'Butterfly'
    
    return 'Complex Strategy'

def recognize_order_strategies(conn):
    """Recognize and update strategy types for all orders"""
    cursor = conn.cursor()
    
    # Get all orders
    cursor.execute("SELECT order_id FROM orders")
    order_ids = [row[0] for row in cursor.fetchall()]
    
    updated_count = 0
    
    for order_id in order_ids:
        # Get positions for this order
        cursor.execute("""
            SELECT position_id, order_id, account_number, symbol, underlying, 
                   instrument_type, option_type, strike, expiration, quantity,
                   opening_price, closing_price, opening_transaction_id, 
                   closing_transaction_id, opening_action, closing_action, 
                   status, pnl, created_at, updated_at
            FROM positions_new 
            WHERE order_id = ?
        """, (order_id,))
        
        positions = cursor.fetchall()
        if not positions:
            continue
        
        old_strategy = None
        cursor.execute("SELECT strategy_type FROM orders WHERE order_id = ?", (order_id,))
        old_result = cursor.fetchone()
        if old_result:
            old_strategy = old_result[0]
        
        new_strategy = determine_strategy_from_positions(positions)
        
        if old_strategy != new_strategy:
            # Update order with new strategy type
            cursor.execute("""
                UPDATE orders SET strategy_type = ? WHERE order_id = ?
            """, (new_strategy, order_id))
            
            logger.info(f"Order {order_id}: {old_strategy} -> {new_strategy}")
            updated_count += 1
    
    logger.info(f"Updated {updated_count} orders with corrected strategies")
    return updated_count

def main():
    """Update order strategies with Zebra fix"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        logger.error("Database not found")
        return
    
    logger.info("Updating order strategies with Zebra recognition fix")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        updated_count = recognize_order_strategies(conn)
        conn.commit()
        
        logger.info(f"Strategy update complete. Updated {updated_count} orders.")
        
        # Show some examples of updated strategies
        cursor = conn.cursor()
        cursor.execute("""
            SELECT order_id, underlying, strategy_type, total_pnl
            FROM orders 
            WHERE strategy_type LIKE '%Zebra%' OR strategy_type LIKE '%Ratio%'
            ORDER BY order_id
        """)
        
        ratio_orders = cursor.fetchall()
        if ratio_orders:
            logger.info("Found ratio spread orders:")
            for order in ratio_orders:
                logger.info(f"  {order[0]}: {order[1]} {order[2]} (P&L: ${order[3]:.2f})")
        
    except Exception as e:
        logger.error(f"Error updating strategies: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()