#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

db = DatabaseManager()

# Get AVGO positions
positions = db.get_open_positions()
avgo_positions = [p for p in positions if p.get('symbol') and 'AVGO' in p['symbol']]

print("=== AVGO Position Symbols ===")
for pos in avgo_positions:
    symbol = pos.get('symbol')
    account = pos.get('account_number')
    print(f"Position: '{symbol}' | Account: {account}")

# Get AVGO transactions  
transactions = db.get_raw_transactions()
avgo_transactions = [t for t in transactions if t.get('symbol') and 'AVGO' in t.get('symbol', '')]

print("\n=== AVGO Transaction Symbols ===")
opening_transactions = {}
for txn in avgo_transactions:
    symbol = txn.get('symbol')
    action = txn.get('action', '').upper()
    account = txn.get('account_number')
    
    print(f"Transaction: '{symbol}' | Action: '{action}' | Account: {account}")
    
    # Test the matching logic
    if symbol and ('BUY_TO_OPEN' in action or 'SELL_TO_OPEN' in action):
        if symbol not in opening_transactions:
            opening_transactions[symbol] = []
        opening_transactions[symbol].append(txn)

print(f"\n=== Opening Transactions Dictionary ===")
print(f"Found opening transactions for {len(opening_transactions)} symbols:")
for symbol in opening_transactions:
    print(f"  '{symbol}': {len(opening_transactions[symbol])} transactions")

print("\n=== String Comparison Test ===")
pos_symbols = set(p.get('symbol') for p in avgo_positions)
txn_symbols = set(opening_transactions.keys())

print(f"Position symbols: {pos_symbols}")
print(f"Transaction symbols: {txn_symbols}")
print(f"Intersection: {pos_symbols & txn_symbols}")

# Test exact matches
for pos_symbol in pos_symbols:
    for txn_symbol in txn_symbols:
        if pos_symbol == txn_symbol:
            print(f"MATCH: '{pos_symbol}' == '{txn_symbol}'")
        else:
            print(f"NO MATCH: '{pos_symbol}' != '{txn_symbol}'")
            # Show character-by-character comparison
            print(f"  Lengths: {len(pos_symbol)} vs {len(txn_symbol)}")
            if len(pos_symbol) == len(txn_symbol):
                for i, (a, b) in enumerate(zip(pos_symbol, txn_symbol)):
                    if a != b:
                        print(f"    Diff at position {i}: '{a}' vs '{b}' (ord {ord(a)} vs {ord(b)})")