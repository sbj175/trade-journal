#!/usr/bin/env python3
"""
Fix the sync to include expiration/assignment transactions
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def analyze_sync_filtering():
    """Analyze what transactions are being filtered out"""
    
    import sqlite3
    
    print("Analyzing Transaction Filtering Issues")
    print("=" * 50)
    
    # Check what raw transactions we have vs what gets processed
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Check all raw transactions from May 12
    print("1. All Raw Transactions from May 12:")
    cursor.execute('''
        SELECT 
            executed_at,
            symbol,
            action,
            description,
            transaction_sub_type,
            instrument_type,
            price,
            quantity
        FROM raw_transactions 
        WHERE executed_at BETWEEN '2025-05-12' AND '2025-05-13'
        ORDER BY executed_at
    ''')
    
    may12_txs = cursor.fetchall()
    print(f"Found {len(may12_txs)} transactions on May 12:")
    
    for tx in may12_txs:
        executed_at, symbol, action, description, sub_type, inst_type, price, quantity = tx
        
        # Check if this would be filtered out by current logic
        has_instrument_type = inst_type is not None
        has_symbol = symbol is not None
        would_be_included = has_instrument_type and has_symbol
        
        print(f"  {executed_at}")
        print(f"    Symbol: {symbol}")
        print(f"    Action: {action}")
        print(f"    Instrument Type: {inst_type}")
        print(f"    Sub-type: {sub_type}")
        print(f"    Description: {description[:60]}...")
        print(f"    INCLUDED: {'✅ YES' if would_be_included else '❌ NO'}")
        print()
    
    conn.close()
    
    print("\n2. SOLUTION NEEDED:")
    print("=" * 30)
    print("The current filtering logic:")
    print("  if tx.get('instrument_type') is not None and tx.get('symbol') is not None")
    print()
    print("Should be modified to also include expiration/assignment transactions:")
    print("  - Receive Deliver transactions")
    print("  - Assignment/Exercise/Expiration sub-types")
    print("  - Even if action is None/blank")
    print()
    print("These are legitimate closing transactions that affect trade status!")

if __name__ == "__main__":
    try:
        analyze_sync_filtering()
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the database exists and app.py has been run")