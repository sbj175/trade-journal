#!/usr/bin/env python3
"""
Find the opening order that matches the partial close contracts
"""
import sqlite3

def find_opening_order():
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()

    print('=== FINDING THE OPENING ORDER ===')
    cursor.execute('''
        SELECT order_id, order_type, order_date, total_quantity, status
        FROM orders 
        WHERE underlying = "MSTR" 
        AND order_date <= "2025-04-29"
        AND order_type = "OPENING"
        ORDER BY order_date DESC
    ''')

    opening_orders = cursor.fetchall()
    matching_opening = None
    
    for order in opening_orders:
        order_id = order[0]
        print(f'\nChecking Order {order_id}: {order[1]} on {order[2]}, qty={order[3]}, status={order[4]}')
        
        # Check if this order has the matching contract (MSTR 250509C00317500)
        cursor.execute('''
            SELECT symbol, option_type, strike, expiration, quantity, status
            FROM positions_new 
            WHERE order_id = ?
            AND symbol LIKE "MSTR%250509C00317500"
        ''', (order_id,))
        
        positions = cursor.fetchall()
        if positions:
            for pos in positions:
                print(f'  ✓ MATCH: {pos[0]}, qty={pos[4]}, status={pos[5]}')
                
                # If this is a -9 quantity position, it matches our closing orders
                if pos[4] == -9:
                    matching_opening = order_id
                    print(f'    🎯 This is likely the opening order being closed!')
                
                # Check if this opening order is in a chain
                cursor.execute('''
                    SELECT oc.chain_id, oc.chain_status, ocm.sequence_number
                    FROM order_chains oc
                    JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
                    WHERE ocm.order_id = ?
                ''', (order_id,))
                
                chain_info = cursor.fetchone()
                if chain_info:
                    print(f'    In chain: {chain_info[0]} (status: {chain_info[1]}, sequence: {chain_info[2]})')
                else:
                    print(f'    ❌ NOT in any chain!')

    if matching_opening:
        print(f'\n=== RECOMMENDED SOLUTION ===')
        print(f'Opening Order: {matching_opening} (-9 contracts)')
        print(f'Closing Orders: 381208759 (1 contract) + 381209221 (8 contracts)')
        print(f'Total closed: 9 contracts ✓')
        print()
        print('These should all be linked in the same chain:')
        print(f'1. {matching_opening} (OPENING)')
        print(f'2. 381208759 (CLOSING - partial)')  
        print(f'3. 381209221 (CLOSING - partial)')
        print()
        print('The chain detection logic needs to be enhanced to:')
        print('- Allow multiple CLOSING orders to be linked to the same OPENING order')
        print('- Recognize when partial closes sum up to fully close a position')
        print('- Set chain status to CLOSED when total closing quantity matches opening quantity')

    conn.close()

if __name__ == "__main__":
    find_opening_order()