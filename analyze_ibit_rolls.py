#!/usr/bin/env python3
"""
Analyze IBIT roll transactions to understand why rolls only show STO
"""
import sqlite3
import json
from datetime import datetime
import pytz

def connect_db():
    """Connect to the trade journal database"""
    return sqlite3.connect('trade_journal.db')

def analyze_ibit_rolls():
    """Analyze IBIT roll transactions"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== IBIT Roll Analysis ===\n")
    
    # Query all IBIT transactions from May 7 (the roll date)
    query = """
    SELECT 
        id, symbol, action, transaction_type, transaction_sub_type, 
        quantity, price, executed_at, order_id, description
    FROM raw_transactions 
    WHERE underlying_symbol = 'IBIT' 
    AND date(executed_at) = '2025-05-07'
    ORDER BY executed_at
    """
    
    cursor.execute(query)
    transactions = cursor.fetchall()
    
    print(f"Found {len(transactions)} IBIT transactions on May 7, 2025:\n")
    
    for tx in transactions:
        print(f"ID: {tx[0]}")
        print(f"Symbol: {tx[1]}")
        print(f"Action: {tx[2]}")
        print(f"Type/SubType: {tx[3]} / {tx[4]}")
        print(f"Qty: {tx[5]}, Price: ${tx[6]}")
        print(f"Time: {tx[7]}")
        print(f"Order ID: {tx[8]}")
        print(f"Description: {tx[9]}")
        print("-" * 50)
    
    # Now look at how these are grouped into trades
    print("\n=== Trade Grouping Analysis ===\n")
    
    # Query the trades created from these transactions
    query = """
    SELECT 
        t.trade_id, t.strategy_type, t.status, t.includes_roll,
        ol.symbol, ol.transaction_actions, ol.transaction_ids
    FROM trades t
    JOIN option_legs ol ON t.trade_id = ol.trade_id
    WHERE t.underlying = 'IBIT'
    AND (ol.symbol LIKE '%250509C00055500%' OR ol.symbol LIKE '%250516C00058000%')
    ORDER BY t.trade_id
    """
    
    cursor.execute(query)
    trades = cursor.fetchall()
    
    print(f"Found {len(trades)} trade legs involving the roll:\n")
    
    for trade in trades:
        print(f"Trade ID: {trade[0]}")
        print(f"Strategy: {trade[1]}, Status: {trade[2]}, Includes Roll: {trade[3]}")
        print(f"Symbol: {trade[4]}")
        print(f"Actions: {trade[5]}")
        print(f"Transaction IDs: {trade[6]}")
        print("-" * 50)
    
    # Check for orders with same order_id (indicating a roll)
    print("\n=== Order ID Analysis ===\n")
    
    query = """
    SELECT order_id, COUNT(*) as tx_count, 
           GROUP_CONCAT(symbol || ' ' || action, ', ') as transactions
    FROM raw_transactions
    WHERE underlying_symbol = 'IBIT'
    AND date(executed_at) = '2025-05-07'
    AND order_id IS NOT NULL
    GROUP BY order_id
    HAVING tx_count > 1
    """
    
    cursor.execute(query)
    orders = cursor.fetchall()
    
    print(f"Found {len(orders)} orders with multiple transactions (potential rolls):\n")
    
    for order in orders:
        print(f"Order ID: {order[0]}")
        print(f"Transaction Count: {order[1]}")
        print(f"Transactions: {order[2]}")
        print("-" * 50)
    
    conn.close()

if __name__ == "__main__":
    analyze_ibit_rolls()