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
        # 1. Find the chain containing order 397401079
        print("=== FINDING IBIT CHAIN ===")
        chain_query = """
        SELECT DISTINCT chain_id 
        FROM orders 
        WHERE order_id = '397401079'
        """
        cursor = conn.cursor()
        cursor.execute(chain_query, ('397401079',))
        chain_result = [dict(row) for row in cursor.fetchall()]
        if not chain_result:
            print("ERROR: Order 397401079 not found!")
            return
        
        chain_id = chain_result[0]['chain_id']
        print(f"Chain ID: {chain_id}")
        
        # 2. Get all orders in this chain
        print("\n=== CHAIN ORDERS ===")
        orders_query = """
        SELECT order_id, underlying, executed_at, status, strategy, 
               realized_pnl, unrealized_pnl, total_pnl, is_opening, is_closing
        FROM orders 
        WHERE chain_id = ?
        ORDER BY executed_at
        """
        cursor.execute(orders_query, (chain_id,))
        orders = [dict(row) for row in cursor.fetchall()]
        
        for order in orders:
            print(f"Order {order['order_id']}:")
            print(f"  Executed: {order['executed_at']}")
            print(f"  Status: {order['status']}")
            print(f"  Strategy: {order['strategy']}")
            print(f"  Realized P&L: {order['realized_pnl']}")
            print(f"  Unrealized P&L: {order['unrealized_pnl']}")
            print(f"  Total P&L: {order['total_pnl']}")
            print(f"  Opening: {order['is_opening']}")
            print(f"  Closing: {order['is_closing']}")
            print()
        
        # 3. Get all positions in this chain
        print("=== CHAIN POSITIONS ===")
        positions_query = """
        SELECT p.position_id, p.order_id, p.symbol, p.instrument_type,
               p.quantity, p.price, p.value, p.open_date, p.close_date,
               p.pnl, p.status, p.closing_order_id
        FROM positions p
        JOIN orders o ON p.order_id = o.order_id
        WHERE o.chain_id = ?
        ORDER BY p.open_date, p.position_id
        """
        cursor.execute(positions_query, (chain_id,))
        positions = [dict(row) for row in cursor.fetchall()]
        
        for pos in positions:
            print(f"Position {pos['position_id']} (Order {pos['order_id']}):")
            print(f"  Symbol: {pos['symbol']}")
            print(f"  Type: {pos['instrument_type']}")
            print(f"  Quantity: {pos['quantity']}")
            print(f"  Price: {pos['price']}")
            print(f"  Value: {pos['value']}")
            print(f"  Open Date: {pos['open_date']}")
            print(f"  Close Date: {pos['close_date']}")
            print(f"  P&L: {pos['pnl']}")
            print(f"  Status: {pos['status']}")
            print(f"  Closing Order: {pos['closing_order_id']}")
            print()
        
        # 4. Get chain-level P&L from the chains table
        print("=== CHAIN-LEVEL P&L ===")
        chain_pnl_query = """
        SELECT realized_pnl, unrealized_pnl, total_pnl
        FROM chains
        WHERE chain_id = ?
        """
        cursor.execute(chain_pnl_query, (chain_id,))
        chain_pnl = [dict(row) for row in cursor.fetchall()]
        
        if chain_pnl:
            chain_data = chain_pnl[0]
            print(f"Chain Realized P&L: {chain_data['realized_pnl']}")
            print(f"Chain Unrealized P&L: {chain_data['unrealized_pnl']}")
            print(f"Chain Total P&L: {chain_data['total_pnl']}")
        else:
            print("No chain-level P&L data found")
        
        # 5. Show what positions are still open
        print("\n=== OPEN POSITIONS ===")
        open_positions = [p for p in positions if p['status'] == 'OPEN']
        for pos in open_positions:
            print(f"Position {pos['position_id']}: {pos['symbol']} x{pos['quantity']} @ {pos['price']}")
        
        # 6. Show what positions are closed
        print("\n=== CLOSED POSITIONS ===")
        closed_positions = [p for p in positions if p['status'] == 'CLOSED']
        for pos in closed_positions:
            print(f"Position {pos['position_id']}: {pos['symbol']} x{pos['quantity']} @ {pos['price']}")
            print(f"  Closed on: {pos['close_date']}")
            print(f"  P&L: {pos['pnl']}")
        
        # 7. Calculate totals manually
        print("\n=== MANUAL CALCULATIONS ===")
        total_realized = sum(float(p['pnl'] or 0) for p in closed_positions)
        print(f"Sum of closed position P&L: {total_realized}")
        
        total_order_realized = sum(float(o['realized_pnl'] or 0) for o in orders)
        total_order_unrealized = sum(float(o['unrealized_pnl'] or 0) for o in orders)
        total_order_total = sum(float(o['total_pnl'] or 0) for o in orders)
        
        print(f"Sum of order realized P&L: {total_order_realized}")
        print(f"Sum of order unrealized P&L: {total_order_unrealized}")
        print(f"Sum of order total P&L: {total_order_total}")

if __name__ == "__main__":
    investigate_ibit_pnl()