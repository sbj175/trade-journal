#!/usr/bin/env python3
"""
Investigate actual P&L calculation for IBIT chain with order 397401079
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
import json

def investigate_ibit_pnl():
    """Investigate the actual P&L values for the IBIT chain"""
    
    db = DatabaseManager()
    db.ensure_initialized()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Find the chain containing order 397401079
        print("=== FINDING IBIT CHAIN ===")
        
        # First check if this order exists
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", ('397401079',))
        target_order = cursor.fetchone()
        if not target_order:
            print("ERROR: Order 397401079 not found!")
            return
        
        target_order = dict(target_order)
        print(f"Target order: {target_order}")
        
        # Find chain membership
        cursor.execute("SELECT chain_id FROM order_chain_members WHERE order_id = ?", ('397401079',))
        chain_result = cursor.fetchone()
        
        if not chain_result:
            print("Order 397401079 is not part of any chain")
            # Let's look for related orders by underlying and account
            print("\n=== LOOKING FOR RELATED IBIT ORDERS ===")
            cursor.execute("""
                SELECT * FROM orders 
                WHERE underlying = 'IBIT' AND account_number = ?
                ORDER BY order_date
            """, (target_order['account_number'],))
            ibit_orders = [dict(row) for row in cursor.fetchall()]
            
            for order in ibit_orders:
                print(f"Order {order['order_id']} ({order['order_type']}) - {order['order_date']} - P&L: {order['total_pnl']}")
            return
        
        chain_id = chain_result[0]
        print(f"Chain ID: {chain_id}")
        
        # 2. Get chain information
        print("\n=== CHAIN INFORMATION ===")
        cursor.execute("SELECT * FROM order_chains WHERE chain_id = ?", (chain_id,))
        chain_info = cursor.fetchone()
        if chain_info:
            chain_info = dict(chain_info)
            print(f"Chain: {chain_info}")
        
        # 3. Get all orders in this chain
        print("\n=== CHAIN ORDERS ===")
        cursor.execute("""
            SELECT o.* FROM orders o
            JOIN order_chain_members ocm ON o.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date, o.order_id
        """, (chain_id,))
        orders = [dict(row) for row in cursor.fetchall()]
        
        total_order_pnl = 0
        for order in orders:
            print(f"Order {order['order_id']} ({order['order_type']}):")
            print(f"  Date: {order['order_date']}")
            print(f"  Status: {order['status']}")
            print(f"  Quantity: {order['total_quantity']}")
            print(f"  Total P&L: {order['total_pnl']}")
            total_order_pnl += order['total_pnl'] or 0
            print()
        
        print(f"Sum of all order P&L: {total_order_pnl}")
        
        # 4. Get all positions for these orders
        print("\n=== POSITIONS FOR CHAIN ORDERS ===")
        order_ids = [order['order_id'] for order in orders]
        placeholders = ','.join('?' * len(order_ids))
        
        cursor.execute(f"""
            SELECT * FROM positions 
            WHERE order_id IN ({placeholders})
            ORDER BY open_date, position_id
        """, order_ids)
        positions = [dict(row) for row in cursor.fetchall()]
        
        total_position_pnl = 0
        open_positions = []
        closed_positions = []
        
        for pos in positions:
            print(f"Position {pos['position_id']} (Order {pos['order_id']}):")
            print(f"  Symbol: {pos['symbol']}")
            print(f"  Instrument: {pos['instrument_type']}")
            print(f"  Quantity: {pos['quantity']}")
            print(f"  Price: {pos['price']}")
            print(f"  Value: {pos['value']}")
            print(f"  Open Date: {pos['open_date']}")
            print(f"  Close Date: {pos['close_date']}")
            print(f"  P&L: {pos['pnl']}")
            print(f"  Status: {pos['status']}")
            print(f"  Closing Order: {pos['closing_order_id']}")
            
            if pos['pnl']:
                total_position_pnl += pos['pnl']
            
            if pos['status'] == 'OPEN':
                open_positions.append(pos)
            else:
                closed_positions.append(pos)
            print()
        
        print(f"Sum of all position P&L: {total_position_pnl}")
        
        # 5. Analyze the specific positions
        print("\n=== POSITION ANALYSIS ===")
        print(f"Open positions: {len(open_positions)}")
        print(f"Closed positions: {len(closed_positions)}")
        
        realized_pnl = sum(pos['pnl'] or 0 for pos in closed_positions)
        print(f"Realized P&L (closed positions): {realized_pnl}")
        
        # 6. Check if there's realized/unrealized breakdown
        print("\n=== LOOKING FOR P&L BREAKDOWN ===")
        # Check if the new positions table has more detailed P&L info
        cursor.execute("PRAGMA table_info(positions_new)")
        new_pos_cols = [col[1] for col in cursor.fetchall()]
        if 'realized_pnl' in new_pos_cols:
            print("Found positions_new table with realized_pnl column")
            cursor.execute(f"""
                SELECT * FROM positions_new 
                WHERE order_id IN ({placeholders})
                ORDER BY open_date, position_id
            """, order_ids)
            new_positions = [dict(row) for row in cursor.fetchall()]
            
            for pos in new_positions:
                print(f"New Position {pos['position_id']}:")
                if 'realized_pnl' in pos:
                    print(f"  Realized P&L: {pos.get('realized_pnl')}")
                if 'unrealized_pnl' in pos:
                    print(f"  Unrealized P&L: {pos.get('unrealized_pnl')}")
        
        # 7. Check individual transactions that make up these orders
        print("\n=== INDIVIDUAL TRANSACTIONS ===")
        for order in orders:
            print(f"\nTransactions for Order {order['order_id']}:")
            cursor.execute("""
                SELECT * FROM raw_transactions 
                WHERE order_id = ?
                ORDER BY executed_at
            """, (order['order_id'],))
            transactions = [dict(row) for row in cursor.fetchall()]
            
            for txn in transactions:
                print(f"  {txn['symbol']} x{txn['quantity']} @ {txn['price']} = {txn['net_value']}")

if __name__ == "__main__":
    investigate_ibit_pnl()