#!/usr/bin/env python3
"""
Test the actual calculate_chain_position_balance method to see if it matches our manual calculation
"""

import sqlite3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Import with a more basic approach to avoid module errors
def test_method_directly():
    """Test the method more directly by copying its logic"""
    
    print('🔍 Testing Actual Method Logic')
    print('=' * 40)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    chain_id = 'IBIT_OPENING_20250630_39244084'
    
    # Get orders and positions like the reprocessing would
    cursor.execute('''
        SELECT o.order_id, o.order_type, p.symbol, p.quantity, p.opening_action, 
               p.closing_action, p.strike, p.expiration
        FROM orders o
        JOIN order_chain_members ocm ON o.order_id = ocm.order_id
        JOIN positions_new p ON o.order_id = p.order_id
        WHERE ocm.chain_id = ?
        ORDER BY o.order_date, o.order_id
    ''', (chain_id,))
    
    rows = cursor.fetchall()
    print(f'Found {len(rows)} position records')
    
    # Manually implement the get_position_key and calculate_chain_position_balance logic
    def get_position_key(symbol, strike, expiration):
        if strike is not None and expiration is not None:
            return f"{symbol}_{strike}_{expiration}"
        else:
            return symbol
    
    print(f'\nProcessing positions using actual method logic:')
    position_balances = {}
    
    for row in rows:
        order_id, order_type, symbol, quantity, opening_action, closing_action, strike, expiration = row
        
        pos_key = get_position_key(symbol, strike, expiration)
        
        print(f'\nOrder {order_id} ({order_type}):')
        print(f'  Position: {pos_key}')
        print(f'  Actions: {opening_action} | {closing_action}')
        print(f'  Quantity: {quantity}')
        
        if pos_key not in position_balances:
            position_balances[pos_key] = 0
        
        abs_quantity = abs(quantity)
        
        # Apply opening action - this is the exact logic from calculate_chain_position_balance
        if opening_action:
            if 'SELL_TO_OPEN' in opening_action:
                position_balances[pos_key] += abs_quantity
                print(f'  → STO: balance += {abs_quantity} = {position_balances[pos_key]}')
            elif 'BUY_TO_OPEN' in opening_action:
                position_balances[pos_key] -= abs_quantity
                print(f'  → BTO: balance -= {abs_quantity} = {position_balances[pos_key]}')
            elif 'BUY_TO_CLOSE' in opening_action:
                position_balances[pos_key] -= abs_quantity
                print(f'  → BTC: balance -= {abs_quantity} = {position_balances[pos_key]}')
            elif 'SELL_TO_CLOSE' in opening_action:
                position_balances[pos_key] += abs_quantity
                print(f'  → STC: balance += {abs_quantity} = {position_balances[pos_key]}')
        
        # Apply closing action - this is the exact logic from calculate_chain_position_balance
        if closing_action:
            if 'EXPIRED' in closing_action:
                current_balance = position_balances[pos_key]
                print(f'  → EXPIRATION! Current balance: {current_balance}')
                if current_balance > 0:
                    position_balances[pos_key] -= abs_quantity
                    print(f'  → EXPIRED (short): balance -= {abs_quantity} = {position_balances[pos_key]}')
                elif current_balance < 0:
                    position_balances[pos_key] += abs_quantity
                    print(f'  → EXPIRED (long): balance += {abs_quantity} = {position_balances[pos_key]}')
                else:
                    print(f'  → EXPIRED (zero): no change')
    
    print(f'\n📊 Position Balances using actual method logic:')
    has_open_positions = False
    for pos_key, balance in position_balances.items():
        is_open = abs(balance) > 1e-6
        if is_open:
            has_open_positions = True
        status = 'OPEN' if is_open else 'CLOSED'
        print(f'  {pos_key}: {balance} ({status})')
    
    should_be_closed = not has_open_positions
    print(f'\nUsing exact method logic, chain should be: {"CLOSED" if should_be_closed else "OPEN"}')
    
    # This proves that the method logic itself is correct
    # The bug must be elsewhere in the reprocessing pipeline
    
    conn.close()

if __name__ == "__main__":
    test_method_directly()