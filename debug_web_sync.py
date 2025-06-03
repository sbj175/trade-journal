#!/usr/bin/env python3
"""
Debug what the web app sync is actually doing
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.trade_manager import TradeManager
from src.database.db_manager import DatabaseManager

def debug_web_sync():
    print("=== Debugging Web App Sync Process ===")
    
    # Initialize exactly like the web app does
    tastytrade = TastytradeClient()
    trade_manager = TradeManager()
    db = DatabaseManager()
    
    # Authenticate
    if not tastytrade.authenticate():
        print("Failed to authenticate")
        return
    
    # Fetch transactions
    print("1. Fetching transactions...")
    transactions = tastytrade.get_transactions(days_back=30)
    rivn_transactions = [tx for tx in transactions if tx.get('underlying_symbol') == 'RIVN']
    print(f"Found {len(rivn_transactions)} RIVN transactions")
    
    # Process into trades
    print("\n2. Processing transactions into trades...")
    trades = trade_manager.process_transactions(transactions)
    rivn_trades = [t for t in trades if t.underlying == 'RIVN']
    print(f"Created {len(rivn_trades)} RIVN trades:")
    
    for i, trade in enumerate(rivn_trades):
        print(f"  {i+1}. {trade.trade_id} - {trade.status.value} - Entry: {trade.entry_date} - Exit: {trade.exit_date}")
    
    # Check what's in database before save
    print("\n3. Checking existing database...")
    existing_rivn = db.get_trades(underlying='RIVN', limit=10)
    print(f"Found {len(existing_rivn)} existing RIVN trades in database:")
    for trade in existing_rivn:
        print(f"  - {trade['trade_id']} - {trade['status']}")
    
    # Simulate the web app save process
    print(f"\n4. Simulating web app save process...")
    
    # Get existing trades to avoid duplicates (like web app does)
    existing_trades = {}
    for underlying in set(trade.underlying for trade in trades):
        existing = db.get_trades(underlying=underlying, limit=1000)
        for existing_trade in existing:
            existing_trades[existing_trade['trade_id']] = existing_trade
    
    print(f"Existing trades dict has {len(existing_trades)} entries")
    
    saved_count = 0
    updated_count = 0
    skipped_count = 0
    
    for trade in rivn_trades:
        print(f"\nProcessing trade: {trade.trade_id}")
        if trade.trade_id in existing_trades:
            existing = existing_trades[trade.trade_id]
            if (existing['status'] != trade.status.value or 
                existing['exit_date'] != (trade.exit_date.isoformat() if trade.exit_date else None)):
                print(f"  -> Would UPDATE (status: {existing['status']} -> {trade.status.value})")
                updated_count += 1
            else:
                print(f"  -> Would SKIP (unchanged)")
                skipped_count += 1
        else:
            print(f"  -> Would SAVE as NEW")
            saved_count += 1
    
    print(f"\nResult: {saved_count} new, {updated_count} updated, {skipped_count} skipped")

if __name__ == "__main__":
    debug_web_sync()