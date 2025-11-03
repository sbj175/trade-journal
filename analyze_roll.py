#!/usr/bin/env python3
"""
Analyze roll order to understand per-share credit/debit calculation
"""

import sqlite3

def analyze_roll_order():
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    order_id = '394522472'
    print(f'Analyzing roll order: {order_id}')
    print('=' * 50)
    
    # Get order details
    cursor.execute('''
        SELECT order_date, order_type, total_amount
        FROM orders 
        WHERE order_id = ?
    ''', (order_id,))
    
    order_info = cursor.fetchone()
    if order_info:
        order_date, order_type, total_amount = order_info
        print(f'Order Date: {order_date}')
        print(f'Order Type: {order_type}')
        print(f'Total Amount: ${total_amount}')
    
    # Get all positions in this roll
    cursor.execute('''
        SELECT symbol, quantity, opening_action, opening_price, opening_amount,
               option_type, strike, expiration
        FROM positions_new 
        WHERE order_id = ?
        ORDER BY opening_action, strike
    ''', (order_id,))
    
    positions = cursor.fetchall()
    
    print(f'\nPositions in roll:')
    total_amount = 0
    total_quantity = 0
    
    for pos in positions:
        symbol, qty, action, price, amount, opt_type, strike, exp = pos
        print(f'  {action} {qty}x {symbol} ${strike} {opt_type}s exp {exp}')
        print(f'    Price: ${price}, Amount: ${amount}')
        
        total_amount += amount or 0
        total_quantity += abs(qty)
    
    print(f'\nRoll Summary:')
    print(f'  Total Amount: ${total_amount:.2f}')
    print(f'  Total Quantity: {total_quantity} contracts')
    
    if total_quantity > 0:
        per_share_amount = total_amount / total_quantity
        per_contract_amount = per_share_amount * 100  # Convert to per contract
        
        roll_type = 'Credit' if total_amount > 0 else 'Debit'
        
        print(f'  Per Contract: ${abs(per_contract_amount):.2f} {roll_type.lower()}')
        print(f'  Per Share: ${abs(per_share_amount):.4f} {roll_type.lower()}')
        
        # Format for display (like .23 credit)
        display_amount = abs(per_share_amount)
        print(f'\nDisplay format: {display_amount:.2f} {roll_type.lower()}')
    
    conn.close()

if __name__ == "__main__":
    analyze_roll_order()