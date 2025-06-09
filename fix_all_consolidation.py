#!/usr/bin/env python3
"""
Fix consolidation for all trades with multiple duplicate actions
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json
from collections import defaultdict

def fix_all_consolidation():
    """
    Fix all trades that have duplicate actions due to over-consolidation
    """
    
    print("Fixing All Transaction Consolidation Issues")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Find all option legs with duplicate actions
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price, quantity
        FROM option_legs 
        WHERE transaction_actions IS NOT NULL
    ''')
    
    legs = cursor.fetchall()
    fixed_count = 0
    
    for leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price, quantity in legs:
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        # Check if there are duplicate actions
        action_counts = {}
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1
        
        has_duplicates = any(count > 1 for count in action_counts.values())
        
        if not has_duplicates:
            continue
            
        print(f"Fixing {symbol} in trade {trade_id}")
        print(f"  Current actions: {actions}")
        print(f"  Action counts: {action_counts}")
        
        # Get raw transactions for this symbol
        cursor.execute('''
            SELECT executed_at, action, price, quantity, description, transaction_sub_type
            FROM raw_transactions 
            WHERE symbol = ?
            ORDER BY executed_at
        ''', (symbol,))
        
        raw_txs = cursor.fetchall()
        
        # Consolidate properly
        consolidated = consolidate_transactions_properly(raw_txs)
        
        new_actions = []
        new_timestamps = []
        final_exit_price = exit_price  # Keep existing exit price as fallback
        
        for action_type, data in consolidated.items():
            new_actions.append(action_type)
            new_timestamps.append(data['timestamps'][0])  # Use first timestamp
            
            # Update exit price for closing actions
            if action_type in ['BTC', 'STC', 'EXPIRED', 'ASSIGNED', 'EXERCISED', 'CASH_SETTLED']:
                if data['avg_price'] > 0:
                    final_exit_price = data['avg_price']
                elif action_type in ['EXPIRED', 'ASSIGNED']:
                    final_exit_price = 0.0
        
        print(f"  → New actions: {new_actions}")
        print(f"  → Exit price: ${final_exit_price}")
        
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
    
    print(f"✅ Fixed {fixed_count} option legs with consolidation issues")
    print("🔄 Refresh your browser to see the changes!")

def consolidate_transactions_properly(raw_txs):
    """
    Consolidate transactions by type, keeping only one entry per action type
    """
    consolidated = defaultdict(lambda: {
        'total_qty': 0,
        'total_value': 0,
        'timestamps': [],
        'avg_price': 0,
        'prices': []
    })
    
    for executed_at, action, price, qty, description, sub_type in raw_txs:
        normalized_action = normalize_action_type(action, description, sub_type)
        
        qty_val = abs(float(qty or 0))
        price_val = float(price or 0)
        
        consolidated[normalized_action]['total_qty'] += qty_val
        consolidated[normalized_action]['total_value'] += price_val * qty_val
        consolidated[normalized_action]['timestamps'].append(executed_at)
        consolidated[normalized_action]['prices'].append(price_val)
    
    # Calculate average prices
    for action_type, data in consolidated.items():
        if data['total_qty'] > 0 and data['total_value'] > 0:
            data['avg_price'] = data['total_value'] / data['total_qty']
        else:
            # For expiration/assignment, use 0
            data['avg_price'] = 0.0
    
    return consolidated

def normalize_action_type(action, description, sub_type):
    """Normalize action to standard type"""
    action_str = str(action).upper()
    desc_str = str(description).upper()
    sub_type_str = str(sub_type).upper()
    
    # Priority order: most specific first
    if ('EXPIRATION' in desc_str or 'EXPIRED' in desc_str or 
        'REMOVAL' in desc_str and 'EXPIRATION' in desc_str or
        'EXPIRATION' in sub_type_str):
        return 'EXPIRED'
    elif ('ASSIGNMENT' in desc_str or 'ASSIGNED' in desc_str or
          'ASSIGNMENT' in sub_type_str):
        return 'ASSIGNED'
    elif ('EXERCISE' in desc_str or 'EXERCISED' in desc_str or
          'EXERCISE' in sub_type_str):
        return 'EXERCISED'
    elif ('CASH SETTLEMENT' in desc_str or 'CASH SETTLED' in desc_str):
        return 'CASH_SETTLED'
    elif 'SELL_TO_OPEN' in action_str:
        return 'STO'
    elif 'BUY_TO_OPEN' in action_str:
        return 'BTO'
    elif 'BUY_TO_CLOSE' in action_str:
        return 'BTC'
    elif 'SELL_TO_CLOSE' in action_str:
        return 'STC'
    
    return action_str

if __name__ == "__main__":
    fix_all_consolidation()