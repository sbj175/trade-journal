#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

db = DatabaseManager()

with db.get_connection() as conn:
    cursor = conn.cursor()
    
    print("=== STC Transaction Analysis ===")
    
    # Check raw transactions for STC actions
    print("\n1. Raw STC transactions:")
    cursor.execute("""
        SELECT id, symbol, action, quantity, price, executed_at 
        FROM raw_transactions 
        WHERE action LIKE '%SELL_TO_CLOSE%' 
        ORDER BY executed_at DESC 
        LIMIT 10
    """)
    
    raw_transactions = cursor.fetchall()
    if raw_transactions:
        for txn in raw_transactions:
            print(f"  ID: {txn[0]}")
            print(f"    Symbol: {txn[1]}")
            print(f"    Action: {txn[2]}")
            print(f"    Quantity: {txn[3]} (raw)")
            print(f"    Price: {txn[4]}")
            print(f"    Date: {txn[5]}")
            print()
    else:
        print("  No STC transactions found in raw_transactions")
    
    # Check processed positions for negative quantities
    print("\n2. Processed positions for STC-containing orders:")
    cursor.execute("""
        SELECT DISTINCT o.order_id, o.underlying, p.symbol, p.action, p.quantity, p.price
        FROM orders o
        JOIN positions p ON o.order_id = p.order_id
        WHERE p.action LIKE '%SELL_TO_CLOSE%'
        ORDER BY o.created_at DESC
        LIMIT 10
    """)
    
    processed_positions = cursor.fetchall()
    if processed_positions:
        for pos in processed_positions:
            print(f"  Order: {pos[0]}")
            print(f"    Underlying: {pos[1]}")
            print(f"    Symbol: {pos[2]}")
            print(f"    Action: {pos[3]}")
            print(f"    Quantity: {pos[4]} (processed)")
            print(f"    Price: {pos[5]}")
            print()
    else:
        print("  No STC positions found in processed orders")
    
    # Check for both positive and negative quantities in positions
    print("\n3. Quantity distribution for STC actions:")
    cursor.execute("""
        SELECT 
            CASE 
                WHEN quantity > 0 THEN 'Positive'
                WHEN quantity < 0 THEN 'Negative'
                ELSE 'Zero'
            END as quantity_sign,
            COUNT(*) as count,
            MIN(quantity) as min_qty,
            MAX(quantity) as max_qty
        FROM positions 
        WHERE action LIKE '%SELL_TO_CLOSE%'
        GROUP BY 
            CASE 
                WHEN quantity > 0 THEN 'Positive'
                WHEN quantity < 0 THEN 'Negative'
                ELSE 'Zero'
            END
    """)
    
    qty_distribution = cursor.fetchall()
    if qty_distribution:
        for dist in qty_distribution:
            print(f"  {dist[0]}: {dist[1]} transactions (range: {dist[2]} to {dist[3]})")
    else:
        print("  No quantity distribution data found")
    
    # Sample of actual STC transactions with details
    print("\n4. Sample STC transaction details:")
    cursor.execute("""
        SELECT o.order_id, o.underlying, o.order_type, p.symbol, p.action, p.quantity, p.price, o.created_at
        FROM orders o
        JOIN positions p ON o.order_id = p.order_id
        WHERE p.action LIKE '%SELL_TO_CLOSE%'
        ORDER BY o.created_at DESC
        LIMIT 5
    """)
    
    sample_stc = cursor.fetchall()
    for stc in sample_stc:
        print(f"  Order ID: {stc[0]}")
        print(f"    Underlying: {stc[1]}")
        print(f"    Order Type: {stc[2]}")
        print(f"    Position Symbol: {stc[3]}")
        print(f"    Action: {stc[4]}")
        print(f"    Quantity: {stc[5]}")
        print(f"    Price: {stc[6]}")
        print(f"    Created: {stc[7]}")
        print()