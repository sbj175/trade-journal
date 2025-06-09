#!/usr/bin/env python3
"""
Debug script to analyze roll linking for IBIT trades
"""
import sqlite3
import json
from datetime import datetime

def connect_db():
    return sqlite3.connect('trade_journal.db')

def extract_position_from_symbol(symbol):
    """Extract position details from symbol like 'IBIT  250509C00055500'"""
    if ' ' in symbol:
        parts = symbol.split()
        if len(parts) >= 2:
            option_code = parts[1]
            if len(option_code) >= 7:
                expiration = option_code[:6]  # YYMMDD 
                option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                strike_str = option_code[7:] if len(option_code) > 7 else '0'
                strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                
                return {
                    'strike': strike,
                    'expiration': expiration,
                    'option_type': option_type,
                    'underlying': parts[0],
                    'symbol': symbol
                }
    return None

def analyze_roll_chain():
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=== IBIT Roll Chain Analysis ===\n")
    
    # Get raw transactions for the specific orders
    cursor.execute("""
        SELECT order_id, transaction_date, action, symbol, description, quantity, price
        FROM raw_transactions 
        WHERE underlying_symbol = 'IBIT' 
        AND account_number LIKE '%959' 
        AND order_id IN ('382168011', '382568608')
        ORDER BY transaction_date, order_id
    """)
    
    transactions = cursor.fetchall()
    
    print("Raw Transactions:")
    for tx in transactions:
        print(f"  {tx[0]} | {tx[1]} | {tx[2]} | {tx[3]} | Qty: {tx[5]} | Price: ${tx[6]}")
    
    print("\n" + "="*60 + "\n")
    
    # Analyze each order
    orders = {}
    for tx in transactions:
        order_id = tx[0]
        if order_id not in orders:
            orders[order_id] = []
        orders[order_id].append(tx)
    
    positions_opened = {}
    positions_closed = {}
    
    for order_id, txs in orders.items():
        print(f"Order {order_id}:")
        
        for tx in txs:
            action = tx[2]
            symbol = tx[3]
            position = extract_position_from_symbol(symbol)
            
            print(f"  {action} | {symbol}")
            if position:
                print(f"    Position: {position}")
                
                if 'OPEN' in action:
                    if order_id not in positions_opened:
                        positions_opened[order_id] = []
                    positions_opened[order_id].append(position)
                elif 'CLOSE' in action:
                    if order_id not in positions_closed:
                        positions_closed[order_id] = []
                    positions_closed[order_id].append(position)
        print()
    
    print("="*60 + "\n")
    
    # Check for roll relationships
    print("Roll Relationship Analysis:")
    
    # Order 382168011 opens positions
    opened_by_382168011 = positions_opened.get('382168011', [])
    closed_by_382568608 = positions_closed.get('382568608', [])
    opened_by_382568608 = positions_opened.get('382568608', [])
    
    print(f"Positions opened by 382168011: {opened_by_382168011}")
    print(f"Positions closed by 382568608: {closed_by_382568608}")
    print(f"Positions opened by 382568608: {opened_by_382568608}")
    
    # Check if any position opened by 382168011 is closed by 382568608
    for opened_pos in opened_by_382168011:
        for closed_pos in closed_by_382568608:
            match = (opened_pos.get('strike') == closed_pos.get('strike') and
                    opened_pos.get('expiration') == closed_pos.get('expiration') and
                    opened_pos.get('option_type') == closed_pos.get('option_type') and
                    opened_pos.get('underlying') == closed_pos.get('underlying'))
            
            if match:
                print(f"\n*** ROLL DETECTED ***")
                print(f"Order 382568608 closes position opened by 382168011:")
                print(f"  Opened: {opened_pos}")
                print(f"  Closed: {closed_pos}")
                
                if opened_by_382568608:
                    print(f"  And opens new position: {opened_by_382568608[0]}")
                    print(f"\n*** This should link trades IBIT_20250505_1legs_959 → IBIT_20250507_2legs_959 ***")
                
                return True
    
    print("\nNo roll relationship detected by the matching logic")
    return False

def check_current_trade_data():
    """Check what the current trade data shows"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("\n" + "="*60)
    print("Current Trade Data:")
    print("="*60 + "\n")
    
    # Get the specific trades
    trade_ids = ['IBIT_20250505_1legs_959', 'IBIT_20250507_2legs_959']
    
    for trade_id in trade_ids:
        cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
        trade = cursor.fetchone()
        
        if trade:
            print(f"Trade: {trade[0]}")
            print(f"  Strategy: {trade[2]}")  
            print(f"  Entry Date: {trade[3]}")
            print(f"  Status: {trade[5]}")
            print(f"  Includes Roll: {trade[15]}")  # includes_roll column
            
            # Get option legs
            cursor.execute("""
                SELECT symbol, transaction_actions, order_id 
                FROM option_legs 
                WHERE trade_id = ?
            """, (trade_id,))
            
            legs = cursor.fetchall()
            for leg in legs:
                actions = json.loads(leg[1]) if leg[1] else []
                print(f"  Leg: {leg[0]} | Actions: {actions} | Order ID: {leg[2]}")
            print()
    
    conn.close()

if __name__ == "__main__":
    roll_detected = analyze_roll_chain()
    check_current_trade_data()
    
    if roll_detected:
        print("\n*** CONCLUSION: Roll chain logic should work, but trades are not linked ***")
        print("*** Issue is likely in the grouping or linking implementation ***")
    else:
        print("\n*** CONCLUSION: Roll matching logic has a bug ***")