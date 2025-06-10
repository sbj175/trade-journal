#!/usr/bin/env python3
import sqlite3
from datetime import datetime
from src.database.db_manager import DatabaseManager

def check_mstr_covered_calls():
    db = DatabaseManager()
    
    print("=== MSTR Naked Call Analysis ===\n")
    
    # First, let's check all MSTR trades with strategy_type 'Naked Call'
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
        GROUP_CONCAT(ol.symbol || ' (' || ol.transaction_actions || ' ' || ol.quantity || ')') as option_legs,
        GROUP_CONCAT(sl.symbol || ' (' || sl.transaction_actions || ' ' || sl.quantity || ')') as stock_legs
    FROM trades t
    LEFT JOIN option_legs ol ON t.trade_id = ol.trade_id
    LEFT JOIN stock_legs sl ON t.trade_id = sl.trade_id
    WHERE t.underlying = 'MSTR' AND t.strategy_type = 'Naked Call'
    GROUP BY t.trade_id
    ORDER BY t.entry_date DESC
    """
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        naked_calls = cursor.fetchall()
    
    print(f"Found {len(naked_calls)} MSTR trades classified as 'Naked Call':\n")
    
    for trade in naked_calls:
        print(f"Trade ID: {trade[0]}")
        print(f"  Underlying: {trade[1]}")
        print(f"  Strategy: {trade[2]}")
        print(f"  Status: {trade[3]}")
        print(f"  Entry Date: {trade[4]}")
        print(f"  Exit Date: {trade[5]}")
        print(f"  P&L: ${trade[6]}")
        print(f"  Net Premium: ${trade[7]}")
        print(f"  Option Legs: {trade[8]}")
        print(f"  Stock Legs: {trade[9]}")
        print()
    
    # Now let's check for MSTR stock positions that could indicate covered calls
    print("\n=== MSTR Stock Positions ===\n")
    
    stock_query = """
    SELECT 
        sl.trade_id,
        sl.symbol,
        sl.transaction_actions,
        sl.quantity,
        sl.entry_price,
        sl.transaction_timestamps,
        t.strategy_type,
        t.status
    FROM stock_legs sl
    JOIN trades t ON sl.trade_id = t.trade_id
    WHERE sl.symbol = 'MSTR'
    ORDER BY sl.transaction_timestamps DESC
    """
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(stock_query)
        stock_positions = cursor.fetchall()
    
    print(f"Found {len(stock_positions)} MSTR stock positions:\n")
    
    for pos in stock_positions:
        print(f"Trade ID: {pos[0]}")
        print(f"  Symbol: {pos[1]}")
        print(f"  Actions: {pos[2]}")
        print(f"  Quantity: {pos[3]}")
        print(f"  Entry Price: ${pos[4]}")
        print(f"  Timestamps: {pos[5]}")
        print(f"  Strategy Type: {pos[6]}")
        print(f"  Status: {pos[7]}")
        print()
    
    # Check for potential covered calls - trades with both call options and stock
    print("\n=== Potential Covered Calls Analysis ===\n")
    
    covered_call_query = """
    SELECT 
        t.trade_id,
        t.strategy_type,
        t.status,
        t.entry_date,
        ol.symbol as option_symbol,
        ol.transaction_actions as option_action,
        ol.quantity as option_qty,
        sl.symbol,
        sl.transaction_actions as stock_action,
        sl.quantity as stock_qty
    FROM trades t
    JOIN option_legs ol ON t.trade_id = ol.trade_id
    LEFT JOIN stock_legs sl ON t.trade_id = sl.trade_id
    WHERE t.underlying = 'MSTR' 
    AND ol.option_type = 'C'  -- Call options
    AND ol.transaction_actions LIKE '%SELL_TO_OPEN%'   -- Selling calls
    ORDER BY t.entry_date DESC
    """
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(covered_call_query)
        potential_covered_calls = cursor.fetchall()
    
    print(f"MSTR trades with sold call options:\n")
    
    covered_call_candidates = []
    naked_call_candidates = []
    
    for trade in potential_covered_calls:
        trade_id = trade[0]
        strategy_type = trade[1]
        has_stock = trade[7] is not None  # stock symbol exists
        stock_action = trade[8] if has_stock else None
        stock_qty = trade[9] if has_stock else 0
        option_qty = abs(trade[6])  # option quantity (make positive)
        
        print(f"Trade ID: {trade_id}")
        print(f"  Current Strategy: {strategy_type}")
        print(f"  Option: {trade[4]} ({trade[5]} {trade[6]})")
        if has_stock:
            print(f"  Stock: {trade[7]} ({stock_action} {stock_qty})")
            # Check if stock quantity covers the call quantity
            if 'BUY' in str(stock_action or '') and stock_qty >= option_qty * 100:
                print(f"  --> SHOULD BE COVERED CALL (has {stock_qty} shares for {option_qty} contracts)")
                covered_call_candidates.append(trade_id)
            else:
                print(f"  --> Stock position insufficient for covered call")
        else:
            print(f"  Stock: None")
            print(f"  --> NAKED CALL (no stock position)")
            naked_call_candidates.append(trade_id)
        print()
    
    print(f"\n=== Summary ===")
    print(f"Trades that should be COVERED CALLS: {len(covered_call_candidates)}")
    print(f"Trade IDs: {covered_call_candidates}")
    print(f"\nTrades correctly classified as NAKED CALLS: {len(naked_call_candidates)}")
    print(f"Trade IDs: {naked_call_candidates}")
    
    # Check if there are any MSTR trades with multiple legs that might indicate order chains
    print(f"\n=== MSTR Order Chain Analysis ===\n")
    
    order_chain_query = """
    SELECT 
        t.trade_id,
        t.strategy_type,
        t.status,
        t.entry_date,
        COUNT(ol.symbol) as option_leg_count,
        COUNT(sl.symbol) as stock_leg_count,
        GROUP_CONCAT(DISTINCT ol.symbol) as all_options,
        GROUP_CONCAT(DISTINCT sl.symbol) as all_stocks
    FROM trades t
    LEFT JOIN option_legs ol ON t.trade_id = ol.trade_id
    LEFT JOIN stock_legs sl ON t.trade_id = sl.trade_id
    WHERE t.underlying = 'MSTR'
    GROUP BY t.trade_id
    HAVING option_leg_count > 1 OR stock_leg_count > 0
    ORDER BY t.entry_date DESC
    """
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(order_chain_query)
        complex_trades = cursor.fetchall()
    
    print(f"MSTR trades with multiple legs or stock components:\n")
    
    for trade in complex_trades:
        print(f"Trade ID: {trade[0]}")
        print(f"  Strategy: {trade[1]}")
        print(f"  Status: {trade[2]}")
        print(f"  Entry Date: {trade[3]}")
        print(f"  Option Legs: {trade[4]} ({trade[6]})")
        print(f"  Stock Legs: {trade[5]} ({trade[7]})")
        print()

if __name__ == "__main__":
    check_mstr_covered_calls()