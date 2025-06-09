#!/usr/bin/env python3
"""
Fix transaction consolidation logic - consolidate multiple transactions 
of the same type into single actions with proper quantities
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json
from datetime import datetime
from collections import defaultdict

def fix_transaction_consolidation():
    """
    Fix over-consolidation of transactions - properly group and consolidate
    transactions of the same type while maintaining accurate quantities
    """
    
    print("Fixing Transaction Consolidation Logic")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Focus on the specific problematic trade first
    target_trade = 'IBIT_20250528_2legs_959'
    
    # Get the option leg for this trade
    cursor.execute('''
        SELECT id, trade_id, symbol, transaction_actions, transaction_timestamps,
               entry_price, exit_price, quantity
        FROM option_legs 
        WHERE trade_id = ?
    ''', (target_trade,))
    
    leg = cursor.fetchone()
    if not leg:
        print(f"❌ Trade {target_trade} not found")
        return
    
    leg_id, trade_id, symbol, actions_json, timestamps_json, entry_price, exit_price, quantity = leg
    actions = json.loads(actions_json) if actions_json else []
    timestamps = json.loads(timestamps_json) if timestamps_json else []
    
    print(f"Analyzing trade: {trade_id}")
    print(f"Symbol: {symbol}")
    print(f"Current leg quantity: {quantity}")
    print(f"Current actions: {actions}")
    print(f"Current timestamps: {len(timestamps)} timestamps")
    print()
    
    # Get all raw transactions for this symbol
    cursor.execute('''
        SELECT executed_at, action, price, quantity, description, transaction_sub_type
        FROM raw_transactions 
        WHERE symbol = ?
        ORDER BY executed_at
    ''', (symbol,))
    
    raw_txs = cursor.fetchall()
    
    print("Raw transactions:")
    for i, (executed_at, action, price, qty, description, sub_type) in enumerate(raw_txs):
        print(f"{i+1}. {executed_at}")
        print(f"   Action: {action}")
        print(f"   Price: ${price}, Qty: {qty}")
        print(f"   Sub-type: {sub_type}")
        print(f"   Desc: {description[:80]}...")
        print()
    
    # Consolidate transactions properly
    consolidated = consolidate_transactions(raw_txs)
    
    print("Consolidated transactions:")
    new_actions = []
    new_timestamps = []
    final_exit_price = None
    
    for action_type, data in consolidated.items():
        print(f"  {action_type}: {data['total_qty']} contracts @ ${data['avg_price']:.2f}")
        print(f"    Times: {data['timestamps']}")
        
        new_actions.append(action_type)
        new_timestamps.append(data['timestamps'][0])  # Use first timestamp
        
        if action_type in ['BTC', 'STC', 'EXPIRED', 'ASSIGNED', 'EXERCISED', 'CASH_SETTLED']:
            final_exit_price = data['avg_price']
    
    print()
    print(f"Final consolidated actions: {new_actions}")
    print(f"Final exit price: ${final_exit_price}")
    
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
    
    conn.commit()
    conn.close()
    
    print("✅ Transaction consolidation fixed!")
    print("🔄 Refresh your browser to see the changes!")

def consolidate_transactions(raw_txs):
    """
    Consolidate raw transactions by action type, calculating total quantities
    and average prices properly
    """
    consolidated = defaultdict(lambda: {
        'total_qty': 0,
        'total_value': 0,
        'transactions': [],
        'timestamps': [],
        'avg_price': 0
    })
    
    for executed_at, action, price, qty, description, sub_type in raw_txs:
        # Normalize the action
        normalized_action = normalize_action_type(action, description, sub_type)
        
        # Add to consolidated data
        consolidated[normalized_action]['total_qty'] += abs(float(qty or 0))
        consolidated[normalized_action]['total_value'] += abs(float(price or 0)) * abs(float(qty or 0))
        consolidated[normalized_action]['transactions'].append((executed_at, action, price, qty))
        consolidated[normalized_action]['timestamps'].append(executed_at)
    
    # Calculate average prices
    for action_type, data in consolidated.items():
        if data['total_qty'] > 0:
            data['avg_price'] = data['total_value'] / data['total_qty']
        else:
            data['avg_price'] = 0.0
    
    return consolidated

def normalize_action_type(action, description, sub_type):
    """Normalize transaction action to standard types"""
    action_str = str(action).upper()
    desc_str = str(description).upper()
    sub_type_str = str(sub_type).upper()
    
    # Check for expiration/assignment first (most specific)
    if ('EXPIRATION' in desc_str or 'EXPIRED' in desc_str or 
        'REMOVAL' in desc_str and 'EXPIRATION' in desc_str):
        return 'EXPIRED'
    elif 'ASSIGNMENT' in desc_str or 'ASSIGNED' in desc_str:
        return 'ASSIGNED'
    elif 'EXERCISE' in desc_str or 'EXERCISED' in desc_str:
        return 'EXERCISED'
    elif 'CASH SETTLEMENT' in desc_str or 'CASH SETTLED' in desc_str:
        return 'CASH_SETTLED'
    
    # Standard trading actions
    elif 'SELL_TO_OPEN' in action_str or 'STO' in action_str:
        return 'STO'
    elif 'BUY_TO_OPEN' in action_str or 'BTO' in action_str:
        return 'BTO'
    elif 'BUY_TO_CLOSE' in action_str or 'BTC' in action_str:
        return 'BTC'
    elif 'SELL_TO_CLOSE' in action_str or 'STC' in action_str:
        return 'STC'
    
    return action_str

if __name__ == "__main__":
    fix_transaction_consolidation()