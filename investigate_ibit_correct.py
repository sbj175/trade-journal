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
            return
        
        chain_id = chain_result[0]
        print(f"Chain ID: {chain_id}")
        
        # 2. Get chain information
        print("\n=== CHAIN INFORMATION ===")
        cursor.execute("SELECT * FROM order_chains WHERE chain_id = ?", (chain_id,))
        chain_info = cursor.fetchone()
        if chain_info:
            chain_info = dict(chain_info)
            print(f"Chain Status: {chain_info['chain_status']}")
            print(f"Total P&L: {chain_info['total_pnl']}")
            print(f"Realized P&L: {chain_info['realized_pnl']}")
            print(f"Unrealized P&L: {chain_info['unrealized_pnl']}")
            print(f"Opening Date: {chain_info['opening_date']}")
            print(f"Closing Date: {chain_info['closing_date']}")
        
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
        
        # 4. Get individual transactions that make up these orders
        print("\n=== INDIVIDUAL TRANSACTIONS ===")
        total_realized = 0
        for order in orders:
            print(f"\nTransactions for Order {order['order_id']} ({order['order_type']}):")
            cursor.execute("""
                SELECT * FROM raw_transactions 
                WHERE order_id = ?
                ORDER BY executed_at
            """, (order['order_id'],))
            transactions = [dict(row) for row in cursor.fetchall()]
            
            order_value = 0
            for txn in transactions:
                print(f"  {txn['symbol']} x{txn['quantity']} @ ${txn['price']} = ${txn['net_value']}")
                order_value += txn['net_value']
            
            print(f"  Order net value: ${order_value}")
            if order['order_type'] == 'CLOSING':
                total_realized += order_value
        
        print(f"\nTotal realized from closing transactions: ${total_realized}")
        
        # 5. Get current positions for IBIT
        print("\n=== CURRENT IBIT POSITIONS ===")
        cursor.execute("""
            SELECT * FROM positions 
            WHERE underlying = 'IBIT' AND account_number = ?
            ORDER BY symbol
        """, (target_order['account_number'],))
        current_positions = [dict(row) for row in cursor.fetchall()]
        
        total_unrealized = 0
        for pos in current_positions:
            print(f"Position: {pos['symbol']}")
            print(f"  Quantity: {pos['quantity']} ({pos['quantity_direction']})")
            print(f"  Average Open Price: ${pos['average_open_price']}")
            print(f"  Market Value: ${pos['market_value']}")
            print(f"  Cost Basis: ${pos['cost_basis']}")
            print(f"  Unrealized P&L: ${pos['unrealized_pnl']}")
            print(f"  Strike: ${pos['strike_price']} {pos['option_type']}")
            print(f"  Expires: {pos['expires_at']}")
            
            if pos['unrealized_pnl']:
                total_unrealized += pos['unrealized_pnl']
            print()
        
        print(f"Total unrealized P&L: ${total_unrealized}")
        
        # 6. Check what the P&L calculation methods would return
        print("\n=== P&L CALCULATION ANALYSIS ===")
        print(f"Chain reported total P&L: ${chain_info['total_pnl']}")
        print(f"Chain reported realized P&L: ${chain_info['realized_pnl']}")
        print(f"Chain reported unrealized P&L: ${chain_info['unrealized_pnl']}")
        print()
        print(f"Sum of order P&L: ${total_order_pnl}")
        print(f"Calculated realized P&L: ${total_realized}")
        print(f"Calculated unrealized P&L: ${total_unrealized}")
        print(f"Calculated total: ${total_realized + total_unrealized}")
        
        # 7. Check what's displayed in the UI
        print("\n=== WHAT SHOULD BE DISPLAYED ===")
        print("According to the data:")
        print(f"  - Realized P&L: ${total_realized} (from closing transactions)")
        print(f"  - Unrealized P&L: ${total_unrealized} (from open positions)")
        print(f"  - Total P&L: ${total_realized + total_unrealized}")
        
        print("\nChain table shows:")
        print(f"  - Realized P&L: ${chain_info['realized_pnl']}")
        print(f"  - Unrealized P&L: ${chain_info['unrealized_pnl']}")
        print(f"  - Total P&L: ${chain_info['total_pnl']}")

if __name__ == "__main__":
    investigate_ibit_pnl()