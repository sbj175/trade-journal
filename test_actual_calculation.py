#!/usr/bin/env python3
"""
Test what actually happens in calculate_chain_position_balance with real data
"""

import sqlite3

def test_actual_calculation():
    """Test the actual calculation with real position data"""
    
    print('🔍 Testing Actual Position Balance Calculation')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get the actual positions as they exist in the database
    cursor.execute("""
        SELECT p.order_id, p.symbol, p.quantity, p.opening_action, 
               p.closing_action, p.strike, p.expiration
        FROM positions_new p
        JOIN order_chain_members ocm ON p.order_id = ocm.order_id
        WHERE ocm.chain_id = 'IBIT_OPENING_20250630_39244084'
        ORDER BY p.order_id
    """)
    
    positions = cursor.fetchall()
    
    print('Positions in chain IBIT_OPENING_20250630_39244084:')
    for pos in positions:
        order_id, symbol, qty, open_act, close_act, strike, exp = pos
        print(f'  Order {order_id}:')
        print(f'    Symbol: {symbol}, Qty: {qty}')
        print(f'    Opening: {open_act}, Closing: {close_act}')
    
    # Now simulate EXACTLY what calculate_chain_position_balance does
    print('\n' + '=' * 60)
    print('Simulating calculate_chain_position_balance logic:')
    print('-' * 40)
    
    position_balances = {}
    
    for pos in positions:
        order_id, symbol, quantity, opening_action, closing_action, strike, expiration = pos
        
        # Create position key
        if strike is not None and expiration is not None:
            pos_key = f"{symbol}_{strike}_{expiration}"
        else:
            pos_key = symbol
        
        if pos_key not in position_balances:
            position_balances[pos_key] = 0
        
        quantity = abs(quantity)
        
        print(f'\nProcessing position from {order_id}:')
        print(f'  Position key: {pos_key}')
        print(f'  Quantity: {quantity}')
        
        # Process opening action (EXACTLY as in the method)
        if opening_action:
            print(f'  Opening action: {opening_action}')
            if 'SELL_TO_OPEN' in opening_action:
                position_balances[pos_key] += quantity
                print(f'    → STO: balance += {quantity} = {position_balances[pos_key]}')
            elif 'BUY_TO_OPEN' in opening_action:
                position_balances[pos_key] -= quantity
                print(f'    → BTO: balance -= {quantity} = {position_balances[pos_key]}')
            elif 'BUY_TO_CLOSE' in opening_action:
                position_balances[pos_key] -= quantity
                print(f'    → BTC: balance -= {quantity} = {position_balances[pos_key]}')
            elif 'SELL_TO_CLOSE' in opening_action:
                position_balances[pos_key] += quantity
                print(f'    → STC: balance += {quantity} = {position_balances[pos_key]}')
        else:
            print(f'  No opening action')
        
        # Process closing action (EXACTLY as in the method)
        if closing_action:
            print(f'  Closing action: {closing_action}')
            if 'EXPIRED' in closing_action:
                current_balance = position_balances[pos_key]
                print(f'    Current balance before expiration: {current_balance}')
                if current_balance > 0:
                    position_balances[pos_key] -= quantity
                    print(f'    → EXPIRED (short): balance -= {quantity} = {position_balances[pos_key]}')
                elif current_balance < 0:
                    position_balances[pos_key] += quantity
                    print(f'    → EXPIRED (long): balance += {quantity} = {position_balances[pos_key]}')
                else:
                    print(f'    → EXPIRED (zero balance): no change')
        else:
            print(f'  No closing action')
    
    print('\n' + '=' * 60)
    print('Final position balances:')
    for pos_key, balance in position_balances.items():
        is_closed = abs(balance) < 1e-6
        print(f'  {pos_key}: {balance} ({"CLOSED" if is_closed else "OPEN"})')
    
    all_closed = all(abs(balance) < 1e-6 for balance in position_balances.values())
    print(f'\nChain should be: {"CLOSED" if all_closed else "OPEN"}')
    
    # Check actual status
    cursor.execute("SELECT chain_status FROM order_chains WHERE chain_id = 'IBIT_OPENING_20250630_39244084'")
    actual_status = cursor.fetchone()[0]
    print(f'Actual status in DB: {actual_status}')
    
    if all_closed and actual_status == 'OPEN':
        print('\n❌ BUG CONFIRMED: Chain should be CLOSED but shows OPEN')
        print('Even though the calculation works correctly!')
    
    conn.close()

if __name__ == "__main__":
    test_actual_calculation()