#!/usr/bin/env python3
"""
Investigate how expiration transactions are processed during order creation
"""

import sqlite3

def investigate_expiration_processing():
    """Trace how expiration transactions become orders"""
    
    print('🔍 Investigating Expiration Transaction Processing')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Find an IBIT expiration transaction
    cursor.execute("""
        SELECT id, order_id, transaction_type, transaction_sub_type, 
               description, symbol, quantity, action, executed_at
        FROM raw_transactions 
        WHERE symbol LIKE 'IBIT%' 
        AND transaction_sub_type = 'Expiration'
        LIMIT 5
    """)
    
    print('Sample IBIT Expiration Transactions:')
    print('-' * 40)
    exp_transactions = cursor.fetchall()
    
    for tx in exp_transactions:
        tx_id, order_id, tx_type, sub_type, desc, symbol, qty, action, executed_at = tx
        print(f'TX ID: {tx_id}')
        print(f'  Order ID: {order_id} (Note: This is None!)')
        print(f'  Symbol: {symbol}')
        print(f'  Quantity: {qty}')
        print(f'  Action: {action}')
        print(f'  Description: {desc}')
        print()
    
    # Now check what orders were created from these transactions
    print('\n' + '=' * 60)
    print('Corresponding Orders in the orders table:')
    print('-' * 40)
    
    # Check for SYSTEM_EXPIRATION orders
    cursor.execute("""
        SELECT order_id, account_number, underlying, order_type, 
               order_date, strategy_type, status
        FROM orders 
        WHERE order_id LIKE 'SYSTEM_EXPIRATION_%'
        AND underlying = 'IBIT'
        ORDER BY order_date DESC
        LIMIT 5
    """)
    
    system_orders = cursor.fetchall()
    for order in system_orders:
        order_id, account, underlying, order_type, order_date, strategy, status = order
        print(f'Order ID: {order_id}')
        print(f'  Type: {order_type}')
        print(f'  Date: {order_date}')
        
        # Check what positions are in this order
        cursor.execute("""
            SELECT symbol, quantity, opening_action, closing_action
            FROM positions_new
            WHERE order_id = ?
        """, (order_id,))
        
        positions = cursor.fetchall()
        print(f'  Positions: {len(positions)}')
        for pos in positions:
            symbol, qty, open_act, close_act = pos
            print(f'    {symbol}: qty={qty}, open={open_act}, close={close_act}')
        print()
    
    # Now let's trace a specific example through the chain
    print('\n' + '=' * 60)
    print('Tracing IBIT 250703C00063000 Expiration:')
    print('-' * 40)
    
    # Find the raw transaction
    cursor.execute("""
        SELECT id, account_number, executed_at, quantity, action
        FROM raw_transactions 
        WHERE symbol = 'IBIT  250703C00063000'
        AND transaction_sub_type = 'Expiration'
    """)
    
    exp_txs = cursor.fetchall()
    print(f'Found {len(exp_txs)} expiration transactions for this symbol:')
    for tx in exp_txs:
        tx_id, account, executed_at, qty, action = tx
        print(f'  TX {tx_id}: Account {account}, Qty {qty}, Action {action}')
    
    # Find the SYSTEM_EXPIRATION order
    cursor.execute("""
        SELECT o.order_id, o.account_number, o.order_type, p.quantity, 
               p.opening_action, p.closing_action
        FROM orders o
        JOIN positions_new p ON o.order_id = p.order_id
        WHERE p.symbol = 'IBIT  250703C00063000'
        AND o.order_id LIKE 'SYSTEM_EXPIRATION_%'
    """)
    
    system_exp_orders = cursor.fetchall()
    print(f'\nFound {len(system_exp_orders)} SYSTEM_EXPIRATION orders for this symbol:')
    for order in system_exp_orders:
        order_id, account, order_type, qty, open_act, close_act = order
        print(f'  {order_id}: Account {account}, Qty {qty}')
        print(f'    Opening: {open_act}, Closing: {close_act}')
    
    # Find the original opening order
    cursor.execute("""
        SELECT o.order_id, o.account_number, o.order_type, p.quantity, 
               p.opening_action, p.closing_action
        FROM orders o
        JOIN positions_new p ON o.order_id = p.order_id
        WHERE p.symbol = 'IBIT  250703C00063000'
        AND o.order_type = 'OPENING'
    """)
    
    opening_orders = cursor.fetchall()
    print(f'\nFound {len(opening_orders)} OPENING orders for this symbol:')
    for order in opening_orders:
        order_id, account, order_type, qty, open_act, close_act = order
        print(f'  {order_id}: Account {account}, Qty {qty}')
        print(f'    Opening: {open_act}, Closing: {close_act}')
    
    # Check chain membership
    print('\n' + '=' * 60)
    print('Chain Membership Analysis:')
    print('-' * 40)
    
    # Find all chains that include orders for this symbol
    cursor.execute("""
        SELECT DISTINCT oc.chain_id, oc.chain_status, 
               GROUP_CONCAT(ocm.order_id, ', ') as order_ids
        FROM order_chains oc
        JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
        JOIN orders o ON ocm.order_id = o.order_id
        JOIN positions_new p ON o.order_id = p.order_id
        WHERE p.symbol = 'IBIT  250703C00063000'
        GROUP BY oc.chain_id, oc.chain_status
    """)
    
    chains = cursor.fetchall()
    for chain in chains:
        chain_id, status, order_ids = chain
        print(f'Chain: {chain_id} (Status: {status})')
        print(f'  Orders: {order_ids}')
    
    conn.close()

if __name__ == "__main__":
    investigate_expiration_processing()