#!/usr/bin/env python3
"""
Verify the expiration position bug - positions with no opening action
"""

import sqlite3

def verify_expiration_position_bug():
    """Check if expiration positions have missing opening_action"""
    
    print('🔍 Verifying Expiration Position Bug')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get expiration positions
    cursor.execute("""
        SELECT o.order_id, p.symbol, p.quantity, p.opening_action, 
               p.closing_action, p.opening_price, p.closing_price
        FROM positions_new p
        JOIN orders o ON p.order_id = o.order_id
        WHERE o.order_id LIKE 'SYSTEM_EXPIRATION_%'
        AND p.symbol LIKE 'IBIT%'
        LIMIT 10
    """)
    
    print('SYSTEM_EXPIRATION positions:')
    print('-' * 50)
    positions = cursor.fetchall()
    
    for pos in positions:
        order_id, symbol, qty, open_act, close_act, open_price, close_price = pos
        print(f'Order: {order_id}')
        print(f'  Symbol: {symbol}')
        print(f'  Quantity: {qty}')
        print(f'  Opening Action: {open_act} (← THIS IS THE BUG!)')
        print(f'  Closing Action: {close_act}')
        print(f'  Opening Price: {open_price}')
        print(f'  Closing Price: {close_price}')
        print()
    
    print('\nTHE BUG:')
    print('-' * 50)
    print('Expiration positions have opening_action = None!')
    print('This means the position balance calculation sees:')
    print('  - No opening action to process')
    print('  - Only a closing action (EXPIRED)')
    print('  - But closing action requires a current balance to work with')
    print('  - Since there was no opening, the balance is 0')
    print('  - So the expiration has no effect!')
    
    # Let's trace through what happens
    print('\nPosition Balance Calculation for IBIT Chain:')
    print('-' * 50)
    
    # Simulate the calculation
    position_balances = {}
    
    # First, the opening order
    print('1. Opening Order (392440841):')
    print('   IBIT 250703C00063000: SELL_TO_OPEN 150')
    pos_key = 'IBIT  250703C00063000_63.0_2025-07-03'
    position_balances[pos_key] = 150  # Short position
    print(f'   Balance: {position_balances[pos_key]}')
    
    # Then, the expiration order
    print('\n2. Expiration Order (SYSTEM_EXPIRATION_372466522):')
    print('   IBIT 250703C00063000: opening_action=None, closing_action=EXPIRED')
    print('   Since opening_action is None, nothing happens!')
    print('   The closing_action (EXPIRED) is processed:')
    print(f'   Current balance: {position_balances[pos_key]}')
    print('   Since balance > 0 (short position), it would subtract 150')
    print('   BUT WAIT...')
    
    # The real bug
    print('\n3. THE REAL BUG:')
    print('   The expiration position has quantity but NO opening_action')
    print('   So when calculate_chain_position_balance processes it:')
    print('   - It skips the opening action processing (None)')
    print('   - It processes the closing action (EXPIRED)')
    print('   - But the position might not have the right data!')
    
    conn.close()

if __name__ == "__main__":
    verify_expiration_position_bug()