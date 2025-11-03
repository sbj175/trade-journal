#!/usr/bin/env python3
"""
Check the IBIT order data structure
"""

import sqlite3

def check_ibit_data():
    """Check the IBIT data structure"""
    
    print("Checking IBIT Order Data Structure")
    print("=" * 50)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get column names
        cursor.execute("PRAGMA table_info(positions_new)")
        columns = cursor.fetchall()
        print("Columns in positions_new:")
        for col in columns:
            print(f"   {col[1]} ({col[2]})")
        
        # Get the actual data for IBIT order
        cursor.execute("""
            SELECT * FROM positions_new 
            WHERE order_id = '388512672'
            LIMIT 1
        """)
        
        sample_row = cursor.fetchone()
        if sample_row:
            print(f"\nSample row data:")
            for i, col in enumerate(columns):
                col_name = col[1]
                value = sample_row[i] if i < len(sample_row) else None
                print(f"   {col_name}: {value}")
        
        # Check specifically for option type data
        cursor.execute("""
            SELECT symbol, quantity, opening_action, option_type, strike, expiration
            FROM positions_new 
            WHERE order_id = '388512672'
            ORDER BY strike
        """)
        
        positions = cursor.fetchall()
        print(f"\nIBIT Order 388512672 Positions:")
        for pos in positions:
            symbol, qty, action, opt_type, strike, exp = pos
            print(f"   {action} {qty}x {symbol} ${strike} {opt_type} {exp}")
            
            # Parse symbol to determine if it's a call or put
            if 'C' in symbol and symbol.endswith('000'):
                parsed_type = "CALL"
            elif 'P' in symbol and symbol.endswith('000'):
                parsed_type = "PUT"
            else:
                parsed_type = "UNKNOWN"
            
            print(f"      Option type from DB: '{opt_type}'")
            print(f"      Option type from symbol: '{parsed_type}'")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_ibit_data()