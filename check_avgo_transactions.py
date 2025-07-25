#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

db = DatabaseManager()

# Check AVGO transactions
print("=== AVGO Transactions ===")
transactions = db.get_raw_transactions()
avgo_transactions = [t for t in transactions if t.get('symbol') and 'AVGO' in t['symbol']]

print(f"Found {len(avgo_transactions)} AVGO-related transactions")

for txn in avgo_transactions:
    symbol = txn.get('symbol')
    action = txn.get('action')
    executed_at = txn.get('executed_at')
    account = txn.get('account_number')
    print(f"  {symbol} | {action} | {executed_at} | Account: {account}")

print(f"\nCurrent AVGO positions:")
positions = db.get_open_positions()
avgo_positions = [p for p in positions if p.get('symbol') and 'AVGO' in p['symbol']]

for pos in avgo_positions:
    symbol = pos.get('symbol')
    account = pos.get('account_number') 
    opened_at = pos.get('opened_at')
    print(f"  {symbol} | Account: {account} | opened_at: {opened_at}")