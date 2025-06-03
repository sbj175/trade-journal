#!/usr/bin/env python3
"""
Clean up duplicate RIVN trades in the database
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

def clean_rivn_trades():
    db = DatabaseManager()
    
    # Get all RIVN trades
    rivn_trades = db.get_trades(underlying='RIVN', limit=10)
    
    print(f"Found {len(rivn_trades)} RIVN trades in database:")
    
    # The correct trade should be the one with 4 legs (opening + closing)
    correct_trade = None
    incorrect_trades = []
    
    for trade in rivn_trades:
        print(f"\nTrade ID: {trade['trade_id']}")
        print(f"Status: {trade['status']}")
        print(f"Entry Date: {trade['entry_date']}")
        print(f"Exit Date: {trade['exit_date']}")
        
        # The correct trade should have 4 legs and be closed
        if '4legs' in trade['trade_id'] and trade['status'] == 'Closed':
            correct_trade = trade
            print(f"✅ This is the CORRECT trade")
        else:
            incorrect_trades.append(trade)
            print(f"❌ This is an INCORRECT trade (will be deleted)")
    
    if correct_trade and incorrect_trades:
        print(f"\n{'='*50}")
        print(f"Will delete {len(incorrect_trades)} incorrect trades and keep:")
        print(f"✅ {correct_trade['trade_id']} - {correct_trade['status']} - Entry: {correct_trade['entry_date']} - Exit: {correct_trade['exit_date']}")
        
        # Delete incorrect trades
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            for trade in incorrect_trades:
                trade_id = trade['trade_id']
                print(f"Deleting {trade_id}...")
                
                # Delete from all related tables
                cursor.execute("DELETE FROM option_legs WHERE trade_id = ?", (trade_id,))
                cursor.execute("DELETE FROM stock_legs WHERE trade_id = ?", (trade_id,))
                cursor.execute("DELETE FROM trades WHERE trade_id = ?", (trade_id,))
        
        print(f"\n✅ Cleanup complete! RIVN should now show as 1 closed trade.")
    else:
        print(f"\n⚠️  Could not identify correct trade pattern")

if __name__ == "__main__":
    clean_rivn_trades()