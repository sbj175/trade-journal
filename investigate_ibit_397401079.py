#!/usr/bin/env python3
"""Investigate IBIT order 397401079 to understand partial close scenario"""

import sqlite3
from datetime import datetime

def investigate_order():
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()

    print('=== TRACKING OPENING POSITIONS FOR ORDER 397401079 ===')

    # The symbols that were closed in order 397401079
    closed_symbols = [
        'IBIT  251231C00061000',  # 1 BTC (bought to close)
        'IBIT  251231C00047000'   # 2 STC (sold to close)
    ]

    print('Closed in order 397401079:')
    print('  BUY_TO_CLOSE 1x IBIT  251231C00061000 (Dec 31 61 Call)')
    print('  SELL_TO_CLOSE 2x IBIT  251231C00047000 (Dec 31 47 Call)')
    print()

    # Track net positions for the chain
    chain_has_open_positions = False

    # Find all opening transactions for these symbols
    for symbol in closed_symbols:
        print(f'=== OPENING TRANSACTIONS FOR {symbol} ===')
        
        # Find all opening transactions (STO/BTO) for this symbol
        cursor.execute('''
            SELECT order_id, action, quantity, price, executed_at, transaction_sub_type
            FROM raw_transactions 
            WHERE symbol = ? 
            AND (action LIKE '%SELL_TO_OPEN%' OR action LIKE '%BUY_TO_OPEN%')
            ORDER BY executed_at
        ''', (symbol,))
        
        opening_txs = cursor.fetchall()
        total_opening_qty = 0
        
        if opening_txs:
            print('Opening transactions:')
            for tx in opening_txs:
                action = tx[1]
                qty = tx[2]
                if 'SELL_TO_OPEN' in action:
                    qty_sign = -qty
                else:
                    qty_sign = qty
                total_opening_qty += qty_sign
                print(f'  Order {tx[0]}: {action} {qty} @ ${tx[3]} on {tx[4]} (running total: {total_opening_qty})')
        else:
            print('No opening transactions found!')
        
        # Find all closing transactions for this symbol  
        cursor.execute('''
            SELECT order_id, action, quantity, price, executed_at, transaction_sub_type
            FROM raw_transactions 
            WHERE symbol = ? 
            AND (action LIKE '%SELL_TO_CLOSE%' OR action LIKE '%BUY_TO_CLOSE%')
            ORDER BY executed_at
        ''', (symbol,))
        
        closing_txs = cursor.fetchall()
        total_closing_qty = 0
        
        if closing_txs:
            print('Closing transactions:')
            for tx in closing_txs:
                action = tx[1]
                qty = tx[2]
                if 'SELL_TO_CLOSE' in action:
                    qty_sign = -qty
                else:
                    qty_sign = qty
                total_closing_qty += qty_sign
                print(f'  Order {tx[0]}: {action} {qty} @ ${tx[3]} on {tx[4]} (running total: {total_closing_qty})')
        
        net_position = total_opening_qty + total_closing_qty
        print(f'\nPosition Balance for {symbol}:')
        print(f'  Opening quantity: {total_opening_qty}')
        print(f'  Closing quantity: {total_closing_qty}')
        print(f'  Net remaining: {net_position}')
        status = 'OPEN' if net_position != 0 else 'CLOSED'
        print(f'  Status: {status}')
        
        if net_position != 0:
            chain_has_open_positions = True
        print()

    print('=== CHAIN STATUS ANALYSIS ===')
    print(f'Chain has open positions: {chain_has_open_positions}')
    print(f'Expected chain status: {"OPEN" if chain_has_open_positions else "CLOSED"}')
    
    # Check what the current system thinks about this chain
    print('\n=== CURRENT SYSTEM STATUS ===')
    
    # Check if this order is in the orders table
    cursor.execute('SELECT * FROM orders WHERE order_id = "397401079"')
    order_record = cursor.fetchone()
    if order_record:
        print(f'Order 397401079 found in orders table')
    else:
        print('Order 397401079 NOT found in orders table')
    
    # Check order chains for IBIT around this time
    cursor.execute('''
        SELECT oc.chain_id, oc.underlying, oc.chain_status, oc.total_pnl, oc.created_at
        FROM order_chains oc
        WHERE oc.underlying = "IBIT"
        AND oc.created_at BETWEEN "2025-07-20" AND "2025-07-30"
    ''')
    
    chains = cursor.fetchall()
    print(f'\nFound {len(chains)} IBIT chains in timeframe:')
    for chain in chains:
        print(f'  Chain {chain[0]}: {chain[1]} - Status: {chain[2]} - P&L: ${chain[3]:.2f} - Created: {chain[4]}')
        
        # Show members of this chain
        cursor.execute('''
            SELECT ocm.order_id, o.order_date, o.status
            FROM order_chain_members ocm
            JOIN orders o ON ocm.order_id = o.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date
        ''', (chain[0],))
        members = cursor.fetchall()
        for member in members:
            print(f'    Order {member[0]}: {member[1]} - {member[2]}')

    conn.close()

if __name__ == "__main__":
    investigate_order()