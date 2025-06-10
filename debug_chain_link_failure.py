#!/usr/bin/env python3
"""
Debug why chain detection failed to link order 380871211 to order 380086981
"""
import sqlite3
from datetime import datetime, timedelta

def is_position_based_roll_continuation(prev_order, candidate_order, conn):
    """
    Check if candidate order is a roll/close continuation based on matching positions
    """
    cursor = conn.cursor()
    
    print(f"\n=== DEBUGGING POSITION MATCHING ===")
    print(f"Previous order: {prev_order['order_id']} ({prev_order['order_date']})")
    print(f"Candidate order: {candidate_order['order_id']} ({candidate_order['order_date']})")
    
    # Must be within reasonable time frame (30 days) and after previous order
    try:
        prev_date = datetime.fromisoformat(prev_order['order_date'])
        candidate_date = datetime.fromisoformat(candidate_order['order_date'])
        
        print(f"Previous date: {prev_date}")
        print(f"Candidate date: {candidate_date}")
        
        if candidate_date <= prev_date:
            print("❌ FAIL: Candidate date not after previous date")
            return False
        
        time_diff = candidate_date - prev_date
        print(f"Time difference: {time_diff}")
        
        if time_diff > timedelta(days=30):
            print("❌ FAIL: Time difference > 30 days")
            return False
        
        print("✅ PASS: Time validation")
    except Exception as e:
        print(f"❌ FAIL: Date parsing error: {e}")
        return False
    
    # Must be same account and underlying
    print(f"Previous account: '{prev_order['account_number']}'")
    print(f"Candidate account: '{candidate_order['account_number']}'")
    print(f"Previous underlying: '{prev_order['underlying']}'")
    print(f"Candidate underlying: '{candidate_order['underlying']}'")
    
    if (prev_order['account_number'] != candidate_order['account_number'] or
        prev_order['underlying'] != candidate_order['underlying']):
        print("❌ FAIL: Account or underlying mismatch")
        return False
    
    print("✅ PASS: Account and underlying match")
    
    # Get open positions from previous order
    cursor.execute("""
        SELECT symbol, underlying, option_type, strike, expiration, quantity
        FROM positions_new 
        WHERE order_id = ? AND status = 'OPEN'
    """, (prev_order['order_id'],))
    
    prev_open_positions = cursor.fetchall()
    print(f"\nOpen positions from previous order ({len(prev_open_positions)}):")
    for pos in prev_open_positions:
        print(f"  Symbol: {pos[0]}, Type: {pos[2]}, Strike: {pos[3]}, Exp: {pos[4]}, Qty: {pos[5]}")
    
    if not prev_open_positions:
        print("❌ FAIL: No open positions from previous order")
        return False
    
    # Get closing transactions from candidate rolling order
    cursor.execute("""
        SELECT rt.symbol, rt.underlying_symbol, rt.quantity, rt.action
        FROM raw_transactions rt
        WHERE rt.order_id = ? 
        AND (rt.action LIKE '%BTC%' OR rt.action LIKE '%STC%' OR rt.action LIKE '%CLOSE%')
    """, (candidate_order['order_id'],))
    
    closing_transactions = cursor.fetchall()
    print(f"\nClosing transactions from candidate order ({len(closing_transactions)}):")
    for tx in closing_transactions:
        print(f"  Symbol: {tx[0]}, Underlying: {tx[1]}, Qty: {tx[2]}, Action: {tx[3]}")
    
    if not closing_transactions:
        print("❌ FAIL: No closing transactions in candidate order")
        return False
    
    # Convert closing transactions to position keys for matching
    closing_position_keys = set()
    print(f"\nParsing closing transactions:")
    for tx in closing_transactions:
        symbol = tx[0]
        instrument_type = 'EQUITY_OPTION' if symbol and len(symbol.split()) >= 2 else 'EQUITY'
        
        print(f"  Processing: {symbol} -> {instrument_type}")
        
        if instrument_type == 'EQUITY_OPTION':
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                print(f"    Option code: {option_code}")
                try:
                    expiration = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[8:] if len(option_code) > 8 else option_code[7:]
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    print(f"    Parsed - Exp: {expiration}, Type: {option_type}, Strike str: '{strike_str}', Strike: {strike}")
                    
                    # Convert expiration to same format as positions table
                    year = 2000 + int(expiration[:2])
                    month = int(expiration[2:4])
                    day = int(expiration[4:6])
                    exp_date = f"{year:04d}-{month:02d}-{day:02d}"
                    
                    print(f"    Converted exp date: {exp_date}")
                    
                    position_key = (symbol.strip(), option_type, strike, exp_date)
                    closing_position_keys.add(position_key)
                    print(f"    Position key: {position_key}")
                except (ValueError, IndexError) as e:
                    print(f"    ❌ Parse error: {e}")
                    continue
        else:
            # Stock position
            position_key = (symbol.strip(), None, None, None)
            closing_position_keys.add(position_key)
            print(f"    Stock position key: {position_key}")
    
    # Convert previous open positions to same format for comparison
    prev_position_keys = set()
    print(f"\nConverting previous open positions:")
    for pos in prev_open_positions:
        symbol, underlying, option_type, strike, expiration = pos[:5]
        position_key = (symbol.strip(), option_type, strike, expiration)
        prev_position_keys.add(position_key)
        print(f"  {position_key}")
    
    # Check if closing transactions match any previous open positions
    print(f"\nMatching positions:")
    print(f"Previous position keys: {prev_position_keys}")
    print(f"Closing position keys: {closing_position_keys}")
    
    matches = closing_position_keys.intersection(prev_position_keys)
    print(f"Matches: {matches}")
    
    success = len(matches) > 0
    print(f"\n{'✅ SUCCESS' if success else '❌ FAIL'}: Match result = {success}")
    
    return success

