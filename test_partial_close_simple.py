#!/usr/bin/env python3
"""
Simple test script to validate the partial close fix without loguru dependency.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_ibit_order():
    """Simple test to check IBIT order 397401079"""
    
    print("Testing IBIT partial close fix...")
    print("=" * 50)
    
    try:
        # Use sqlite3 directly to avoid import issues
        import sqlite3
        
        # Connect to database
        db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
        if not os.path.exists(db_path):
            print("❌ Database not found!")
            return
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if order 397401079 exists
        print("1. Checking IBIT order 397401079:")
        cursor.execute("""
            SELECT order_id, order_type, order_date, total_pnl
            FROM orders 
            WHERE order_id = '397401079'
        """)
        order = cursor.fetchone()
        if order:
            print(f"   ✓ Order found: {order[0]} ({order[1]}) on {order[2]} with P&L ${order[3]}")
            
            # Check its positions
            cursor.execute("""
                SELECT symbol, quantity, opening_action, closing_action, strike, expiration
                FROM positions_new 
                WHERE order_id = '397401079'
                ORDER BY symbol
            """)
            positions = cursor.fetchall()
            print(f"   ✓ Order has {len(positions)} positions:")
            for pos in positions:
                action = pos[3] if pos[3] else pos[2]  # Use closing_action or opening_action
                print(f"      - {action} {pos[1]}x {pos[0]} (${pos[4]} {pos[5]})")
        else:
            print("   ❌ Order 397401079 not found!")
            return
        
        # Check current chain status for IBIT with this order
        print("\n2. Current chain status containing order 397401079:")
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.chain_status, oc.opening_date, oc.closing_date
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE ocm.order_id = '397401079'
        """)
        chain = cursor.fetchone()
        
        if chain:
            chain_id, underlying, status, open_date, close_date = chain
            status_icon = "🔴" if status == 'OPEN' else "🟢"
            print(f"   {status_icon} Chain: {chain_id}")
            print(f"      Status: {status}")
            print(f"      Dates: {open_date} to {close_date}")
            
            # Show all positions in this chain to calculate balance
            cursor.execute("""
                SELECT p.symbol, p.opening_action, p.closing_action, p.quantity, p.strike, p.expiration, o.order_id, o.order_date
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id  
                JOIN orders o ON p.order_id = o.order_id
                WHERE ocm.chain_id = ?
                ORDER BY o.order_date, p.symbol, p.strike
            """, (chain_id,))
            positions = cursor.fetchall()
            
            print(f"\n3. All positions in chain {chain_id}:")
            position_balance = {}
            
            for pos in positions:
                symbol, open_action, close_action, qty, strike, exp, order_id, order_date = pos
                key = f"{symbol}_{strike}_{exp}"
                if key not in position_balance:
                    position_balance[key] = 0
                
                action = close_action if close_action else open_action
                print(f"   {order_date} {order_id}: {action} {qty}x {symbol} ${strike} {exp}")
                
                # Calculate balance
                if 'BUY_TO_OPEN' in action:
                    position_balance[key] -= abs(qty)  # Long
                elif 'SELL_TO_OPEN' in action:
                    position_balance[key] += abs(qty)  # Short
                elif 'BUY_TO_CLOSE' in action:
                    position_balance[key] -= abs(qty)  # Close short
                elif 'SELL_TO_CLOSE' in action:
                    position_balance[key] += abs(qty)  # Close long
                    
            print("\n4. Net position balances:")
            open_positions = 0
            for key, balance in position_balance.items():
                if abs(balance) > 1e-6:  # Non-zero balance
                    open_positions += 1
                    print(f"   🔴 {key}: {balance:+.0f} (STILL OPEN)")
                else:
                    print(f"   🟢 {key}: {balance:+.0f} (CLOSED)")
                    
            print(f"\n5. Analysis:")
            if open_positions > 0:
                print(f"   📊 {open_positions} positions still have non-zero quantities")
                if status == 'OPEN':
                    print(f"   ✅ SUCCESS: Chain is correctly OPEN")
                else:
                    print(f"   ❌ FAILURE: Chain is {status} but should be OPEN!")
            else:
                print(f"   📊 All positions are fully closed")
                if status == 'CLOSED':
                    print(f"   ✅ SUCCESS: Chain is correctly CLOSED")
                else:
                    print(f"   ❌ FAILURE: Chain is {status} but should be CLOSED!")
        else:
            print("   ❌ Could not find chain containing order 397401079")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_ibit_order()