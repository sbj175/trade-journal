#!/usr/bin/env python3
"""
Fix expiration/assignment actions to be emblems on opening transactions
rather than separate transaction lines
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json

def fix_expiration_emblems():
    """
    Convert expiration/assignment actions to emblems on the opening transactions
    instead of showing them as separate lines
    """
    
    print("Converting Expiration Actions to Emblems")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get all option legs
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price, quantity
        FROM option_legs 
        ORDER BY trade_id, symbol
    ''')
    
    legs = cursor.fetchall()
    fixed_count = 0
    
    for leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price, quantity in legs:
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        if not actions:
            continue
            
        # Check if this leg has expiration/assignment actions that should be emblems
        closing_actions = []
        opening_actions = []
        closing_emblems = []
        
        for i, action in enumerate(actions):
            if action in ['EXPIRED', 'ASSIGNED', 'EXERCISED', 'CASH_SETTLED']:
                closing_emblems.append(action)
            elif action in ['BTC', 'STC']:
                closing_actions.append((action, timestamps[i] if i < len(timestamps) else None))
            else:  # BTO, STO
                opening_actions.append((action, timestamps[i] if i < len(timestamps) else None))
        
        # If we have both opening actions and expiration emblems (but no BTC/STC), 
        # then the expiration should be an emblem, not a separate line
        if opening_actions and closing_emblems and not closing_actions:
            print(f"Converting emblems for {symbol} in trade {trade_id}")
            print(f"  Current actions: {actions}")
            print(f"  Opening actions: {[a[0] for a in opening_actions]}")
            print(f"  Closing emblems: {closing_emblems}")
            
            # Create new actions list with only opening actions
            # The emblems will be handled by the frontend based on exit_price and trade status
            new_actions = [action for action, timestamp in opening_actions]
            new_timestamps = [timestamp for action, timestamp in opening_actions]
            
            # Keep exit price as 0 for expired options
            final_exit_price = 0.0 if closing_emblems else exit_price
            
            print(f"  → New actions: {new_actions}")
            print(f"  → Exit price: ${final_exit_price}")
            print(f"  → Emblems will show based on trade status and exit price")
            
            # Update the leg
            cursor.execute('''
                UPDATE option_legs 
                SET transaction_actions = ?,
                    transaction_timestamps = ?,
                    exit_price = ?
                WHERE id = ?
            ''', (
                json.dumps(new_actions),
                json.dumps(new_timestamps),
                final_exit_price,
                leg_id
            ))
            
            fixed_count += 1
            print()
    
    conn.commit()
    conn.close()
    
    print(f"✅ Fixed {fixed_count} option legs to use emblems instead of separate lines")
    print("✅ Expiration/assignment indicators will now show as emblems on opening transactions")
    print()
    print("🔄 Refresh your browser to see the changes!")

if __name__ == "__main__":
    fix_expiration_emblems()