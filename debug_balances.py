#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

db = DatabaseManager()

with db.get_connection() as conn:
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='account_balances'")
    table_exists = cursor.fetchone()
    print(f"account_balances table exists: {table_exists is not None}")
    
    if table_exists:
        # Count records
        cursor.execute("SELECT COUNT(*) FROM account_balances")
        count = cursor.fetchone()[0]
        print(f"Total account_balances records: {count}")
        
        # Show latest records
        cursor.execute("""
            SELECT account_number, cash_balance, derivative_buying_power, 
                   net_liquidating_value, updated_at 
            FROM account_balances 
            ORDER BY updated_at DESC 
            LIMIT 5
        """)
        
        rows = cursor.fetchall()
        if rows:
            print("\nLatest balance records:")
            for row in rows:
                print(f"  Account: {row[0]}")
                print(f"    Cash: ${row[1]:,.2f}")
                print(f"    Derivative BP: ${row[2]:,.2f}")
                print(f"    NLV: ${row[3]:,.2f}")
                print(f"    Updated: {row[4]}")
                print()
        else:
            print("\nNo balance records found!")