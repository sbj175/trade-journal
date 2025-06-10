#!/usr/bin/env python3
"""
Test the position-based order linking logic for CLOSING orders
"""
import sqlite3
from datetime import datetime, timedelta

def test_position_matching():
    """Test if the position matching logic works for our specific orders"""
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get the order details
    cursor.execute("SELECT * FROM orders WHERE order_id IN ('374805462', '375108991') ORDER BY order_date")
    orders = cursor.fetchall()
    
    if len(orders) != 2:
        print(f"Expected 2 orders, found {len(orders)}")
        return
    
    opening_order = orders[0]  # 374805462
    closing_order = orders[1]  # 375108991
    
    print("=== TESTING POSITION MATCHING LOGIC ===")
    print(f"Opening order: {opening_order[0]} ({opening_order[3]}) on {opening_order[5]}")
    print(f"Closing order: {closing_order[0]} ({closing_order[3]}) on {closing_order[5]}")
    
    # Convert to dict format for easier access
    columns = ['order_id', 'account_number', 'underlying', 'order_type', 'strategy_type', 'order_date', 'status', 'total_quantity', 'total_pnl', 'has_assignment', 'has_expiration', 'has_exercise', 'linked_order_id']
    
    prev_order = dict(zip(columns, opening_order))
    candidate_order = dict(zip(columns, closing_order))
    
    print(f"\nPrev order dict: {prev_order}")
    print(f"Candidate order dict: {candidate_order}")
    
    # Test the matching logic step by step
    print(f"\n=== STEP-BY-STEP MATCHING TEST ===")
    
    # 1. Time proximity check
    try:
        prev_date = datetime.fromisoformat(prev_order['order_date'])
        candidate_date = datetime.fromisoformat(candidate_order['order_date'])
        
        print(f"Prev date: {prev_date}")
        print(f"Candidate date: {candidate_date}")
        
        time_diff = candidate_date - prev_date
        print(f"Time difference: {time_diff}")
        
        if candidate_date <= prev_date:
            print("❌ FAIL: Candidate is not after previous order")
            return False
        
        if time_diff > timedelta(days=30):
            print("❌ FAIL: Time difference is more than 30 days")
            return False
            
        print("✅ PASS: Time proximity check")
        
    except Exception as e:
        print(f"❌ FAIL: Time parsing error: {e}")
        return False
    
    # 2. Account and underlying check
    if (prev_order['account_number'] != candidate_order['account_number'] or
        prev_order['underlying'] != candidate_order['underlying']):
        print("❌ FAIL: Account or underlying mismatch")
        return False
    
    print("✅ PASS: Account and underlying match")
    
    # 3. Get open positions from previous order
    cursor.execute("""
        SELECT symbol, underlying, option_type, strike, expiration, quantity
        FROM positions_new 
        WHERE order_id = ? AND status = 'OPEN'
    """, (prev_order['order_id'],))
    
    prev_open_positions = cursor.fetchall()
    print(f"Previous order open positions: {prev_open_positions}")
    
    if not prev_open_positions:
        print("❌ FAIL: No open positions from previous order")
        return False
    
    # 4. Get closing transactions from candidate order
    cursor.execute("""
        SELECT rt.symbol, rt.underlying_symbol, rt.quantity, rt.action
        FROM raw_transactions rt
        WHERE rt.order_id = ? 
        AND (rt.action LIKE '%BTC%' OR rt.action LIKE '%STC%' OR rt.action LIKE '%CLOSE%')
    """, (candidate_order['order_id'],))
    
    closing_transactions = cursor.fetchall()
    print(f"Closing transactions: {closing_transactions}")
    
    if not closing_transactions:
        print("❌ FAIL: No closing transactions in candidate order")
        return False
    
    # 5. Convert closing transactions to position keys
    closing_position_keys = set()
    for tx in closing_transactions:
        symbol = tx[0]
        if symbol and ' ' in symbol and len(symbol.split()) >= 2:
            parts = symbol.split()
            option_code = parts[1]
            try:
                expiration = option_code[:6]  # YYMMDD
                option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                strike_str = option_code[8:] if len(option_code) > 8 else option_code[7:]
                strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                
                # Convert expiration to same format as positions table
                year = 2000 + int(expiration[:2])
                month = int(expiration[2:4])
                day = int(expiration[4:6])
                exp_date = f"{year:04d}-{month:02d}-{day:02d}"
                
                position_key = (symbol.strip(), option_type, strike, exp_date)
                closing_position_keys.add(position_key)
                print(f"Closing position key: {position_key}")
            except (ValueError, IndexError) as e:
                print(f"Error parsing option symbol {symbol}: {e}")
                continue
    
    # 6. Convert previous open positions to same format
    prev_position_keys = set()
    for pos in prev_open_positions:
        symbol, underlying, option_type, strike, expiration = pos[:5]
        position_key = (symbol.strip(), option_type, strike, expiration)
        prev_position_keys.add(position_key)
        print(f"Previous position key: {position_key}")
    
    # 7. Check for matches
    matches = closing_position_keys.intersection(prev_position_keys)
    print(f"Matching position keys: {matches}")
    
    if len(matches) > 0:
        print(f"✅ SUCCESS: Found {len(matches)} matching positions!")
        print("These orders should be linked in the same chain.")
        return True
    else:
        print("❌ FAIL: No matching positions found")
        return False
    
    conn.close()

if __name__ == "__main__":
    success = test_position_matching()
    
    if success:
        print("\n🎉 Position matching logic should work!")
        print("The issue might be that the chain detection logic needs to be re-run.")
    else:
        print("\n❌ Position matching logic has issues that need to be fixed.")