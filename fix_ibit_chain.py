#!/usr/bin/env python3
"""
Direct fix for the IBIT chain status
"""

import sqlite3
from datetime import date

def fix_ibit_chain():
    """Directly fix the IBIT chain status in the database"""
    
    print('🔧 Fixing IBIT Chain Status')
    print('=' * 50)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    chain_id = 'IBIT_OPENING_20250630_39244084'
    
    # Check current status
    cursor.execute('SELECT chain_status, closing_date FROM order_chains WHERE chain_id = ?', (chain_id,))
    result = cursor.fetchone()
    if result:
        current_status, current_closing_date = result
        print(f'Current status: {current_status} (closing: {current_closing_date})')
    else:
        print('Chain not found!')
        return
    
    # Calculate what the status should be using our manual logic
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
    
    # Manual position balance calculation
    position_balances = {}
    latest_order_date = None
    
    for pos in positions:
        symbol, qty, open_action, close_action, strike, exp, order_id, order_date, order_type = pos
        
        # Track latest order date for closing date
        if order_date:
            if isinstance(order_date, str):
                order_date = datetime.strptime(order_date, '%Y-%m-%d').date()
            if latest_order_date is None or order_date > latest_order_date:
                latest_order_date = order_date
        
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
            if current_balance > 0:
                position_balances[pos_key] -= quantity
            elif current_balance < 0:
                position_balances[pos_key] += quantity
    
    # Determine if chain should be closed
    has_open_positions = any(abs(balance) > 1e-6 for balance in position_balances.values())
    should_be_closed = not has_open_positions
    correct_status = 'CLOSED' if should_be_closed else 'OPEN'
    
    print(f'Position balances: {position_balances}')
    print(f'Should be: {correct_status}')
    
    if correct_status != current_status:
        print(f'Fixing: {current_status} → {correct_status}')
        
        # Update the chain status
        closing_date = latest_order_date if should_be_closed else None
        cursor.execute('''
            UPDATE order_chains 
            SET chain_status = ?, closing_date = ?
            WHERE chain_id = ?
        ''', (correct_status, closing_date, chain_id))
        
        conn.commit()
        print(f'✅ Fixed chain status to {correct_status}')
    else:
        print(f'✅ Chain status is already correct: {correct_status}')
    
    conn.close()

if __name__ == "__main__":
    from datetime import datetime
    fix_ibit_chain()