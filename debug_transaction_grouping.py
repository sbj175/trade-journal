#!/usr/bin/env python3
"""
Debug script to analyze how transactions are being grouped into trades
"""
import sqlite3
import json
from datetime import datetime

def connect_db():
    return sqlite3.connect('trade_journal.db')

def analyze_transaction_grouping():
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== Transaction Grouping Analysis ===\n")
    
    # Get the specific transactions and their trade assignments
    cursor.execute("""
        SELECT t.trade_id, ol.symbol, ol.transaction_actions, ol.transaction_timestamps, ol.transaction_ids, ol.order_id
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE t.trade_id IN ('IBIT_20250505_1legs_959', 'IBIT_20250507_2legs_959')
        ORDER BY t.entry_date
    """)
    
    trade_legs = cursor.fetchall()
    
    print("Current Trade-to-Leg Assignments:")
    for leg in trade_legs:
        trade_id = leg[0]
        symbol = leg[1]
        actions = json.loads(leg[2]) if leg[2] else []
        timestamps = json.loads(leg[3]) if leg[3] else []
        tx_ids = json.loads(leg[4]) if leg[4] else []
        order_id = leg[5]
        
        print(f"\nTrade: {trade_id}")
        print(f"  Symbol: {symbol}")
        print(f"  Actions: {actions}")
        print(f"  Order ID: {order_id}")
        print(f"  Transaction IDs: {tx_ids}")
        
        # Get raw transaction details for these IDs
        if tx_ids:
            placeholders = ','.join(['?' for _ in tx_ids])
            cursor.execute(f"""
                SELECT id, order_id, action, executed_at, description
                FROM raw_transactions 
                WHERE id IN ({placeholders})
                ORDER BY executed_at
            """, tx_ids)
            
            raw_txs = cursor.fetchall()
            print(f"  Raw Transactions:")
            for raw_tx in raw_txs:
                print(f"    ID: {raw_tx[0]} | Order: {raw_tx[1]} | Action: {raw_tx[2]} | Time: {raw_tx[3]}")
                print(f"      {raw_tx[4]}")
    
    print("\n" + "="*60)
    print("Expected vs Actual Grouping:")
    print("="*60)
    
    print("\nEXPECTED:")
    print("Trade IBIT_20250505_1legs_959:")
    print("  - Only STO from order 382168011")
    print("  - Actions: ['STO']")
    print("  - includes_roll: False")
    
    print("\nTrade IBIT_20250507_2legs_959:")
    print("  - BTC from order 382568608 (closing the above)")
    print("  - STO from order 382568608 (opening new position)")
    print("  - Actions: ['BTC', 'STO']")
    print("  - includes_roll: True")
    
    print("\nACTUAL:")
    print("Trade IBIT_20250505_1legs_959:")
    print("  - Actions: ['STO', 'BTC'] (WRONG - includes closing from different order)")
    print("  - includes_roll: False")
    
    print("\nTrade IBIT_20250507_2legs_959:")
    print("  - Actions: ['STO'] (WRONG - missing the BTC)")
    print("  - includes_roll: True (correct but for wrong reason)")
    
    print("\n" + "="*60)
    print("ROOT CAUSE ANALYSIS:")
    print("="*60)
    
    print("\nThe closing transaction matching logic is incorrectly merging")
    print("the BTC transaction from order 382568608 into the trade created")
    print("from order 382168011, instead of keeping them as separate trades")
    print("that are linked by the roll chain logic.")
    
    print("\nThis suggests the transaction matching is prioritizing position")
    print("closure over maintaining order-based grouping integrity.")
    
    conn.close()

if __name__ == "__main__":
    analyze_transaction_grouping()