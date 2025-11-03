#!/usr/bin/env python3
"""
Show sample trade transaction data from Tastytrade
"""

import sqlite3
import json

def show_trade_transactions():
    """Show a few actual trade transactions"""
    
    print('🔍 Sample Trade Transaction Data from Tastytrade')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get some actual trade transactions (not money movements or fees)
    cursor.execute("""
        SELECT * FROM raw_transactions 
        WHERE transaction_type = 'Trade' 
        AND symbol IS NOT NULL 
        ORDER BY executed_at DESC 
        LIMIT 5
    """)
    rows = cursor.fetchall()
    
    # Get column names
    cursor.execute("PRAGMA table_info(raw_transactions)")
    column_info = cursor.fetchall()
    column_names = [col[1] for col in column_info]
    
    print(f'Found {len(rows)} trade transactions:')
    
    for i, row in enumerate(rows, 1):
        print(f'\n📈 Trade Transaction {i}:')
        print('-' * 50)
        
        for col_name, value in zip(column_names, row):
            print(f'{col_name}: {value}')
    
    # Also show some expiration transactions to see the structure
    print('\n\n🏁 Sample Expiration Transactions:')
    print('=' * 60)
    
    cursor.execute("""
        SELECT * FROM raw_transactions 
        WHERE transaction_sub_type = 'Expiration'
        AND symbol IS NOT NULL 
        ORDER BY executed_at DESC 
        LIMIT 3
    """)
    rows = cursor.fetchall()
    
    for i, row in enumerate(rows, 1):
        print(f'\n⏰ Expiration Transaction {i}:')
        print('-' * 50)
        
        for col_name, value in zip(column_names, row):
            print(f'{col_name}: {value}')
    
    conn.close()

if __name__ == "__main__":
    show_trade_transactions()