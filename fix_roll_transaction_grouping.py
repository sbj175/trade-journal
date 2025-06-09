#!/usr/bin/env python3
"""
Fix roll transaction grouping to ensure BTC transactions are properly linked to their STO trades
"""
import sqlite3
import json
from datetime import datetime

def connect_db():
    """Connect to the trade journal database"""
    return sqlite3.connect('trade_journal.db')

def fix_roll_transaction_grouping():
    """Fix the grouping of roll transactions"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== Fixing Roll Transaction Grouping ===\n")
    
    # First, identify all orphaned BTC transactions
    query = """
    SELECT rt.id, rt.symbol, rt.action, rt.quantity, rt.price, rt.executed_at, rt.order_id
    FROM raw_transactions rt
    WHERE rt.action LIKE '%BUY_TO_CLOSE%'
    AND rt.underlying_symbol = 'IBIT'
    AND rt.id NOT IN (
        SELECT DISTINCT json_each.value
        FROM option_legs, json_each(option_legs.transaction_ids)
    )
    ORDER BY rt.executed_at
    """
    cursor.execute(query)
    orphaned_btc = cursor.fetchall()
    
    print(f"Found {len(orphaned_btc)} orphaned BTC transactions\n")
    
    # For each orphaned BTC, find its matching STO trade
    fixes_to_apply = []
    
    for btc_tx in orphaned_btc:
        tx_id, symbol, action, quantity, price, executed_at, order_id = btc_tx
        
        # Find the trade that contains the STO for this option
        query = """
        SELECT t.trade_id, ol.id as leg_id, ol.transaction_ids, ol.transaction_actions, 
               ol.transaction_timestamps, ol.exit_price
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE ol.symbol = ?
        AND ol.quantity = ?
        AND ol.exit_price IS NULL
        AND t.status != 'Closed'
        ORDER BY t.entry_date DESC
        LIMIT 1
        """
        cursor.execute(query, (symbol, -abs(quantity)))
        matching_trade = cursor.fetchone()
        
        if matching_trade:
            trade_id, leg_id, tx_ids_json, actions_json, timestamps_json, exit_price = matching_trade
            
            # Parse existing data
            tx_ids = json.loads(tx_ids_json) if tx_ids_json else []
            actions = json.loads(actions_json) if actions_json else []
            timestamps = json.loads(timestamps_json) if timestamps_json else []
            
            # Add the BTC transaction
            tx_ids.append(str(tx_id))
            actions.append('BTC')
            timestamps.append(executed_at)
            
            fixes_to_apply.append({
                'leg_id': leg_id,
                'tx_ids': json.dumps(tx_ids),
                'actions': json.dumps(actions),
                'timestamps': json.dumps(timestamps),
                'exit_price': price,
                'btc_details': f"{symbol} x{quantity} @ ${price}"
            })
            
            print(f"Will add BTC {tx_id} to trade {trade_id}: {symbol} x{quantity} @ ${price}")
    
    # Apply the fixes
    if fixes_to_apply:
        print(f"\nApplying {len(fixes_to_apply)} fixes...")
        
        for fix in fixes_to_apply:
            query = """
            UPDATE option_legs
            SET transaction_ids = ?,
                transaction_actions = ?,
                transaction_timestamps = ?,
                exit_price = ?
            WHERE id = ?
            """
            cursor.execute(query, (
                fix['tx_ids'],
                fix['actions'],
                fix['timestamps'],
                fix['exit_price'],
                fix['leg_id']
            ))
        
        # Update trade statuses to closed where all legs are closed
        query = """
        UPDATE trades
        SET status = 'Closed',
            exit_date = DATE(
                (SELECT MAX(json_each.value)
                 FROM option_legs ol, json_each(ol.transaction_timestamps)
                 WHERE ol.trade_id = trades.trade_id
                 AND json_valid(ol.transaction_timestamps))
            )
        WHERE trade_id IN (
            SELECT DISTINCT t.trade_id
            FROM trades t
            JOIN option_legs ol ON t.trade_id = ol.trade_id
            WHERE t.status = 'Open'
            AND NOT EXISTS (
                SELECT 1
                FROM option_legs ol2
                WHERE ol2.trade_id = t.trade_id
                AND ol2.exit_price IS NULL
            )
        )
        """
        cursor.execute(query)
        
        conn.commit()
        print(f"Successfully applied fixes and updated trade statuses")
    else:
        print("No fixes needed")
    
    # Verify the fixes
    print("\n=== Verification ===")
    
    # Check the IBIT trades we were interested in
    query = """
    SELECT t.trade_id, t.status, ol.transaction_actions, ol.exit_price
    FROM trades t
    JOIN option_legs ol ON t.trade_id = ol.trade_id
    WHERE t.trade_id IN ('IBIT_20250505_1legs_959', 'IBIT_20250505_1legs_644')
    """
    cursor.execute(query)
    results = cursor.fetchall()
    
    for result in results:
        print(f"Trade {result[0]}: Status={result[1]}, Actions={result[2]}, Exit=${result[3]}")
    
    conn.close()

if __name__ == "__main__":
    fix_roll_transaction_grouping()