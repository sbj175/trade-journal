#!/usr/bin/env python3
"""
Verify the Zebra and ratio spread recognition fix
"""

import sqlite3
from pathlib import Path

def verify_ratio_spreads():
    """Check all ratio spreads in the database"""
    db_path = Path("trade_journal.db")
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Find all ratio spreads including Zebra
        print("\n=== Ratio Spreads and Zebra Strategies ===")
        cursor.execute("""
            SELECT o.order_id, o.account_number, o.underlying, o.strategy_type, 
                   o.order_date, o.status, COUNT(p.position_id) as position_count
            FROM orders o
            JOIN positions_new p ON o.order_id = p.order_id
            WHERE o.strategy_type LIKE '%Ratio%' OR o.strategy_type = 'Zebra'
            GROUP BY o.order_id
            ORDER BY o.order_date DESC
        """)
        
        results = cursor.fetchall()
        print(f"Found {len(results)} ratio spreads/Zebra strategies\n")
        
        for row in results:
            print(f"Order {row['order_id']}:")
            print(f"  Account: {row['account_number']}")
            print(f"  Underlying: {row['underlying']}")
            print(f"  Strategy: {row['strategy_type']}")
            print(f"  Date: {row['order_date']}")
            print(f"  Status: {row['status']}")
            print(f"  Positions: {row['position_count']}")
            
            # Get position details
            cursor.execute("""
                SELECT symbol, option_type, strike, quantity, opening_price
                FROM positions_new 
                WHERE order_id = ?
                ORDER BY strike
            """, (row['order_id'],))
            
            positions = cursor.fetchall()
            for pos in positions:
                print(f"    - {pos['symbol']}: {pos['quantity']} @ ${pos['opening_price']:.2f}")
            print()
        
        # Show specifically the Zebra we fixed
        print("\n=== Specific Zebra Order 388512672 ===")
        cursor.execute("""
            SELECT o.*, 
                   GROUP_CONCAT(p.symbol || ' x' || p.quantity, ', ') as positions_summary
            FROM orders o
            JOIN positions_new p ON o.order_id = p.order_id
            WHERE o.order_id = '388512672'
            GROUP BY o.order_id
        """)
        
        zebra = cursor.fetchone()
        if zebra:
            print(f"Order ID: {zebra['order_id']}")
            print(f"Strategy: {zebra['strategy_type']} ✓")
            print(f"Positions: {zebra['positions_summary']}")
            print(f"Status: {zebra['status']}")
            print(f"P&L: ${zebra['total_pnl']:.2f}")

if __name__ == "__main__":
    verify_ratio_spreads()