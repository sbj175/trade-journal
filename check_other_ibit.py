#!/usr/bin/env python3
"""
Check another IBIT chain with expiration
"""

import sqlite3

def check_ibit_chain():
    """Check another IBIT chain that should be closed"""
    
    print('🔍 Checking Another IBIT Chain')
    print('=' * 50)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    chain_id = 'IBIT_OPENING_20250630_39244050'  # This should also be closed (expired 2025-07-03)
    
    # Check current status
    cursor.execute('SELECT chain_status, closing_date FROM order_chains WHERE chain_id = ?', (chain_id,))
    result = cursor.fetchone()
    if result:
        current_status, current_closing_date = result
        print(f'Current status: {current_status} (closing: {current_closing_date})')
    else:
        print('Chain not found!')
        return
    
    # Get positions
    cursor.execute('''
        SELECT p.symbol, p.quantity, p.opening_action, p.closing_action, 
               p.strike, p.expiration, p.order_id, o.order_date, o.order_type
        FROM positions_new p
        JOIN order_chain_members ocm ON p.order_id = ocm.order_id
        JOIN orders o ON p.order_id = o.order_id
        WHERE ocm.chain_id = ?
        ORDER BY o.order_date, p.order_id
    ''', (chain_id,))
    
    positions = cursor.fetchall()
    print(f'Found {len(positions)} positions:')
    
    # Manual position balance calculation
    position_balances = {}
    
    for pos in positions:
        symbol, qty, open_action, close_action, strike, exp, order_id, order_date, order_type = pos
        
        print(f'  {order_id} ({order_type}): {symbol} {open_action} | {close_action} ({qty})')
        
        # Create position key
        if strike is not None and exp is not None:
            pos_key = f"{symbol}_{strike}_{exp}"
        else:
            pos_key = symbol
        
        if pos_key not in position_balances:
            position_balances[pos_key] = 0
        
        quantity = abs(qty)
        
        # Apply opening action
        if open_action:
            if 'SELL_TO_OPEN' in open_action:
                position_balances[pos_key] += quantity
            elif 'BUY_TO_OPEN' in open_action:
                position_balances[pos_key] -= quantity
            elif 'BUY_TO_CLOSE' in open_action:
                position_balances[pos_key] -= quantity
            elif 'SELL_TO_CLOSE' in open_action:
                position_balances[pos_key] += quantity
        
        # Apply closing action
        if close_action and 'EXPIRED' in close_action:
            current_balance = position_balances[pos_key]
            print(f'    → EXPIRATION! Balance before: {current_balance}')
            if current_balance > 0:
                position_balances[pos_key] -= quantity
                print(f'    → EXPIRED (short): -{quantity} = {position_balances[pos_key]}')
            elif current_balance < 0:
                position_balances[pos_key] += quantity
                print(f'    → EXPIRED (long): +{quantity} = {position_balances[pos_key]}')
    
    # Check if should be closed
    has_open_positions = any(abs(balance) > 1e-6 for balance in position_balances.values())
    should_be_closed = not has_open_positions
    correct_status = 'CLOSED' if should_be_closed else 'OPEN'
    
    print(f'\nPosition balances: {position_balances}')
    print(f'Should be: {correct_status}')
    print(f'Currently: {current_status}')
    
    if correct_status != current_status:
        print(f'❌ MISMATCH! This chain also has the expiration bug')
    else:
        print(f'✅ Chain status is correct')
    
    conn.close()

if __name__ == "__main__":
    check_ibit_chain()