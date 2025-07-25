#!/usr/bin/env python3
"""Test script to verify expiration transaction processing"""

import sys
import sqlite3
sys.path.append('.')

# Test the new system event detection
from src.models.order_models import OrderManager
from src.database.db_manager import DatabaseManager

def test_system_event_detection():
    print("Testing system event detection...")
    
    db = DatabaseManager()
    order_manager = OrderManager(db)
    
    # Get a sample expiration transaction
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT *
        FROM raw_transactions
        WHERE description LIKE '%due to expiration%'
        LIMIT 1
    ''')
    
    row = cursor.fetchone()
    if not row:
        print("No expiration transactions found")
        return
    
    # Convert to dict
    columns = [description[0] for description in cursor.description]
    transaction = dict(zip(columns, row))
    
    print(f"Sample expiration transaction: {transaction['id']}")
    print(f"Description: {transaction['description']}")
    print(f"Action: {transaction['action']}")
    
    # Test detection
    is_system = order_manager.is_system_event(transaction)
    event_type = order_manager.get_system_event_type(transaction)
    
    print(f"Is system event: {is_system}")
    print(f"Event type: {event_type}")
    
    # Test synthetic order ID generation
    if is_system:
        tx_id = transaction.get('id', 'UNKNOWN')
        synthetic_id = f"SYSTEM_{event_type}_{tx_id}"
        print(f"Synthetic order ID: {synthetic_id}")
    
    conn.close()

def check_expiration_orders():
    print("\nChecking if expiration orders are being created...")
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Look for orders that start with SYSTEM_EXPIRATION
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM orders
        WHERE order_id LIKE 'SYSTEM_EXPIRATION_%'
    ''')
    
    count = cursor.fetchone()[0]
    print(f"Found {count} expiration orders in database")
    
    if count > 0:
        cursor.execute('''
            SELECT order_id, order_date, order_type, underlying, has_expiration
            FROM orders
            WHERE order_id LIKE 'SYSTEM_EXPIRATION_%'
            ORDER BY order_date
            LIMIT 5
        ''')
        
        print("\nFirst 5 expiration orders:")
        for row in cursor.fetchall():
            print(f"  {row[0]} | {row[1]} | {row[2]} | {row[3]} | Expired: {row[4]}")
    
    conn.close()

if __name__ == "__main__":
    test_system_event_detection()
    check_expiration_orders()