#!/usr/bin/env python3
"""Debug script to test MSTR chain termination logic"""

import sys
sys.path.append('.')
import sqlite3
from datetime import datetime, date

# Simulate the position balance tracking for the first two MSTR orders
conn = sqlite3.connect('trade_journal.db')
cursor = conn.cursor()

# Get the first two orders
cursor.execute('''
    SELECT o.order_id, o.order_date, o.order_type, o.total_pnl
    FROM orders o
    JOIN order_chain_members ocm ON o.order_id = ocm.order_id
    WHERE ocm.chain_id = 'MSTR_OPENING_20250327_37480546'
    ORDER BY o.order_date
    LIMIT 2
''')
orders = cursor.fetchall()

print("First 2 MSTR orders:")
for order in orders:
    print(f"  {order[0]} | {order[1]} | {order[2]} | ${order[3]:.2f}")

# Get positions for these orders
position_balances = {}
for order in orders:
    order_id = order[0]
    order_type = order[2]
    
    cursor.execute('''
        SELECT symbol, quantity, opening_action
        FROM positions_new
        WHERE order_id = ?
        ORDER BY symbol
    ''', (order_id,))
    positions = cursor.fetchall()
    
    print(f"\nOrder {order_id} ({order_type}) positions:")
    for pos in positions:
        symbol = pos[0]
        quantity = pos[1]
        action = pos[2]
        
        print(f"  {symbol} | Qty: {quantity} | Action: {action}")
        
        # Initialize position balance if not exists
        if symbol not in position_balances:
            position_balances[symbol] = 0
        
        # Apply balance logic
        if 'BUY_TO_OPEN' in action:
            position_balances[symbol] -= abs(quantity)  # Long position
            print(f"    BUY_TO_OPEN: balance -= {abs(quantity)} = {position_balances[symbol]}")
        elif 'SELL_TO_OPEN' in action:
            position_balances[symbol] += abs(quantity)  # Short position
            print(f"    SELL_TO_OPEN: balance += {abs(quantity)} = {position_balances[symbol]}")
        elif 'BUY_TO_CLOSE' in action:
            position_balances[symbol] -= abs(quantity)  # Close short position
            print(f"    BUY_TO_CLOSE: balance -= {abs(quantity)} = {position_balances[symbol]}")
        elif 'SELL_TO_CLOSE' in action:
            position_balances[symbol] += abs(quantity)  # Close long position
            print(f"    SELL_TO_CLOSE: balance += {abs(quantity)} = {position_balances[symbol]}")

print(f"\nFinal position balances: {position_balances}")

# Check if all positions are closed
all_closed = True
for pos_key, balance in position_balances.items():
    if abs(balance) > 0.01:
        all_closed = False
        print(f"Position {pos_key} has balance {balance} - NOT CLOSED")
    else:
        print(f"Position {pos_key} has balance {balance} - CLOSED")

print(f"\nAll positions closed: {all_closed}")

conn.close()