def debug_chain_linking():
    """Debug the specific chain linking failure"""
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    try:
        print("=== DEBUGGING CHAIN LINKING FAILURE ===")
        print("Orders: 380086981 -> 380871211")
        
        # Get order details
        cursor.execute("""
            SELECT order_id, account_number, underlying, order_date, order_type, strategy_type, 
                   has_expiration, has_assignment, has_exercise
            FROM orders 
            WHERE order_id IN ('380086981', '380871211')
            ORDER BY order_date
        """)
        
        orders = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        
        if len(orders) != 2:
            print(f"❌ ERROR: Expected 2 orders, found {len(orders)}")
            return
        
        order_dicts = []
        for order in orders:
            order_dict = dict(zip(columns, order))
            order_dicts.append(order_dict)
            print(f"\nOrder {order_dict['order_id']}:")
            print(f"  Account: {order_dict['account_number']}")
            print(f"  Underlying: {order_dict['underlying']}")
            print(f"  Date: {order_dict['order_date']}")
            print(f"  Type: {order_dict['order_type']}")
            print(f"  Strategy: {order_dict['strategy_type']}")
            print(f"  System closed: {order_dict['has_expiration'] or order_dict['has_assignment'] or order_dict['has_exercise']}")
        
        prev_order = order_dicts[0]  # 380086981
        candidate_order = order_dicts[1]  # 380871211
        
        # Check the specific linking conditions
        print(f"\n=== CHECKING LINKING CONDITIONS ===")
        
        # 1. Check if first order is system closed
        is_system_closed = (prev_order['has_expiration'] or prev_order['has_assignment'] or prev_order['has_exercise'])
        print(f"1. Previous order system closed: {is_system_closed}")
        if is_system_closed:
            print("   ❌ Previous order is system closed - won't build chain")
        
        # 2. Check if first order is CLOSING type
        is_closing_type = prev_order['order_type'] == 'CLOSING'
        print(f"2. Previous order is CLOSING type: {is_closing_type}")
        if is_closing_type:
            print("   ❌ Previous order is CLOSING type - won't build chain")
        
        # 3. Check if candidate is ROLLING or CLOSING
        is_valid_continuation = candidate_order['order_type'] in ['ROLLING', 'CLOSING']
        print(f"3. Candidate is ROLLING/CLOSING: {is_valid_continuation}")
        if not is_valid_continuation:
            print(f"   ❌ Candidate type '{candidate_order['order_type']}' not valid for continuation")
        
        # 4. Check if candidate is system closed (FIXED: this should not block linking)
        candidate_system_closed = (candidate_order['has_expiration'] or candidate_order['has_assignment'] or candidate_order['has_exercise'])
        print(f"4. Candidate order system closed: {candidate_system_closed}")
        print("   ✅ FIXED: System closed orders can now be linked as continuations")
        
        # If all basic checks pass, test position matching
        if (not is_system_closed and not is_closing_type and 
            is_valid_continuation):
            print(f"\n5. Testing position-based matching...")
            match_result = is_position_based_roll_continuation(prev_order, candidate_order, conn)
            print(f"   Position matching result: {match_result}")
        else:
            print(f"\n❌ FAILED basic linking conditions - position matching not attempted")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    debug_chain_linking()