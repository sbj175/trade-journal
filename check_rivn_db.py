#!/usr/bin/env python3
"""
Check what RIVN trades are in the database
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

def check_rivn_in_db():
    db = DatabaseManager()
    
    # Get all RIVN trades
    rivn_trades = db.get_trades(underlying='RIVN', limit=10)
    
    print(f"Found {len(rivn_trades)} RIVN trades in database:")
    
    for trade in rivn_trades:
        print(f"\nTrade ID: {trade['trade_id']}")
        print(f"Strategy: {trade['strategy_type']}")
        print(f"Status: {trade['status']}")
        print(f"Entry Date: {trade['entry_date']}")
        print(f"Exit Date: {trade['exit_date']}")
        print(f"P&L: ${trade['current_pnl']}")
        print(f"Created: {trade['created_at']}")
        print(f"Updated: {trade['updated_at']}")

if __name__ == "__main__":
    check_rivn_in_db()