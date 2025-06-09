#!/usr/bin/env python3
"""
Comprehensive fix for all the identified issues
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json

def comprehensive_fix():
    """
    Fix all the issues:
    1. IBIT_20250401_2legs_959 - remove BTC, it expired
    2. IBIT_20250407_1legs_959 - mark as includes_roll = 1 
    3. Trades with no option legs - delete them
    """
    
    print("Comprehensive Fix for All Issues")
    print("=" * 40)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Issue 1: Fix IBIT_20250401_2legs_959 - remove BTC action (it expired)
    print("1. Fixing IBIT_20250401_2legs_959...")
    cursor.execute('''
        SELECT id, transaction_actions FROM option_legs 
        WHERE trade_id = 'IBIT_20250401_2legs_959'
    ''')
    result = cursor.fetchone()
    if result:
        leg_id, actions_json = result
        actions = json.loads(actions_json) if actions_json else []
        print(f"   Current actions: {actions}")
        
        # Remove BTC action - it should just be STO with expiration emblem
        new_actions = ['STO']  # Just opening action
        
        cursor.execute('''
            UPDATE option_legs 
            SET transaction_actions = ?,
                transaction_timestamps = ?
            WHERE id = ?
        ''', (json.dumps(new_actions), json.dumps(['2025-04-01T13:45:08.699000+00:00']), leg_id))
        
        print(f"   → Fixed actions: {new_actions}")
        print("   → Will show STO ⏰ (expired emblem)")
    else:
        print("   ❌ Trade not found")
    print()
    
    # Issue 2: Fix IBIT_20250407_1legs_959 - mark as includes_roll = 1
    print("2. Fixing IBIT_20250407_1legs_959 roll flag...")
    cursor.execute('''
        UPDATE trades 
        SET includes_roll = 1
        WHERE trade_id = 'IBIT_20250407_1legs_959'
    ''')
    if cursor.rowcount > 0:
        print("   ✅ Marked IBIT_20250407_1legs_959 as includes_roll = 1")
        print("   → Will now be grouped with IBIT_20250411_2legs_959 in chain")
    else:
        print("   ❌ Trade not found")
    print()
    
    # Issue 3: Delete trades with no option legs
    print("3. Removing trades with no option legs...")
    problem_trades = ['IBIT_20250502_1legs_959', 'IBIT_20250606_1legs_959', 'SPX_20250512_2legs_959']
    
    for trade_id in problem_trades:
        cursor.execute('''
            SELECT COUNT(*) FROM option_legs WHERE trade_id = ?
        ''', (trade_id,))
        leg_count = cursor.fetchone()[0]
        
        if leg_count == 0:
            # Delete the trade
            cursor.execute('DELETE FROM trades WHERE trade_id = ?', (trade_id,))
            cursor.execute('DELETE FROM stock_legs WHERE trade_id = ?', (trade_id,))
            print(f"   ✅ Deleted empty trade: {trade_id}")
        else:
            print(f"   ⏭️  {trade_id} has {leg_count} legs, keeping")
    print()
    
    # Issue 4: Check for any other BTC actions that should be expired
    print("4. Converting other BTC actions that are actually expirations...")
    cursor.execute('''
        SELECT ol.id, ol.trade_id, ol.symbol, ol.transaction_actions
        FROM option_legs ol
        WHERE ol.transaction_actions LIKE '%BTC%'
        AND ol.exit_price = 0
    ''')
    
    btc_legs = cursor.fetchall()
    for leg_id, trade_id, symbol, actions_json in btc_legs:
        actions = json.loads(actions_json) if actions_json else []
        if 'BTC' in actions and len(actions) == 2:  # STO + BTC pattern
            print(f"   Converting BTC to expired emblem for {symbol} in {trade_id}")
            new_actions = [action for action in actions if action != 'BTC']
            cursor.execute('''
                UPDATE option_legs 
                SET transaction_actions = ?
                WHERE id = ?
            ''', (json.dumps(new_actions), leg_id))
    
    conn.commit()
    conn.close()
    
    print()
    print("✅ All issues fixed!")
    print("🔄 Refresh your browser to see the changes!")
    print()
    print("Expected results:")
    print("• IBIT_20250401_2legs_959: Single line 'STO ⏰' (expired)")
    print("• IBIT_20250407 + IBIT_20250411: Now grouped in same chain")
    print("• Empty trades: Removed from display")

if __name__ == "__main__":
    comprehensive_fix()