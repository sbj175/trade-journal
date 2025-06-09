#!/usr/bin/env python3
"""
Fix expiration transaction matching to existing trades
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from datetime import datetime, timedelta
import json

def fix_expiration_matching():
    """
    Fix the SPX expiration trade by manually matching closing transactions to existing trade
    """
    
    print("Fixing SPX Expiration Transaction Matching")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Step 1: Identify the problem trade
    target_trade_id = 'SPX_20250509_4legs_959'
    
    print(f"1. Analyzing trade: {target_trade_id}")
    
    # Get current trade status
    cursor.execute('''
        SELECT trade_id, status, entry_date, exit_date, strategy_type
        FROM trades 
        WHERE trade_id = ?
    ''', (target_trade_id,))
    
    trade_info = cursor.fetchone()
    if not trade_info:
        print(f"❌ Trade {target_trade_id} not found!")
        return
    
    print(f"   Current status: {trade_info[1]}")
    print(f"   Entry date: {trade_info[2]}")
    print(f"   Exit date: {trade_info[3]}")
    print()
    
    # Step 2: Get all option legs for this trade
    cursor.execute('''
        SELECT id, symbol, option_type, strike, expiration, quantity, 
               entry_price, exit_price, transaction_actions, transaction_timestamps
        FROM option_legs 
        WHERE trade_id = ?
        ORDER BY strike, option_type
    ''', (target_trade_id,))
    
    trade_legs = cursor.fetchall()
    print(f"2. Trade has {len(trade_legs)} option legs:")
    
    leg_symbols = {}
    for leg_id, symbol, opt_type, strike, expiration, quantity, entry_price, exit_price, actions, timestamps in trade_legs:
        print(f"   Leg {leg_id}: {symbol} ({quantity:+d} {opt_type} ${strike})")
        print(f"              Entry: ${entry_price}, Exit: {exit_price}")
        print(f"              Actions: {actions}")
        leg_symbols[symbol] = leg_id
    print()
    
    # Step 3: Find matching closing transactions
    print("3. Finding closing transactions for these legs:")
    
    closing_updates = []
    
    for symbol, leg_id in leg_symbols.items():
        # Find closing transactions for this symbol
        cursor.execute('''
            SELECT id, executed_at, action, transaction_sub_type, price, quantity, description
            FROM raw_transactions 
            WHERE symbol = ?
            AND executed_at >= '2025-05-12'
            ORDER BY executed_at
        ''', (symbol,))
        
        closing_txs = cursor.fetchall()
        
        if closing_txs:
            print(f"   {symbol}:")
            
            # Process each closing transaction
            for tx_id, executed_at, action, sub_type, price, quantity, description in closing_txs:
                print(f"     {executed_at}: {sub_type} (Action: {action})")
                print(f"       Price: {price}, Qty: {quantity}")
                print(f"       Desc: {description[:60]}...")
                
                # Determine the normalized action
                normalized_action = normalize_closing_action(action, sub_type, description)
                print(f"       Normalized: {normalized_action}")
                
                # Determine exit price (for cash settlements, use the settlement amount per contract)
                exit_price = None
                if price is not None and price != 0:
                    if 'CASH SETTLED' in str(sub_type).upper():
                        # For cash settlements, the price is the settlement amount
                        # For index options, this is often the intrinsic value
                        exit_price = abs(float(price)) if price != 0 else 0
                    else:
                        exit_price = float(price)
                
                # Store update info
                closing_updates.append({
                    'leg_id': leg_id,
                    'symbol': symbol,
                    'action': normalized_action,
                    'timestamp': executed_at,
                    'exit_price': exit_price,
                    'tx_id': tx_id
                })
                
                print(f"       Will update leg {leg_id} with exit price: {exit_price}")
                print()
        else:
            print(f"   {symbol}: ❌ No closing transactions found")
    
    # Step 4: Apply updates to option legs
    print("4. Applying updates to option legs:")
    
    if closing_updates:
        for update in closing_updates:
            leg_id = update['leg_id']
            action = update['action']
            timestamp = update['timestamp']
            exit_price = update['exit_price']
            
            # Get current leg data
            cursor.execute('''
                SELECT transaction_actions, transaction_timestamps
                FROM option_legs WHERE id = ?
            ''', (leg_id,))
            
            current_data = cursor.fetchone()
            if current_data:
                current_actions = json.loads(current_data[0]) if current_data[0] else []
                current_timestamps = json.loads(current_data[1]) if current_data[1] else []
                
                # Add new action and timestamp if not already present
                if action not in current_actions:
                    current_actions.append(action)
                    current_timestamps.append(timestamp)
                
                # Update the leg
                cursor.execute('''
                    UPDATE option_legs 
                    SET exit_price = ?,
                        transaction_actions = ?,
                        transaction_timestamps = ?
                    WHERE id = ?
                ''', (exit_price, json.dumps(current_actions), json.dumps(current_timestamps), leg_id))
                
                print(f"   ✅ Updated leg {leg_id} ({update['symbol']})")
                print(f"      Exit price: {exit_price}")
                print(f"      Actions: {current_actions}")
    
    # Step 5: Update trade status to Closed
    print()
    print("5. Updating trade status:")
    
    # Check if all legs now have exit prices
    cursor.execute('''
        SELECT COUNT(*) as total, 
               COUNT(CASE WHEN exit_price IS NOT NULL THEN 1 END) as with_exit
        FROM option_legs 
        WHERE trade_id = ?
    ''', (target_trade_id,))
    
    leg_counts = cursor.fetchone()
    total_legs = leg_counts[0]
    legs_with_exit = leg_counts[1]
    
    print(f"   Legs with exit prices: {legs_with_exit}/{total_legs}")
    
    if legs_with_exit == total_legs:
        # All legs have exit prices, mark trade as closed
        # Find the latest closing timestamp for exit_date
        cursor.execute('''
            SELECT MAX(json_extract(value, '$')) as latest_timestamp
            FROM option_legs ol,
                 json_each(ol.transaction_timestamps) 
            WHERE ol.trade_id = ?
            AND json_extract(value, '$') >= '2025-05-12'
        ''', (target_trade_id,))
        
        latest_timestamp = cursor.fetchone()[0]
        if latest_timestamp:
            # Convert timestamp to date
            try:
                exit_date = datetime.fromisoformat(latest_timestamp.replace('Z', '+00:00')).date()
            except:
                exit_date = datetime(2025, 5, 12).date()  # Fallback to expiration date
        else:
            exit_date = datetime(2025, 5, 12).date()  # Fallback to expiration date
        
        # Update trade status
        cursor.execute('''
            UPDATE trades 
            SET status = 'Closed',
                exit_date = ?
            WHERE trade_id = ?
        ''', (exit_date.isoformat(), target_trade_id))
        
        print(f"   ✅ Trade marked as Closed with exit date: {exit_date}")
    else:
        print(f"   ⚠️  Not all legs have exit prices, keeping trade as Open")
    
    # Step 6: Commit changes
    conn.commit()
    conn.close()
    
    print()
    print("6. SUMMARY:")
    print(f"   ✅ Fixed expiration matching for {target_trade_id}")
    print(f"   ✅ Updated {len(closing_updates)} option legs")
    print(f"   ✅ Trade status updated to reflect expiration")
    print()
    print("   The trade should now correctly show as Closed with expiration emblems!")

def normalize_closing_action(action, sub_type, description):
    """Normalize closing action based on transaction type"""
    
    # Check sub_type first (most reliable)
    sub_type_upper = str(sub_type).upper() if sub_type else ''
    
    if 'EXPIRATION' in sub_type_upper:
        return 'EXPIRED'
    elif 'ASSIGNMENT' in sub_type_upper:
        return 'ASSIGNED'
    elif 'EXERCISE' in sub_type_upper:
        return 'EXERCISED'
    elif 'CASH SETTLED' in sub_type_upper:
        return 'CASH_SETTLED'
    
    # Check action
    action_upper = str(action).upper() if action else ''
    if 'BUY_TO_CLOSE' in action_upper or 'BTC' in action_upper:
        return 'BTC'
    elif 'SELL_TO_CLOSE' in action_upper or 'STC' in action_upper:
        return 'STC'
    
    # Check description as fallback
    desc_upper = str(description).upper() if description else ''
    if 'EXPIRATION' in desc_upper or 'EXPIRED' in desc_upper:
        return 'EXPIRED'
    elif 'ASSIGNMENT' in desc_upper or 'ASSIGNED' in desc_upper:
        return 'ASSIGNED'
    elif 'EXERCISE' in desc_upper or 'EXERCISED' in desc_upper:
        return 'EXERCISED'
    elif 'REMOVAL' in desc_upper:
        return 'EXPIRED'  # "Removal due to expiration/exercise/assignment"
    
    return 'CLOSED'  # Generic fallback

if __name__ == "__main__":
    try:
        fix_expiration_matching()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()