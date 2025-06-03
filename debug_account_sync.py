#!/usr/bin/env python3
"""
Debug script to check account association during sync
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.trade_manager import TradeManager

def debug_account_sync():
    print("=== Debugging Account Association ===")
    
    # Initialize and authenticate
    client = TastytradeClient()
    if not client.authenticate():
        print("Failed to authenticate")
        return
    
    print(f"Found {len(client.accounts)} accounts:")
    for account in client.accounts:
        print(f"  - {account.account_number}")
    
    # Get some recent transactions
    print("\nFetching transactions...")
    transactions = client.get_transactions(days_back=7)
    print(f"Fetched {len(transactions)} transactions")
    
    # Check account numbers in transactions
    account_counts = {}
    for tx in transactions[:10]:  # Check first 10
        account = tx.get('account_number', 'MISSING')
        account_counts[account] = account_counts.get(account, 0) + 1
        print(f"  TX {tx.get('id')}: Account {account}, Symbol {tx.get('symbol')}")
    
    print(f"\nTransaction account distribution:")
    for account, count in account_counts.items():
        print(f"  {account}: {count} transactions")
    
    # Process into trades
    print("\nProcessing into trades...")
    trade_manager = TradeManager()
    trades = trade_manager.process_transactions(transactions)
    print(f"Created {len(trades)} trades")
    
    # Check account numbers in trades
    print("\nTrade account distribution:")
    for trade in trades[:5]:  # Check first 5
        account = getattr(trade, 'account_number', 'MISSING')
        print(f"  Trade {trade.trade_id}: Account {account}")

if __name__ == "__main__":
    debug_account_sync()