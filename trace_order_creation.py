#!/usr/bin/env python3
"""
Trace how orders are created from transactions during reprocessing
"""

import sqlite3

def trace_order_creation():
    """Trace the order creation process"""
    
    print('🔍 Tracing Order Creation Process')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Let's look at how transactions are grouped
    print('1. Transaction Grouping Analysis:')
    print('-' * 40)
    
    # Get transactions for a specific IBIT position
    cursor.execute("""
        SELECT id, order_id, transaction_type, transaction_sub_type, 
               symbol, quantity, action, executed_at
        FROM raw_transactions 
        WHERE symbol = 'IBIT  250703C00063000'
        AND account_number = '5WZ28644'
        ORDER BY executed_at
    """)
    
    transactions = cursor.fetchall()
    print(f'All transactions for IBIT 250703C00063000 (Account 5WZ28644):')
    for tx in transactions:
        tx_id, order_id, tx_type, sub_type, symbol, qty, action, executed_at = tx
        print(f'  TX {tx_id}:')
        print(f'    Order ID: {order_id}')
        print(f'    Type: {tx_type} - {sub_type}')
        print(f'    Action: {action}, Qty: {qty}')
        print(f'    Date: {executed_at}')
        print()
    
    # Now let's see how the order grouping logic works
    print('\n2. Order Grouping Logic:')
    print('-' * 40)
    print('Transactions are grouped by order_id...')
    print('But expiration transactions have order_id = None!')
    print('So they get processed separately as SYSTEM_EXPIRATION orders.')
    
    # Check how positions are linked
    print('\n3. Position Linking Analysis:')
    print('-' * 40)
    
    # Get the opening position
    cursor.execute("""
        SELECT order_id, symbol, quantity, opening_action, closing_action
        FROM positions_new
        WHERE symbol = 'IBIT  250703C00063000'
        AND account_number = '5WZ28644'
        AND opening_action IS NOT NULL
    """)
    
    opening_positions = cursor.fetchall()
    print('Opening positions:')
    for pos in opening_positions:
        order_id, symbol, qty, open_act, close_act = pos
        print(f'  Order {order_id}: {symbol}')
        print(f'    Qty: {qty}, Open: {open_act}, Close: {close_act}')
    
    # Get the expiration position
    cursor.execute("""
        SELECT order_id, symbol, quantity, opening_action, closing_action
        FROM positions_new
        WHERE symbol = 'IBIT  250703C00063000'
        AND account_number = '5WZ28644'
        AND closing_action = 'EXPIRED'
    """)
    
    expiration_positions = cursor.fetchall()
    print('\nExpiration positions:')
    for pos in expiration_positions:
        order_id, symbol, qty, open_act, close_act = pos
        print(f'  Order {order_id}: {symbol}')
        print(f'    Qty: {qty}, Open: {open_act}, Close: {close_act}')
    
    print('\n4. The Problem:')
    print('-' * 40)
    print('The expiration position is in a SEPARATE order!')
    print('This means when calculate_chain_position_balance() runs:')
    print('  - It gets a list of Order objects')
    print('  - Each Order has its own positions list')
    print('  - The opening position is in one Order')
    print('  - The expiration position is in another Order')
    print('  - Both positions have the SAME position_key')
    print('  - The balance calculation should work correctly...')
    
    # Let's verify the chain contains both orders
    print('\n5. Chain Verification:')
    print('-' * 40)
    
    cursor.execute("""
        SELECT ocm.chain_id, ocm.order_id, ocm.sequence_number
        FROM order_chain_members ocm
        WHERE ocm.chain_id = 'IBIT_OPENING_20250630_39244050'
        ORDER BY ocm.sequence_number
    """)
    
    chain_members = cursor.fetchall()
    print('Chain members for IBIT_OPENING_20250630_39244050:')
    for member in chain_members:
        chain_id, order_id, seq = member
        print(f'  Seq {seq}: {order_id}')
    
    print('\n6. So why does the bug happen?')
    print('-' * 40)
    print('The chain DOES contain both orders.')
    print('The position balance calculation SHOULD work.')
    print('But during reprocessing, something goes wrong...')
    print('\nPossible issues:')
    print('  1. Order objects not fully populated with positions')
    print('  2. Position data missing required fields') 
    print('  3. Chain creation happens before all orders are linked')
    print('  4. Race condition in the processing order')
    
    conn.close()

if __name__ == "__main__":
    trace_order_creation()