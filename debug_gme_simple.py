#!/usr/bin/env python3
"""
Simple debug script to investigate GME chain closing issue with order 374895150
"""
import sqlite3
import os

def investigate_gme_chain():
    """Investigate the GME chain that should have been closed by order 374895150"""
    
    db_path = "trade_journal.db"
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found!")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("=== Investigating GME Chain Issue with Order 374895150 ===\n")
        
        # 1. Check if order 374895150 exists
        print("1. Checking order 374895150...")
        cursor.execute("""
        SELECT order_id, underlying, order_date, status, order_type
        FROM orders 
        WHERE order_id = '374895150'
        """)
        
        order_result = cursor.fetchone()
        if order_result:
            print(f"   Order found: {order_result}")
            underlying = order_result[1]
            order_date = order_result[2]
        else:
            print("   Order 374895150 not found!")
            return
        
        # 2. Check positions for this order
        print(f"\n2. Checking positions for order 374895150...")
        cursor.execute("""
        SELECT position_id, symbol, quantity, opening_action, closing_action, 
               opening_price, closing_price, pnl, option_type, strike, expiration
        FROM positions_new 
        WHERE order_id = '374895150'
        ORDER BY symbol
        """)
        
        positions = cursor.fetchall()
        print(f"   Found {len(positions)} positions:")
        for pos in positions:
            print(f"     {pos}")
        
        # 3. Find all GME chains around this time
        print(f"\n3. Looking for GME chains around {order_date}...")
        cursor.execute("""
        SELECT chain_id, underlying, chain_status, total_pnl, 
               opening_date, closing_date, strategy_type
        FROM order_chains 
        WHERE underlying = ? 
        AND (closing_date IS NULL OR 
             ABS(JULIANDAY(closing_date) - JULIANDAY(?)) < 30)
        ORDER BY opening_date
        """, (underlying, order_date))
        
        chains = cursor.fetchall()
        print(f"   Found {len(chains)} GME chains:")
        for chain in chains:
            print(f"     Chain {chain[0]}: {chain[2]} - {chain[1]} - PnL: ${chain[3]} - {chain[4]} to {chain[5]}")
        
        # 4. Check chain memberships for order 374895150
        print(f"\n4. Checking chain membership for order 374895150...")
        cursor.execute("""
        SELECT ocm.chain_id, ocm.order_id, ocm.sequence_number, oc.chain_status
        FROM order_chain_members ocm
        JOIN order_chains oc ON ocm.chain_id = oc.chain_id
        WHERE ocm.order_id = '374895150'
        """)
        
        memberships = cursor.fetchall()
        print(f"   Found {len(memberships)} chain memberships:")
        for membership in memberships:
            print(f"     Chain {membership[0]}: Sequence = {membership[2]}, Status = {membership[3]}")
        
        # 5. Find open GME chains that might need closing
        print(f"\n5. Looking for open GME chains...")
        cursor.execute("""
        SELECT oc.chain_id, oc.underlying, oc.chain_status, oc.total_pnl, 
               oc.opening_date, oc.strategy_type, COUNT(*) as order_count
        FROM order_chains oc
        JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
        WHERE oc.underlying = ? AND oc.chain_status = 'OPEN'
        GROUP BY oc.chain_id
        ORDER BY oc.opening_date
        """, (underlying,))
        
        open_chains = cursor.fetchall()
        print(f"   Found {len(open_chains)} open GME chains:")
        for chain in open_chains:
            print(f"     Chain {chain[0]}: {chain[2]} - {chain[5]} - {chain[6]} orders")
            
            # Get orders in this chain
            cursor.execute("""
            SELECT o.order_id, o.order_date, o.status, ocm.sequence_number
            FROM orders o
            JOIN order_chain_members ocm ON o.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date
            """, (chain[0],))
            
            chain_orders = cursor.fetchall()
            for order in chain_orders:
                print(f"       Order {order[0]}: {order[1]} - {order[2]} - Sequence: {order[3]}")
        
        # 6. Check for position balances in open chains
        print(f"\n6. Checking position balances for open GME chains...")
        for chain in open_chains:
            chain_id = chain[0]
            print(f"\n   Chain {chain_id} position balance:")
            
            cursor.execute("""
            SELECT symbol, 
                   SUM(CASE WHEN opening_action LIKE '%BUY%' THEN quantity ELSE -quantity END) as net_quantity,
                   COUNT(*) as position_count
            FROM positions_new p
            JOIN order_chain_members ocm ON p.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            GROUP BY symbol
            HAVING net_quantity != 0
            """, (chain_id,))
            
            balances = cursor.fetchall()
            if balances:
                for balance in balances:
                    print(f"     {balance[0]}: Net Qty = {balance[1]}, Positions = {balance[2]}")
            else:
                print("     All positions balanced - chain should be closed!")
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    investigate_gme_chain()