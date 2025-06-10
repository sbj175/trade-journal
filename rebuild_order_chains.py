#!/usr/bin/env python3
"""
Rebuild order chains with the updated chain detection logic that links CLOSING orders
"""
import sqlite3
from datetime import datetime, timedelta

def is_position_based_roll_continuation(prev_order, candidate_order, conn):
    """
    Check if candidate order is a roll/close continuation based on matching positions
    """
    cursor = conn.cursor()
    
    # Must be within reasonable time frame (30 days) and after previous order
    try:
        prev_date = datetime.fromisoformat(prev_order['order_date'])
        candidate_date = datetime.fromisoformat(candidate_order['order_date'])
        
        if candidate_date <= prev_date or (candidate_date - prev_date) > timedelta(days=30):
            return False
    except:
        return False
    
    # Must be same account and underlying
    if (prev_order['account_number'] != candidate_order['account_number'] or
        prev_order['underlying'] != candidate_order['underlying']):
        return False
    
    # Get open positions from previous order
    cursor.execute("""
        SELECT symbol, underlying, option_type, strike, expiration, quantity
        FROM positions_new 
        WHERE order_id = ? AND status = 'OPEN'
    """, (prev_order['order_id'],))
    
    prev_open_positions = cursor.fetchall()
    if not prev_open_positions:
        return False
    
    # Get closing transactions from candidate rolling order
    cursor.execute("""
        SELECT rt.symbol, rt.underlying_symbol, rt.quantity, rt.action
        FROM raw_transactions rt
        WHERE rt.order_id = ? 
        AND (rt.action LIKE '%BTC%' OR rt.action LIKE '%STC%' OR rt.action LIKE '%CLOSE%')
    """, (candidate_order['order_id'],))
    
    closing_transactions = cursor.fetchall()
    if not closing_transactions:
        return False
    
    # Convert closing transactions to position keys for matching
    closing_position_keys = set()
    for tx in closing_transactions:
        symbol = tx[0]
        instrument_type = 'EQUITY_OPTION' if symbol and len(symbol.split()) >= 2 else 'EQUITY'
        
        if instrument_type == 'EQUITY_OPTION':
            parts = symbol.split()
            if len(parts) >= 2:
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
                except (ValueError, IndexError):
                    continue
        else:
            # Stock position
            position_key = (symbol.strip(), None, None, None)
            closing_position_keys.add(position_key)
    
    # Convert previous open positions to same format for comparison
    prev_position_keys = set()
    for pos in prev_open_positions:
        symbol, underlying, option_type, strike, expiration = pos[:5]
        position_key = (symbol.strip(), option_type, strike, expiration)
        prev_position_keys.add(position_key)
    
    # Check if closing transactions match any previous open positions
    matches = closing_position_keys.intersection(prev_position_keys)
    
    return len(matches) > 0

