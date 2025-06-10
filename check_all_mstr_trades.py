#!/usr/bin/env python3
import sqlite3
from datetime import datetime
from src.database.db_manager import DatabaseManager

def check_all_mstr_trades():
    db = DatabaseManager()
    
    print("=== All MSTR Trades Analysis ===\n")
    
    # Check all MSTR trades
    query = """
    SELECT 
        t.trade_id,
        t.underlying,
        t.strategy_type,
        t.status,
        t.entry_date,
        t.exit_date,
        t.current_pnl,
        t.net_premium,
        t.account_number
    FROM trades t
    WHERE t.underlying = 'MSTR'
    ORDER BY t.entry_date DESC
    """
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        all_trades = cursor.fetchall()
        
        print(f"Found {len(all_trades)} MSTR trades total:\n")
        
        for trade in all_trades:
            print(f"Trade ID: {trade[0]}")
            print(f"  Strategy: {trade[2]}")
            print(f"  Status: {trade[3]}")
            print(f"  Entry: {trade[4]} | Exit: {trade[5]}")
            print(f"  P&L: ${trade[6]} | Premium: ${trade[7]}")
            print(f"  Account: {trade[8]}")
            
            # Get option legs for this trade
            ol_query = """
            SELECT symbol, option_type, strike, expiration, quantity, 
                   transaction_actions, entry_price, exit_price
            FROM option_legs 
            WHERE trade_id = ?
            """
            cursor.execute(ol_query, (trade[0],))
            option_legs = cursor.fetchall()
            
            if option_legs:
                print(f"  Option Legs:")
                for leg in option_legs:
                    print(f"    {leg[0]} {leg[1]} ${leg[2]} {leg[3]} | Qty: {leg[4]} | Actions: {leg[5]} | Entry: ${leg[6]} | Exit: ${leg[7]}")
            else:
                print(f"  Option Legs: None")
            
            # Get stock legs for this trade
            sl_query = """
            SELECT symbol, quantity, transaction_actions, entry_price, exit_price
            FROM stock_legs 
            WHERE trade_id = ?
            """
            cursor.execute(sl_query, (trade[0],))
            stock_legs = cursor.fetchall()
            
            if stock_legs:
                print(f"  Stock Legs:")
                for leg in stock_legs:
                    print(f"    {leg[0]} | Qty: {leg[1]} | Actions: {leg[2]} | Entry: ${leg[3]} | Exit: ${leg[4]}")
            else:
                print(f"  Stock Legs: None")
            
            print()
    
    # Now let's check for any transactions that might not be properly grouped
    print("\n=== MSTR Raw Transactions ===\n")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        tx_query = """
        SELECT id, symbol, underlying_symbol, transaction_type, action, 
               quantity, price, executed_at, account_number, order_id
        FROM transactions 
        WHERE underlying_symbol = 'MSTR' OR (symbol = 'MSTR' AND transaction_type = 'Trade')
        ORDER BY executed_at DESC
        LIMIT 20
        """
        
        cursor.execute(tx_query)
        transactions = cursor.fetchall()
        
        print(f"Found {len(transactions)} recent MSTR transactions (showing first 20):\n")
        
        for tx in transactions:
            print(f"TX ID: {tx[0]}")
            print(f"  Symbol: {tx[1]} | Underlying: {tx[2]}")
            print(f"  Type: {tx[3]} | Action: {tx[4]}")
            print(f"  Qty: {tx[5]} | Price: ${tx[6]}")
            print(f"  Executed: {tx[7]}")
            print(f"  Account: {tx[8]} | Order: {tx[9]}")
            print()

if __name__ == "__main__":
    check_all_mstr_trades()