#!/usr/bin/env python3
"""
Test script to validate the partial close fix for IBIT order 397401079.
This order should result in a chain that remains OPEN because there are still remaining positions.
"""

import sqlite3
from src.models.order_models import OrderManager
from src.database.db_manager import DatabaseManager

def test_ibit_partial_close():
    """Test that IBIT order 397401079 results in an OPEN chain due to partial close"""
    
    print("Testing IBIT partial close fix...")
    print("=" * 50)
    
    # Initialize database and order manager
    db = DatabaseManager()
    order_manager = OrderManager(db)
    
    # First, let's check the current state before reprocessing
    print("1. Current chain status for IBIT before reprocessing:")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.chain_status, oc.opening_date, oc.closing_date
            FROM order_chains oc
            WHERE oc.underlying = 'IBIT'
            ORDER BY oc.opening_date DESC
            LIMIT 5
        """)
        chains = cursor.fetchall()
        for chain in chains:
            status_icon = "🔴" if chain[2] == 'OPEN' else "🟢"
            print(f"   {status_icon} {chain[0]}: {chain[2]} ({chain[3]} to {chain[4]})")
    
    # Check if order 397401079 exists
    print("\n2. Checking IBIT order 397401079:")
    with db.get_connection() as conn:
        cursor = conn.cursor()
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
    
    # Now reprocess chains to apply our fix
    print("\n3. Reprocessing chains with partial close fix...")
    result = order_manager.reprocess_orders_and_chains_from_database()
    print(f"   ✓ Reprocessed: {result['chains_saved']} chains")
    
    # Check the chain status after reprocessing
    print("\n4. Chain status for IBIT after reprocessing:")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.chain_status, oc.opening_date, oc.closing_date,
                   ocm.order_id
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE oc.underlying = 'IBIT' AND ocm.order_id = '397401079'
        """)
        ibit_chain = cursor.fetchone()
        
        if ibit_chain:
            chain_id, underlying, status, open_date, close_date, order_id = ibit_chain
            status_icon = "🔴" if status == 'OPEN' else "🟢"
            print(f"   {status_icon} Chain containing order 397401079:")
            print(f"      Chain ID: {chain_id}")
            print(f"      Status: {status}")
            print(f"      Dates: {open_date} to {close_date}")
            
            # Validate: Should be OPEN because of partial close
            if status == 'OPEN':
                print(f"   ✅ SUCCESS: Chain correctly remains OPEN due to partial close!")
            else:
                print(f"   ❌ FAILURE: Chain is {status} but should be OPEN due to partial close!")
                
            # Show all orders in this chain
            cursor.execute("""
                SELECT o.order_id, o.order_type, o.order_date, o.total_pnl
                FROM orders o
                JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
                ORDER BY o.order_date
            """, (chain_id,))
            orders = cursor.fetchall()
            print(f"   📋 Chain contains {len(orders)} orders:")
            for order in orders:
                print(f"      - {order[0]} ({order[1]}) on {order[2]} P&L: ${order[3]}")
                
            # Calculate and show position balance
            print("\n5. Position balance analysis:")
            cursor.execute("""
                SELECT p.symbol, p.opening_action, p.closing_action, p.quantity, p.strike, p.expiration
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id  
                WHERE ocm.chain_id = ?
                ORDER BY p.symbol, p.strike
            """, (chain_id,))
            positions = cursor.fetchall()
            
            # Calculate net position balance
            position_balance = {}
            for pos in positions:
                symbol, open_action, close_action, qty, strike, exp = pos
                key = f"{symbol}_{strike}_{exp}"
                if key not in position_balance:
                    position_balance[key] = 0
                
                action = close_action if close_action else open_action
                if 'BUY_TO_OPEN' in action:
                    position_balance[key] -= abs(qty)  # Long
                elif 'SELL_TO_OPEN' in action:
                    position_balance[key] += abs(qty)  # Short
                elif 'BUY_TO_CLOSE' in action:
                    position_balance[key] -= abs(qty)  # Close short
                elif 'SELL_TO_CLOSE' in action:
                    position_balance[key] += abs(qty)  # Close long
                    
            print("   Net position balances:")
            open_positions = 0
            for key, balance in position_balance.items():
                if abs(balance) > 1e-6:  # Non-zero balance
                    open_positions += 1
                    print(f"      - {key}: {balance:+.0f} (OPEN)")
                else:
                    print(f"      - {key}: {balance:+.0f} (CLOSED)")
                    
            if open_positions > 0:
                print(f"   ✅ Confirmed: {open_positions} positions still open, chain should be OPEN")
            else:
                print(f"   ⚠️  All positions closed, chain should be CLOSED")
        else:
            print("   ❌ Could not find chain containing order 397401079")

if __name__ == "__main__":
    test_ibit_partial_close()