#!/usr/bin/env python3
"""
Fix missing closing transactions in trade legs for roll chains
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json
from datetime import datetime

def fix_missing_closing_transactions():
    """
    Find and fix cases where closing transactions exist in raw_transactions
    but are missing from the option_legs transaction_actions
    """
    
    print("Fixing Missing Closing Transactions")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get all option legs
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price
        FROM option_legs 
        ORDER BY trade_id, symbol
    ''')
    
    legs = cursor.fetchall()
    print(f"Processing {len(legs)} option legs...")
    print()
    
    fixes_made = 0
    
    for leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price in legs:
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        # Skip if already has closing transactions
        has_closing = any(action in ['BTC', 'STC', 'EXPIRED', 'ASSIGNED', 'EXERCISED', 'CASH_SETTLED'] 
                         for action in actions)
        
        if has_closing:
            continue
            
        # Find all raw transactions for this symbol
        cursor.execute('''
            SELECT executed_at, action, price, quantity, description, transaction_sub_type
            FROM raw_transactions 
            WHERE symbol = ?
            ORDER BY executed_at
        ''', (symbol,))
        
        raw_txs = cursor.fetchall()
        
        if not raw_txs:
            continue
            
        # Separate opening and closing transactions
        opening_txs = []
        closing_txs = []
        
        for executed_at, action, price, quantity, description, sub_type in raw_txs:
            action_str = str(action)
            sub_type_str = str(sub_type)
            desc_str = str(description)
            
            # Determine if this is a closing transaction
            is_closing = (
                'CLOSE' in action_str.upper() or
                'BTC' in action_str.upper() or  
                'STC' in action_str.upper() or
                'CLOSE' in sub_type_str.upper() or
                'CLOSE' in desc_str.upper() or
                'EXPIRATION' in desc_str.upper() or
                'ASSIGNMENT' in desc_str.upper() or
                'EXERCISE' in desc_str.upper()
            )
            
            if is_closing:
                closing_txs.append((executed_at, action, price, quantity, description, sub_type))
            else:
                opening_txs.append((executed_at, action, price, quantity, description, sub_type))
        
        # If we have closing transactions but they're not in the leg, add them
        if closing_txs and len(actions) < len(opening_txs) + len(closing_txs):
            print(f"Fixing {symbol} in trade {trade_id}")
            print(f"  Current actions: {actions}")
            print(f"  Opening transactions: {len(opening_txs)}")
            print(f"  Closing transactions: {len(closing_txs)}")
            
            # Rebuild actions and timestamps
            new_actions = []
            new_timestamps = []
            
            # Add opening transactions
            for executed_at, action, price, quantity, description, sub_type in opening_txs:
                normalized_action = normalize_action(action, description, sub_type)
                new_actions.append(normalized_action)
                new_timestamps.append(executed_at)
            
            # Add closing transactions  
            exit_price_candidate = None
            for executed_at, action, price, quantity, description, sub_type in closing_txs:
                normalized_action = normalize_action(action, description, sub_type)
                new_actions.append(normalized_action)
                new_timestamps.append(executed_at)
                
                # Use the price from closing transaction as exit price
                if price is not None and price != 0:
                    exit_price_candidate = float(price)
                elif exit_price_candidate is None:
                    exit_price_candidate = 0.0
            
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
                exit_price_candidate,
                leg_id
            ))
            
            print(f"  → Updated actions: {new_actions}")
            print(f"  → Exit price: ${exit_price_candidate}")
            print()
            
            fixes_made += 1
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print(f"✅ Fixed {fixes_made} option legs")
    print("✅ Missing closing transactions have been added")
    print()
    print("🔄 Refresh your browser to see the changes!")

def normalize_action(action, description, sub_type):
    """Normalize action string"""
    action_str = str(action).upper()
    desc_str = str(description).upper()
    sub_type_str = str(sub_type).upper()
    
    # Check for specific patterns
    if 'CASH SETTLEMENT' in desc_str or 'CASH SETTLED' in desc_str:
        return 'CASH_SETTLED'
    elif 'ASSIGNMENT' in desc_str or 'ASSIGNED' in desc_str:
        return 'ASSIGNED'
    elif 'EXPIRATION' in desc_str or 'EXPIRED' in desc_str:
        return 'EXPIRED'
    elif 'EXERCISE' in desc_str or 'EXERCISED' in desc_str:
        return 'EXERCISED'
    elif 'REMOVAL' in desc_str and 'EXPIRATION' in desc_str:
        return 'EXPIRED'
    elif 'BUY_TO_CLOSE' in action_str or 'BTC' in action_str:
        return 'BTC'
    elif 'SELL_TO_CLOSE' in action_str or 'STC' in action_str:
        return 'STC'
    elif 'BUY_TO_OPEN' in action_str or 'BTO' in action_str:
        return 'BTO'
    elif 'SELL_TO_OPEN' in action_str or 'STO' in action_str:
        return 'STO'
    elif 'CLOSE' in sub_type_str:
        if 'BUY' in action_str:
            return 'BTC'
        elif 'SELL' in action_str:
            return 'STC'
    
    return action_str

if __name__ == "__main__":
    fix_missing_closing_transactions()