def rebuild_order_chains():
    """Rebuild order chains with the updated logic"""
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    try:
        print("Rebuilding order chains with updated CLOSING order logic...")
        
        # Clear existing chains
        print("Clearing existing order chains...")
        cursor.execute("DELETE FROM order_chain_members")
        cursor.execute("DELETE FROM order_chains")
        cursor.execute("UPDATE orders SET linked_order_id = NULL")
        
        # Get all orders grouped by account
        cursor.execute("""
            SELECT * FROM orders
            ORDER BY account_number, order_date
        """)
        
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        
        # Group by account
        by_account = {}
        for row in rows:
            order = dict(zip(columns, row))
            account = order['account_number']
            
            if account not in by_account:
                by_account[account] = []
            
            by_account[account].append(order)
        
        # Detect chains
        chain_id_counter = 1
        
        for account, orders in by_account.items():
            processed_orders = set()
            
            for order in orders:
                if order['order_id'] in processed_orders:
                    continue
                
                # Exclude expired/assigned orders from chain linking
                is_system_closed = (order['has_expiration'] or order['has_assignment'] or order['has_exercise'])
                
                # Start a new chain
                chain_id = f"CHAIN_{account}_{order['underlying']}_{chain_id_counter:04d}"
                chain_id_counter += 1
                
                chain_members = [order]
                processed_orders.add(order['order_id'])
                
                # FIXED: Build chains by finding continuation orders (ROLLING or CLOSING)
                if not is_system_closed and order['order_type'] != 'CLOSING':
                    current_order = order
                    
                    # Continue building chain by finding orders that close current positions
                    while True:
                        found_continuation = False
                        
                        for candidate in orders:
                            if (candidate['order_id'] not in processed_orders and
                                candidate['order_type'] in ['ROLLING', 'CLOSING'] and
                                is_position_based_roll_continuation(current_order, candidate, conn)):
                                
                                chain_members.append(candidate)
                                processed_orders.add(candidate['order_id'])
                                
                                # Update linked_order_id
                                cursor.execute("""
                                    UPDATE orders SET linked_order_id = ?
                                    WHERE order_id = ?
                                """, (current_order['order_id'], candidate['order_id']))
                                
                                print(f"  Linked order {candidate['order_id']} to {current_order['order_id']}")
                                
                                # If this is a CLOSING order, stop building the chain
                                if candidate['order_type'] == 'CLOSING':
                                    found_continuation = False  # Don't continue after closing
                                else:
                                    current_order = candidate
                                    found_continuation = True
                                break
                        
                        if not found_continuation:
                            break
                
                # Create chain record
                if chain_members:
                    opening_order = chain_members[0]
                    
                    # Calculate chain P&L
                    chain_order_ids = [m['order_id'] for m in chain_members]
                    placeholders = ','.join('?' * len(chain_order_ids))
                    cursor.execute(f"""
                        SELECT SUM(pnl) FROM positions_new
                        WHERE order_id IN ({placeholders})
                    """, chain_order_ids)
                    
                    total_pnl = cursor.fetchone()[0] or 0
                    
                    # Determine chain status
                    if is_system_closed:
                        chain_status = 'CLOSED'
                    else:
                        last_order = chain_members[-1]
                        chain_status = 'CLOSED' if last_order['order_type'] == 'CLOSING' else 'OPEN'
                    
                    # Use strategy_type from opening order
                    strategy_type = opening_order.get('strategy_type') or 'UNKNOWN'
                    
                    # Insert chain
                    cursor.execute("""
                        INSERT INTO order_chains (
                            chain_id, underlying, account_number, opening_order_id,
                            strategy_type, chain_status, total_pnl
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        chain_id, opening_order['underlying'], account, opening_order['order_id'],
                        strategy_type, chain_status, total_pnl
                    ))
                    
                    # Insert chain members
                    for i, member in enumerate(chain_members):
                        cursor.execute("""
                            INSERT INTO order_chain_members (
                                chain_id, order_id, sequence_number
                            ) VALUES (?, ?, ?)
                        """, (chain_id, member['order_id'], i + 1))
                    
                    print(f"Created chain {chain_id} with {len(chain_members)} orders, status={chain_status}")
                    if len(chain_members) > 1:
                        member_ids = [m['order_id'] for m in chain_members]
                        print(f"  Orders: {' -> '.join(member_ids)}")
        
        conn.commit()
        print("\n✅ Order chains rebuilt successfully!")
        
        # Test our specific orders  
        print("\n=== TESTING SPECIFIC ORDERS ===")
        cursor.execute('''
            SELECT oc.chain_id, oc.strategy_type, oc.chain_status,
                   ocm.order_id, ocm.sequence_number 
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE ocm.order_id IN ("380086981", "380871211")
            ORDER BY oc.chain_id, ocm.sequence_number
        ''')
        
        test_results = cursor.fetchall()
        if test_results:
            current_chain = None
            for result in test_results:
                if result[0] != current_chain:
                    print(f'\nChain {result[0]} ({result[1]}, {result[2]}):')
                    current_chain = result[0]
                print(f'  Order {result[3]} (sequence {result[4]})')
            
            # Check if they're in the same chain
            chain_ids = set(result[0] for result in test_results)
            if len(chain_ids) == 1:
                print(f"\n🎉 SUCCESS: Orders 380086981 and 380871211 are now in the same chain!")
            else:
                print(f"\n❌ Orders are still in separate chains: {chain_ids}")
        else:
            print("❌ No chains found for test orders")
            
    except Exception as e:
        print(f"Error rebuilding chains: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    rebuild_order_chains()