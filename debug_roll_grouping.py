#!/usr/bin/env python3
"""
Debug why BTC transactions aren't being grouped with their original STO trades
"""
import sqlite3
import json

def connect_db():
    """Connect to the trade journal database"""
    return sqlite3.connect('trade_journal.db')

def debug_roll_grouping():
    """Debug the roll grouping issue"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== Debugging Roll Transaction Grouping ===\n")
    
    # Get the original STO transactions from May 5
    print("1. Original STO transactions (May 5):")
    query = """
    SELECT id, symbol, action, quantity, price, executed_at, order_id
    FROM raw_transactions
    WHERE symbol = 'IBIT  250509C00055500'
    AND action LIKE '%SELL_TO_OPEN%'
    ORDER BY executed_at
    """
    cursor.execute(query)
    sto_txs = cursor.fetchall()
    for tx in sto_txs:
        print(f"  ID: {tx[0]}, Qty: {tx[3]}, Price: ${tx[4]}, Time: {tx[5]}")
    
    # Get the BTC transactions from May 7
    print("\n2. BTC transactions (May 7):")
    query = """
    SELECT id, symbol, action, quantity, price, executed_at, order_id
    FROM raw_transactions
    WHERE symbol = 'IBIT  250509C00055500'
    AND action LIKE '%BUY_TO_CLOSE%'
    ORDER BY executed_at
    """
    cursor.execute(query)
    btc_txs = cursor.fetchall()
    for tx in btc_txs:
        print(f"  ID: {tx[0]}, Qty: {tx[3]}, Price: ${tx[4]}, Time: {tx[5]}, Order: {tx[6]}")
    
    # Check which transaction IDs are in which trades
    print("\n3. Transaction ID mapping:")
    
    # Get all relevant transaction IDs
    all_tx_ids = [str(tx[0]) for tx in sto_txs + btc_txs]
    
    for tx_id in all_tx_ids:
        query = """
        SELECT t.trade_id, ol.transaction_ids, ol.transaction_actions
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE ol.transaction_ids LIKE ?
        """
        cursor.execute(query, (f'%{tx_id}%',))
        results = cursor.fetchall()
        
        if results:
            for result in results:
                print(f"  TX {tx_id} is in trade {result[0]} with actions {result[2]}")
        else:
            print(f"  TX {tx_id} is NOT in any trade!")
    
    # Check if the closing transactions are standalone
    print("\n4. Checking for orphaned closing transactions:")
    query = """
    SELECT id, symbol, action, executed_at
    FROM raw_transactions
    WHERE action LIKE '%BUY_TO_CLOSE%'
    AND underlying_symbol = 'IBIT'
    AND id NOT IN (
        SELECT DISTINCT json_each.value
        FROM option_legs, json_each(option_legs.transaction_ids)
    )
    """
    cursor.execute(query)
    orphans = cursor.fetchall()
    print(f"  Found {len(orphans)} orphaned BTC transactions")
    for tx in orphans:
        print(f"    ID: {tx[0]}, Symbol: {tx[1]}, Time: {tx[3]}")
    
    conn.close()

if __name__ == "__main__":
    debug_roll_grouping()