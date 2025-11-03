#!/usr/bin/env python3
"""
Test position key generation
"""

import sqlite3

def test_position_keys():
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print('Testing Position Key Generation')
    print('=' * 50)
    
    # Get some positions from the problematic orders
    cursor.execute('''
        SELECT symbol, strike, expiration, opening_action, quantity
        FROM positions_new 
        WHERE order_id IN ('388512672', '397401079')
        ORDER BY order_id, symbol
    ''')
    
    positions = cursor.fetchall()
    
    for pos in positions:
        symbol, strike, exp, action, qty = pos
        
        # Test both old and new position key logic
        old_key = symbol  # Old logic
        
        # New logic
        if strike is not None and exp is not None:
            new_key = f'{symbol}_{strike}_{exp}'
        else:
            new_key = symbol
        
        print(f'Position: {symbol} ${strike} exp {exp}')
        print(f'  Action: {action} {qty}')
        print(f'  Old key: {old_key}')
        print(f'  New key: {new_key}')
        keys_different = old_key != new_key
        print(f'  Keys different: {keys_different}')
        print()
    
    print('The keys should be different now, which means the')
    print('position balance calculation should be more accurate.')
    
    conn.close()

if __name__ == "__main__":
    test_position_keys()