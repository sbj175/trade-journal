#!/usr/bin/env python3
"""
Simple database query tool for the trade journal
"""
import sqlite3
import json
import sys
from datetime import datetime

def connect_db():
    """Connect to the trade journal database"""
    return sqlite3.connect('trade_journal.db')

def query_trade_legs(trade_id=None):
    """Query option and stock legs for a specific trade or all trades"""
    conn = connect_db()
    cursor = conn.cursor()
    
    if trade_id:
        print(f"\n=== Trade Details for {trade_id} ===")
        
        # Get trade info
        cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
        trade = cursor.fetchone()
        if trade:
            print(f"Trade: {trade[0]} | {trade[2]} | {trade[3]} | {trade[5]}")
        
        # Get option legs
        cursor.execute("""
            SELECT symbol, strike, option_type, quantity, entry_price, exit_price, 
                   transaction_actions, transaction_timestamps 
            FROM option_legs 
            WHERE trade_id = ? 
            ORDER BY strike
        """, (trade_id,))
        
        option_legs = cursor.fetchall()
        if option_legs:
            print(f"\nOption Legs ({len(option_legs)}):")
            for leg in option_legs:
                actions = json.loads(leg[6]) if leg[6] else []
                timestamps = json.loads(leg[7]) if leg[7] else []
                print(f"  {leg[0]} | {leg[2]} ${leg[1]} | Qty: {leg[3]} | Entry: ${leg[4]} | Actions: {actions}")
        
        # Get stock legs
        cursor.execute("""
            SELECT symbol, quantity, entry_price, exit_price, 
                   transaction_actions, transaction_timestamps 
            FROM stock_legs 
            WHERE trade_id = ?
        """, (trade_id,))
        
        stock_legs = cursor.fetchall()
        if stock_legs:
            print(f"\nStock Legs ({len(stock_legs)}):")
            for leg in stock_legs:
                actions = json.loads(leg[4]) if leg[4] else []
                timestamps = json.loads(leg[5]) if leg[5] else []
                print(f"  {leg[0]} | Qty: {leg[1]} | Entry: ${leg[2]} | Actions: {actions}")
    
    else:
        print("\n=== All Trades ===")
        cursor.execute("SELECT trade_id, underlying, strategy_type, status FROM trades ORDER BY entry_date DESC")
        trades = cursor.fetchall()
        for trade in trades:
            print(f"{trade[0]} | {trade[1]} | {trade[2]} | {trade[3]}")
    
    conn.close()

def query_tables():
    """Show all tables and their structure"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("\n=== Database Tables ===")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table[0]
        print(f"\n{table_name}:")
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]} ({col[2]})")
    
    conn.close()

def custom_query(sql):
    """Execute a custom SQL query"""
    conn = connect_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(sql)
        results = cursor.fetchall()
        
        # Get column names
        columns = [description[0] for description in cursor.description]
        print(" | ".join(columns))
        print("-" * (len(" | ".join(columns))))
        
        for row in results:
            print(" | ".join(str(cell) for cell in row))
        
        print(f"\n{len(results)} rows returned")
        
    except Exception as e:
        print(f"Error: {e}")
    
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "tables":
            query_tables()
        elif sys.argv[1] == "query":
            if len(sys.argv) > 2:
                custom_query(" ".join(sys.argv[2:]))
            else:
                print("Usage: python query_db.py query 'SELECT * FROM trades LIMIT 5'")
        else:
            # Assume it's a trade ID
            query_trade_legs(sys.argv[1])
    else:
        query_trade_legs()
        print("\nUsage:")
        print("  python query_db.py                    # List all trades")
        print("  python query_db.py TRADE_ID          # Show specific trade details")
        print("  python query_db.py tables            # Show database structure")
        print("  python query_db.py query 'SQL...'    # Execute custom query")