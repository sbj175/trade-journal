#!/usr/bin/env python3
"""
Investigate NVDA order and its chain status
"""

import sqlite3

def investigate_nvda_order():
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    order_id = '379904620'
    print(f'Investigating NVDA order: {order_id}')
    print('=' * 60)
    
    # Get order details
    cursor.execute('''
        SELECT order_date, order_type
        FROM orders 
        WHERE order_id = ?
    ''', (order_id,))
    
    order_info = cursor.fetchone()
    if order_info:
        order_date, order_type = order_info
        print(f'Order Date: {order_date}')
        print(f'Order Type: {order_type}')
    
    # Get all positions in this order
    cursor.execute('''
        SELECT symbol, quantity, opening_action, opening_price, opening_amount,
               option_type, strike, expiration
        FROM positions_new 
        WHERE order_id = ?
        ORDER BY symbol, strike
    ''', (order_id,))
    
    positions = cursor.fetchall()
    
    print(f'\nPositions in order:')
    for pos in positions:
        symbol, qty, action, price, amount, opt_type, strike, exp = pos
        print(f'  {action} {qty}x {symbol} ${strike} {opt_type}s exp {exp}')
        print(f'    Price: ${price}, Amount: ${amount}')
    
    # Find which chain this order belongs to
    cursor.execute('''
        SELECT ocm.chain_id 
        FROM order_chain_members ocm
        WHERE ocm.order_id = ?
    ''', (order_id,))
    
    chain_result = cursor.fetchone()
    if chain_result:
        chain_id = chain_result[0]
        print(f'\nBelongs to chain: {chain_id}')
        
        # Get chain status
        cursor.execute('''
            SELECT chain_status, opening_date, closing_date
            FROM order_chains 
            WHERE chain_id = ?
        ''', (chain_id,))
        
        chain_info = cursor.fetchone()
        if chain_info:
            status, open_date, close_date = chain_info
            print(f'Chain status: {status}')
            print(f'Chain dates: {open_date} to {close_date}')
        
        # Get ALL positions in this chain to analyze the position balance
        cursor.execute('''
            SELECT p.symbol, p.quantity, p.opening_action, p.closing_action, 
                   p.option_type, p.strike, p.expiration, p.order_id
            FROM positions_new p
            JOIN order_chain_members ocm ON p.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY p.expiration, p.strike, p.order_id
        ''', (chain_id,))
        
        all_positions = cursor.fetchall()
        
        print(f'\nAll positions in chain {chain_id}:')
        position_balances = {}
        
        for pos in all_positions:
            symbol, qty, open_action, close_action, opt_type, strike, exp, pos_order_id = pos
            print(f'\n  Order {pos_order_id}: {symbol} exp {exp}')
            print(f'    {open_action} {qty} | Close: {close_action or "None"}')
            
            # Calculate position balance like the code does
            pos_key = f'{symbol}_{strike}_{exp}'
            if pos_key not in position_balances:
                position_balances[pos_key] = 0
            
            quantity = abs(qty)
            
            # Apply opening action
            if open_action:
                if 'SELL_TO_OPEN' in open_action:
                    position_balances[pos_key] += quantity
                    print(f'    → STO: balance += {quantity} = {position_balances[pos_key]}')
                elif 'BUY_TO_OPEN' in open_action:
                    position_balances[pos_key] -= quantity
                    print(f'    → BTO: balance -= {quantity} = {position_balances[pos_key]}')
                elif 'BUY_TO_CLOSE' in open_action:
                    position_balances[pos_key] -= quantity
                    print(f'    → BTC: balance -= {quantity} = {position_balances[pos_key]}')
                elif 'SELL_TO_CLOSE' in open_action:
                    position_balances[pos_key] += quantity
                    print(f'    → STC: balance += {quantity} = {position_balances[pos_key]}')
            
            # Apply closing action if exists
            if close_action and 'EXPIRED' in close_action:
                current_balance = position_balances[pos_key]
                if current_balance > 0:
                    position_balances[pos_key] -= quantity
                    print(f'    → EXPIRED (short): balance -= {quantity} = {position_balances[pos_key]}')
                elif current_balance < 0:
                    position_balances[pos_key] += quantity
                    print(f'    → EXPIRED (long): balance += {quantity} = {position_balances[pos_key]}')
        
        print(f'\nFinal Position Balances:')
        has_open_positions = False
        for pos_key, balance in position_balances.items():
            is_open = abs(balance) > 0.001
            if is_open:
                has_open_positions = True
            status_text = 'OPEN' if is_open else 'CLOSED'
            print(f'  {pos_key}: {balance} ({status_text})')
        
        should_be_status = 'OPEN' if has_open_positions else 'CLOSED'
        print(f'\nChain should be: {should_be_status}')
        
        if chain_info[0] != should_be_status:
            print(f'❌ STATUS MISMATCH! Chain is {chain_info[0]} but should be {should_be_status}')
        else:
            print(f'✅ Chain status is correct')
    
    conn.close()

if __name__ == "__main__":
    investigate_nvda_order()