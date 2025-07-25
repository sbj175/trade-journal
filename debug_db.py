#!/usr/bin/env python3
"""Debug script to check database state"""

import sqlite3
import os

def check_database():
    db_path = "trade_journal.db"
    
    if not os.path.exists(db_path):
        print("Database does not exist")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("All tables:", [t[0] for t in tables])
    
    # Check for order-related tables
    order_tables = [t[0] for t in tables if 'order' in t[0] or 'position' in t[0]]
    print("Order/Position tables:", order_tables)
    
    # Check HOOD data in raw_transactions if it exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='raw_transactions'")
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM raw_transactions WHERE underlying_symbol = 'HOOD'")
        hood_raw = cursor.fetchone()[0]
        print(f"HOOD raw transactions: {hood_raw}")
        
        # Sample some HOOD transactions
        cursor.execute("SELECT id, symbol, action, quantity, executed_at FROM raw_transactions WHERE underlying_symbol = 'HOOD' LIMIT 5")
        hood_samples = cursor.fetchall()
        print("Sample HOOD transactions:", hood_samples)
    
    # Check HOOD data in trades table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM trades WHERE underlying = 'HOOD'")
        hood_trades = cursor.fetchone()[0]
        print(f"HOOD trades: {hood_trades}")
        
        if hood_trades > 0:
            cursor.execute("SELECT trade_id, strategy_type, status, entry_date FROM trades WHERE underlying = 'HOOD' LIMIT 5")
            hood_trade_samples = cursor.fetchall()
            print("Sample HOOD trades:", hood_trade_samples)
    
    # Check positions table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM positions WHERE underlying = 'HOOD'")
        hood_positions = cursor.fetchone()[0]
        print(f"HOOD positions: {hood_positions}")
    
    conn.close()

if __name__ == "__main__":
    check_database()