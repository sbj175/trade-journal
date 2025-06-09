#!/usr/bin/env python3
"""
Remove separate EXPIRED action lines and show them as emblems only
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json

def remove_separate_expiration_lines():
    """
    Remove EXPIRED actions as separate lines - they should only be emblems
    """
    
    print("Removing Separate Expiration Lines")
    print("=" * 40)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get all option legs with EXPIRED actions
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price, quantity
        FROM option_legs 
        WHERE transaction_actions LIKE '%EXPIRED%'
        ORDER BY trade_id, symbol
    ''')
    
    legs = cursor.fetchall()
    fixed_count = 0
    
    for leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price, quantity in legs:
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        if 'EXPIRED' not in actions:
            continue
            
        # Check if we have both opening actions and EXPIRED
        has_opening = any(action in ['STO', 'BTO'] for action in actions)
        has_expired = 'EXPIRED' in actions
        
        if has_opening and has_expired:
            print(f"Removing separate EXPIRED line for {symbol} in trade {trade_id}")
            print(f"  Current actions: {actions}")
            
            # Remove EXPIRED actions and their timestamps
            new_actions = []
            new_timestamps = []
            
            for i, action in enumerate(actions):
                if action != 'EXPIRED':
                    new_actions.append(action)
                    if i < len(timestamps):
                        new_timestamps.append(timestamps[i])
            
            print(f"  → New actions: {new_actions}")
            print(f"  → EXPIRED will show as ⏰ emblem based on exit_price = 0")
            
            # Update the leg - keep exit_price as 0 for expired options
            cursor.execute('''
                UPDATE option_legs 
                SET transaction_actions = ?,
                    transaction_timestamps = ?,
                    exit_price = 0.0
                WHERE id = ?
            ''', (
                json.dumps(new_actions),
                json.dumps(new_timestamps),
                leg_id
            ))
            
            fixed_count += 1
            print()
    
    conn.commit()
    conn.close()
    
    print(f"✅ Removed {fixed_count} separate EXPIRED action lines")
    print("✅ Expiration will now show as ⏰ emblem on opening transactions")
    print()
    print("🔄 Refresh your browser to see the changes!")

if __name__ == "__main__":
    remove_separate_expiration_lines()