#!/usr/bin/env python3
"""
Fix BTC actions that are actually expirations by checking raw transaction data
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json

def fix_expiration_actions():
    """
    Convert BTC actions back to EXPIRED when they are actually expirations
    based on raw transaction descriptions and sub-types
    """
    
    print("Converting BTC Actions Back to EXPIRED When Appropriate")
    print("=" * 60)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get all option legs with BTC actions
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price, quantity
        FROM option_legs 
        WHERE transaction_actions LIKE '%BTC%'
        ORDER BY trade_id, symbol
    ''')
    
    legs = cursor.fetchall()
    fixed_count = 0
    
    for leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price, quantity in legs:
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        if 'BTC' not in actions:
            continue
            
        # Check raw transactions for this symbol to see if BTC is actually expiration
        cursor.execute('''
            SELECT executed_at, action, description, transaction_sub_type, price
            FROM raw_transactions 
            WHERE symbol = ?
            AND (action LIKE '%BUY_TO_CLOSE%' OR action LIKE '%BTC%')
            ORDER BY executed_at
        ''', (symbol,))
        
        btc_transactions = cursor.fetchall()
        
        needs_fix = False
        for executed_at, action, description, sub_type, price in btc_transactions:
            desc_upper = str(description).upper()
            sub_type_upper = str(sub_type).upper()
            
            # Check if this BTC is actually an expiration
            if ('EXPIRATION' in desc_upper or 'EXPIRED' in desc_upper or
                'REMOVAL' in desc_upper and 'EXPIRATION' in desc_upper or
                'EXPIRATION' in sub_type_upper):
                needs_fix = True
                break
        
        if needs_fix:
            print(f"Converting BTC to EXPIRED for {symbol} in trade {trade_id}")
            print(f"  Current actions: {actions}")
            
            # Replace BTC with EXPIRED
            new_actions = []
            for action in actions:
                if action == 'BTC':
                    new_actions.append('EXPIRED')
                else:
                    new_actions.append(action)
            
            print(f"  → New actions: {new_actions}")
            
            # Update the leg
            cursor.execute('''
                UPDATE option_legs 
                SET transaction_actions = ?
                WHERE id = ?
            ''', (
                json.dumps(new_actions),
                leg_id
            ))
            
            fixed_count += 1
            print()
    
    conn.commit()
    conn.close()
    
    print(f"✅ Fixed {fixed_count} option legs to use EXPIRED instead of BTC")
    print("✅ Expiration actions will now show with proper ⏰ emblems")
    print()
    print("🔄 Refresh your browser to see the changes!")

if __name__ == "__main__":
    fix_expiration_actions()