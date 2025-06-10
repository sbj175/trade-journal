#!/usr/bin/env python3
"""
Check order details and positions for a specific order
"""

import sqlite3
from pathlib import Path
import json

def check_order_details(order_id):
    """Check order and position details"""
    db_path = Path("trade_journal.db")
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get order details
        print(f"\n=== Order {order_id} Details ===")
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        order = cursor.fetchone()
        
        if order:
            for key in order.keys():
                print(f"{key}: {order[key]}")
        else:
            print("Order not found!")
            return
            
        # Get positions
        print(f"\n=== Positions for Order {order_id} ===")
        cursor.execute("""
            SELECT symbol, option_type, strike, expiration, quantity, 
                   opening_price, closing_price, opening_action, status
            FROM positions_new 
            WHERE order_id = ?
            ORDER BY symbol
        """, (order_id,))
        
        positions = cursor.fetchall()
        for i, pos in enumerate(positions):
            print(f"\nPosition {i+1}:")
            print(f"  Symbol: {pos['symbol']}")
            print(f"  Type: {pos['option_type']}")
            print(f"  Strike: {pos['strike']}")
            print(f"  Expiration: {pos['expiration']}")
            print(f"  Quantity: {pos['quantity']}")
            print(f"  Opening Price: ${pos['opening_price']}")
            print(f"  Action: {pos['opening_action']}")
            print(f"  Status: {pos['status']}")
            
        # Analyze what strategy this should be
        print(f"\n=== Strategy Analysis ===")
        if len(positions) == 3:
            # Count calls by quantity
            long_calls = sum(1 for p in positions if p['option_type'] == 'Call' and p['quantity'] > 0)
            short_calls = sum(1 for p in positions if p['option_type'] == 'Call' and p['quantity'] < 0)
            
            print(f"Total positions: {len(positions)}")
            print(f"Long calls: {long_calls}")
            print(f"Short calls: {short_calls}")
            
            # Check if it's a Zebra (2 long calls + 1 short call at higher strike)
            if long_calls == 2 and short_calls == 1:
                # Get strike prices
                long_strikes = [p['strike'] for p in positions if p['quantity'] > 0]
                short_strikes = [p['strike'] for p in positions if p['quantity'] < 0]
                
                print(f"Long strikes: {long_strikes}")
                print(f"Short strikes: {short_strikes}")
                
                if long_strikes and short_strikes:
                    # In a Zebra, the short strike should be higher than the long strikes
                    if all(short_strikes[0] > ls for ls in long_strikes):
                        print("\n*** This appears to be a ZEBRA strategy! ***")
                        print("Pattern: 2 long calls at lower strike + 1 short call at higher strike")
                    else:
                        print("\nNot a typical Zebra pattern (short strike not higher than long strikes)")

if __name__ == "__main__":
    # Check the specific order
    check_order_details("388512672")