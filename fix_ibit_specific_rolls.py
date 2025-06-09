#!/usr/bin/env python3
"""
Fix the specific IBIT May 9 to May 16 roll transactions
"""
import sqlite3
import json
from datetime import datetime

def connect_db():
    """Connect to the trade journal database"""
    return sqlite3.connect('trade_journal.db')

def fix_ibit_specific_rolls():
    """Fix the IBIT May 9 to May 16 roll specifically"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== Fixing IBIT May 9 to May 16 Roll ===\n")
    
    # Map specific BTC transactions to their STO trades
    fixes = [
        {
            'btc_tx_id': '361467801',  # BTC 48 shares @ 0.63
            'target_trade': 'IBIT_20250505_1legs_644'
        },
        {
            'btc_tx_id': '361469425',  # BTC 150 shares @ 0.64  
            'target_trade': 'IBIT_20250505_1legs_959'
        }
    ]
    
    for fix in fixes:
        btc_tx_id = fix['btc_tx_id']
        target_trade = fix['target_trade']
        
        # Get BTC transaction details
        query = """
        SELECT symbol, quantity, price, executed_at
        FROM raw_transactions
        WHERE id = ?
        """
        cursor.execute(query, (btc_tx_id,))
        btc_tx = cursor.fetchone()
        
        if not btc_tx:
            print(f"BTC transaction {btc_tx_id} not found")
            continue
            
        symbol, quantity, price, executed_at = btc_tx
        
        # Get the target trade's option leg
        query = """
        SELECT ol.id, ol.transaction_ids, ol.transaction_actions, ol.transaction_timestamps
        FROM option_legs ol
        WHERE ol.trade_id = ?
        AND ol.symbol = ?
        """
        cursor.execute(query, (target_trade, symbol))
        leg = cursor.fetchone()
        
        if not leg:
            print(f"Option leg for {target_trade} with symbol {symbol} not found")
            continue
            
        leg_id, tx_ids_json, actions_json, timestamps_json = leg
        
        # Parse existing data
        tx_ids = json.loads(tx_ids_json) if tx_ids_json else []
        actions = json.loads(actions_json) if actions_json else []
        timestamps = json.loads(timestamps_json) if timestamps_json else []
        
        # Add the BTC transaction
        tx_ids.append(btc_tx_id)
        actions.append('BTC')
        timestamps.append(executed_at)
        
        # Update the option leg
        query = """
        UPDATE option_legs
        SET transaction_ids = ?,
            transaction_actions = ?,
            transaction_timestamps = ?,
            exit_price = ?
        WHERE id = ?
        """
        cursor.execute(query, (
            json.dumps(tx_ids),
            json.dumps(actions),
            json.dumps(timestamps),
            price,
            leg_id
        ))
        
        print(f"Added BTC {btc_tx_id} to {target_trade}: {symbol} x{quantity} @ ${price}")
    
    # Update trade statuses to closed
    for fix in fixes:
        target_trade = fix['target_trade']
        query = """
        UPDATE trades
        SET status = 'Closed',
            exit_date = '2025-05-07'
        WHERE trade_id = ?
        """
        cursor.execute(query, (target_trade,))
        print(f"Updated {target_trade} status to Closed")
    
    conn.commit()
    
    # Verify the fixes
    print("\n=== Verification ===")
    
    for fix in fixes:
        target_trade = fix['target_trade']
        query = """
        SELECT t.trade_id, t.status, t.exit_date, ol.transaction_actions, ol.exit_price
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE t.trade_id = ?
        """
        cursor.execute(query, (target_trade,))
        result = cursor.fetchone()
        
        if result:
            print(f"Trade {result[0]}: Status={result[1]}, Exit Date={result[2]}, Actions={result[3]}, Exit Price=${result[4]}")
    
    conn.close()

if __name__ == "__main__":
    fix_ibit_specific_rolls()