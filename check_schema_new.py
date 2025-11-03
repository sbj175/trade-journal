#!/usr/bin/env python3
"""
Check database schema
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

def check_schema():
    """Check the database schema"""
    
    db = DatabaseManager()
    db.ensure_initialized()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        print("Available tables:")
        for table in tables:
            print(f"  {table}")
        
        print("\n=== ORDERS TABLE SCHEMA ===")
        cursor.execute("PRAGMA table_info(orders)")
        orders_columns = cursor.fetchall()
        for col in orders_columns:
            print(f"  {col[1]} ({col[2]})")
        
        print("\n=== SAMPLE ORDERS ===")
        cursor.execute("SELECT * FROM orders LIMIT 3")
        sample_orders = cursor.fetchall()
        for order in sample_orders:
            print(f"  {dict(order)}")
        
        print("\n=== FIND ORDER 397401079 ===")
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", ('397401079',))
        target_order = cursor.fetchone()
        if target_order:
            print(f"Found: {dict(target_order)}")
        else:
            print("Order 397401079 not found")

if __name__ == "__main__":
    check_schema()