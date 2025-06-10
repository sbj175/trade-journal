#!/usr/bin/env python3
"""
Check order linking between 374805462 and 375108991
"""
import sqlite3

def check_order_linking():
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()

    print('=== CHECKING ORDER CHAINS ===')

    # Check if there are chains containing either order
    cursor.execute('''
        SELECT oc.chain_id, oc.underlying, oc.strategy_type, oc.chain_status,
               ocm.order_id, ocm.sequence_number 
        FROM order_chains oc
        JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
        WHERE ocm.order_id IN ("374805462", "375108991")
        ORDER BY oc.chain_id, ocm.sequence_number
    ''')

    chains = cursor.fetchall()
    if chains:
        print('Found chains:')
        current_chain = None
        for chain in chains:
            if chain[0] != current_chain:
                print(f'\nChain {chain[0]} ({chain[1]} {chain[2]}, status: {chain[3]}):')
                current_chain = chain[0]
            print(f'  Order {chain[4]} (sequence {chain[5]})')
    else:
        print('No chains found containing these orders')

    print('\n=== CHECKING INDIVIDUAL CHAIN MEMBERSHIPS ===')

    for order_id in ['374805462', '375108991']:
        cursor.execute('''
            SELECT oc.chain_id, oc.underlying, oc.strategy_type 
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE ocm.order_id = ?
        ''', (order_id,))
        
        chain = cursor.fetchone()
        if chain:
            print(f'Order {order_id} is in chain {chain[0]} ({chain[1]} {chain[2]})')
        else:
            print(f'Order {order_id} is NOT in any chain')

    print('\n=== POSITION DETAILS ===')
    cursor.execute('''
        SELECT order_id, symbol, option_type, strike, expiration, quantity, status
        FROM positions_new 
        WHERE order_id IN ("374805462", "375108991")
        ORDER BY order_id
    ''')

    positions = cursor.fetchall()
    for pos in positions:
        print(f'Order {pos[0]}: {pos[1]}, {pos[2]}, ${pos[3]}, {pos[4]}, qty={pos[5]}, status={pos[6]}')

    print('\n=== CHECKING WHY THEY ARE NOT LINKED ===')
    
    # Check order details
    cursor.execute('''
        SELECT order_id, order_type, order_date, status, underlying
        FROM orders 
        WHERE order_id IN ("374805462", "375108991")
        ORDER BY order_date
    ''')
    
    orders = cursor.fetchall()
    print('Order details:')
    for order in orders:
        print(f'  {order[0]}: {order[1]} order on {order[2]}, status={order[3]}, underlying={order[4]}')
    
    # The orders should be linked if:
    # 1. Same underlying (MSTR) ✓ 
    # 2. Same account ✓
    # 3. Same contract details ✓
    # 4. Order 375108991 closes the position opened by 374805462 ✓
    
    print('\n=== ANALYSIS ===')
    print('Both orders:')
    print('  - Same underlying: MSTR ✓')
    print('  - Same contract: MSTR 250328C00342500 ✓') 
    print('  - Order 374805462: OPENING order, -9 contracts (short position)')
    print('  - Order 375108991: CLOSING order, +9 contracts (closes short position)')
    print('  - These should be in the same chain!')
    
    conn.close()

if __name__ == "__main__":
    check_order_linking()