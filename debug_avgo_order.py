#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
import json

db = DatabaseManager()

with db.get_connection() as conn:
    cursor = conn.cursor()
    
    print("=== AVGO Order 397395473 Analysis ===\n")
    
    # Get the order details
    cursor.execute("""
        SELECT * FROM orders 
        WHERE order_id = '397395473'
    """)
    
    columns = [desc[0] for desc in cursor.description]
    order = cursor.fetchone()
    
    if order:
        order_dict = dict(zip(columns, order))
        print("Order Details:")
        for key, value in order_dict.items():
            print(f"  {key}: {value}")
        print()
        
        # Get positions for this order
        cursor.execute("""
            SELECT * FROM positions 
            WHERE order_id = '397395473'
        """)
        
        pos_columns = [desc[0] for desc in cursor.description]
        positions = cursor.fetchall()
        
        print(f"\nPositions ({len(positions)} found):")
        for i, pos in enumerate(positions):
            pos_dict = dict(zip(pos_columns, pos))
            print(f"\n  Position {i+1}:")
            print(f"    position_id: {pos_dict.get('position_id')}")
            print(f"    symbol: {pos_dict.get('symbol')}")
            print(f"    quantity: {pos_dict.get('quantity')}")
            print(f"    opening_action: {pos_dict.get('opening_action')}")
            print(f"    closing_action: {pos_dict.get('closing_action')}")
            print(f"    option_type: {pos_dict.get('option_type')}")
            print(f"    strike: {pos_dict.get('strike')}")
            print(f"    status: {pos_dict.get('status')}")
            
        # Check raw transactions for this order
        print("\n\nRaw Transactions:")
        cursor.execute("""
            SELECT id, symbol, action, quantity, price, order_id 
            FROM raw_transactions 
            WHERE order_id = '397395473'
        """)
        
        raw_txns = cursor.fetchall()
        for txn in raw_txns:
            print(f"  Transaction ID: {txn[0]}")
            print(f"    Symbol: {txn[1]}")
            print(f"    Action: {txn[2]}")
            print(f"    Quantity: {txn[3]}")
            print(f"    Price: {txn[4]}")
            print()
    else:
        print("Order 397395473 not found in database")