#!/usr/bin/env python3
"""
Backup script for obsolete tables before dropping them
"""
import sqlite3
import json
from datetime import datetime

def backup_obsolete_tables():
    """Backup obsolete tables to JSON files"""
    db_path = "trade_journal.db"
    backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    obsolete_tables = ['trades', 'option_legs', 'stock_legs', 'positions_new']
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        for table in obsolete_tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                # Convert to list of dicts for JSON serialization
                data = [dict(row) for row in rows]
                
                # Save to JSON file
                filename = f"backup_{table}_{backup_timestamp}.json"
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                
                print(f"Backed up {len(data)} rows from {table} to {filename}")
                
            except Exception as e:
                print(f"Error backing up {table}: {str(e)}")

if __name__ == "__main__":
    backup_obsolete_tables()