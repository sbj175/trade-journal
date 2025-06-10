#!/usr/bin/env python3
"""
Check the partial close case with orders 381209221 and 381208759
"""
import sqlite3

def check_partial_closes():
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()

    print('=== CHECKING ORDER CHAINS ===')
    cursor.execute('''
        SELECT oc.chain_id, oc.underlying, oc.strategy_type, oc.chain_status,
               ocm.order_id, ocm.sequence_number 
        FROM order_chains oc
        JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
        WHERE ocm.order_id IN ("381209221", "381208759")
        ORDER BY oc.chain_id, ocm.sequence_number
    ''')

    chains = cursor.fetchall()
    if chains:
        current_chain = None
        for chain in chains:
            if chain[0] != current_chain:
                print(f'Chain {chain[0]} ({chain[1]} {chain[2]}, status: {chain[3]}):')
                current_chain = chain[0]
            print(f'  Order {chain[4]} (sequence {chain[5]})')
    else:
        print('No chains found containing these orders')

    print()
    print('=== LOOKING FOR OPENING ORDER ===')
    # Look for the opening order that these two orders are closing
    cursor.execute('''
        SELECT order_id, order_type, order_date, total_quantity, status
        FROM orders 
        WHERE underlying = "MSTR" 
        AND order_date <= "2025-04-29"
        AND order_type = "OPENING"
        ORDER BY order_date DESC
        LIMIT 5
    ''')

    opening_orders = cursor.fetchall()
    for order in opening_orders:
        print(f'Order {order[0]}: {order[1]} on {order[2]}, qty={order[3]}, status={order[4]}')
        
        # Check positions for this opening order
        cursor.execute('''
            SELECT symbol, option_type, strike, expiration, quantity, status
            FROM positions_new 
            WHERE order_id = ?
            AND symbol LIKE "MSTR%250509C00317500"
        ''', (order[0],))
        
        positions = cursor.fetchall()
        for pos in positions:
            print(f'  Position: {pos[0]}, qty={pos[4]}, status={pos[5]}')

    print()
    print('=== RAW TRANSACTION DETAILS ===')
    cursor.execute('''
        SELECT order_id, action, quantity, price, executed_at
        FROM raw_transactions 
        WHERE order_id IN ("381209221", "381208759")
        ORDER BY order_id, executed_at
    ''')
    
    transactions = cursor.fetchall()
    for tx in transactions:
        print(f'Order {tx[0]}: {tx[1]}, qty={tx[2]}, price=${tx[3]}, time={tx[4]}')

    print()
    print('=== ANALYSIS ===')
    print('This appears to be a case where:')
    print('- A single position was closed by TWO separate closing orders')
    print('- Order 381208759: 1 contract closed')
    print('- Order 381209221: 8 contracts closed') 
    print('- Total: 9 contracts closed (likely matching an original -9 contract short position)')
    print()
    print('Current system issue:')
    print('- Both orders are marked as separate CLOSING orders')
    print('- They may not be properly linked to the original OPENING order')
    print('- Chain detection logic needs to handle multiple CLOSING orders for same position')

    conn.close()

if __name__ == "__main__":
    check_partial_closes()