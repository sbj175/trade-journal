#!/usr/bin/env python3
"""
Show sample raw transaction data from Tastytrade
"""

import sqlite3
import json

def show_raw_transactions():
    """Show a few raw transactions with all fields"""
    
    print('🔍 Sample Raw Transaction Data from Tastytrade')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get the schema first
    cursor.execute("PRAGMA table_info(raw_transactions)")
    columns = cursor.fetchall()
    
    print('Raw Transactions Table Schema:')
    for col in columns:
        col_id, name, data_type, not_null, default, pk = col
        print(f'  {name}: {data_type}')
    
    print('\n' + '='*60)
    print('Sample Transaction Records:')
    print('='*60)
    
    # Get a few sample transactions
    cursor.execute("SELECT * FROM raw_transactions LIMIT 3")
    rows = cursor.fetchall()
    
    # Get column names
    cursor.execute("PRAGMA table_info(raw_transactions)")
    column_info = cursor.fetchall()
    column_names = [col[1] for col in column_info]
    
    for i, row in enumerate(rows, 1):
        print(f'\n📋 Transaction {i}:')
        print('-' * 40)
        
        for col_name, value in zip(column_names, row):
            if col_name == 'raw_data' and value:
                # Pretty print the JSON data
                try:
                    parsed_data = json.loads(value)
                    print(f'{col_name}:')
                    print(json.dumps(parsed_data, indent=2))
                except:
                    print(f'{col_name}: {value}')
            else:
                print(f'{col_name}: {value}')
    
    conn.close()

if __name__ == "__main__":
    show_raw_transactions()