#!/usr/bin/env python3
"""
Debug script to investigate GME chain closing issue with order 374895150
"""
import sqlite3
from datetime import datetime
from src.database.db_manager import DatabaseManager

def investigate_gme_chain():
    """Investigate the GME chain that should have been closed by order 374895150"""
    
    with DatabaseManager() as db:
        print("=== Investigating GME Chain Issue with Order 374895150 ===\n")
        
        # 1. Check if order 374895150 exists
        print("1. Checking order 374895150...")
        order_query = """
        SELECT order_id, underlying_symbol, executed_at, status, order_type
        FROM orders 
        WHERE order_id = '374895150'
        """
        
        order_result = db.execute_query(order_query)
        if order_result:
            order = order_result[0]
            print(f"   Order found: {order}")
            underlying = order[1]
            executed_at = order[2]
        else:
            print("   Order 374895150 not found!")
            return
        
        # 2. Check positions for this order
        print(f"\n2. Checking positions for order 374895150...")
        positions_query = """
        SELECT position_id, symbol, quantity, opening_action, closing_action, 
               opening_price, closing_price, pnl, option_type, strike, expiration
        FROM positions_new 
        WHERE order_id = '374895150'
        ORDER BY symbol
        """
        
        positions = db.execute_query(positions_query)
        print(f"   Found {len(positions)} positions:")
        for pos in positions:
            print(f"     {pos}")
        
        # 3. Find all GME chains around this time
        print(f"\n3. Looking for GME chains around {executed_at}...")
        chains_query = """
        SELECT chain_id, underlying_symbol, status, total_pnl, 
               opening_date, closing_date, strategy_type
        FROM order_chains 
        WHERE underlying_symbol = ? 
        AND (closing_date IS NULL OR 
             ABS(JULIANDAY(closing_date) - JULIANDAY(?)) < 30)
        ORDER BY opening_date
        """
        
        chains = db.execute_query(chains_query, (underlying, executed_at))
        print(f"   Found {len(chains)} GME chains:")
        for chain in chains:
            print(f"     Chain {chain[0]}: {chain[2]} - {chain[1]} - PnL: ${chain[3]} - {chain[4]} to {chain[5]}")
        
        # 4. Check chain memberships for order 374895150
        print(f"\n4. Checking chain membership for order 374895150...")
        membership_query = """
        SELECT ocm.chain_id, ocm.order_id, ocm.role, oc.status as chain_status
        FROM order_chain_members ocm
        JOIN order_chains oc ON ocm.chain_id = oc.chain_id
        WHERE ocm.order_id = '374895150'
        """
        
        memberships = db.execute_query(membership_query)
        print(f"   Found {len(memberships)} chain memberships:")
        for membership in memberships:
            print(f"     Chain {membership[0]}: Role = {membership[2]}, Status = {membership[3]}")
        
        # 5. Find open GME chains that might need closing
        print(f"\n5. Looking for open GME chains...")
        open_chains_query = """
        SELECT chain_id, underlying_symbol, status, total_pnl, 
               opening_date, strategy_type, COUNT(*) as order_count
        FROM order_chains oc
        JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
        WHERE underlying_symbol = ? AND status = 'OPEN'
        GROUP BY chain_id
        ORDER BY opening_date
        """
        
        open_chains = db.execute_query(open_chains_query, (underlying,))
        print(f"   Found {len(open_chains)} open GME chains:")
        for chain in open_chains:
            print(f"     Chain {chain[0]}: {chain[2]} - {chain[5]} - {chain[6]} orders")
            
            # Get orders in this chain
            chain_orders_query = """
            SELECT o.order_id, o.executed_at, o.status, ocm.role
            FROM orders o
            JOIN order_chain_members ocm ON o.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.executed_at
            """
            
            chain_orders = db.execute_query(chain_orders_query, (chain[0],))
            for order in chain_orders:
                print(f"       Order {order[0]}: {order[1]} - {order[2]} - Role: {order[3]}")
        
        # 6. Check for position balances in open chains
        print(f"\n6. Checking position balances for open GME chains...")
        for chain in open_chains:
            chain_id = chain[0]
            print(f"\n   Chain {chain_id} position balance:")
            
            balance_query = """
            SELECT symbol, 
                   SUM(CASE WHEN opening_action LIKE '%BUY%' THEN quantity ELSE -quantity END) as net_quantity,
                   COUNT(*) as position_count
            FROM positions_new p
            JOIN order_chain_members ocm ON p.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            GROUP BY symbol
            HAVING net_quantity != 0
            """
            
            balances = db.execute_query(balance_query, (chain_id,))
            if balances:
                for balance in balances:
                    print(f"     {balance[0]}: Net Qty = {balance[1]}, Positions = {balance[2]}")
            else:
                print("     All positions balanced - chain should be closed!")

if __name__ == "__main__":
    investigate_gme_chain()