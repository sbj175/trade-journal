#!/usr/bin/env python3
"""
Fix the core chain detection logic and rebuild chains
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

def is_position_based_roll_continuation(prev_order, candidate_order, conn):
    """
    Check if candidate order is a roll continuation based on matching positions
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

def rebuild_order_chains_fixed(conn):
    """Rebuild order chains with FIXED logic"""
    cursor = conn.cursor()
    
    print("Rebuilding order chains with fixed logic...")
    
    # Clear existing chains
    cursor.execute("DELETE FROM order_chain_members")
    cursor.execute("DELETE FROM order_chains")
    
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
            
            # FIXED: Only exclude system-closed orders from starting chains
            # But allow them to be continuations if they match positions
            is_system_closed = (order['has_expiration'] or order['has_assignment'] or order['has_exercise'])
            
            # Start a new chain
            chain_id = f"CHAIN_{account}_{order['underlying']}_{chain_id_counter:04d}"
            chain_id_counter += 1
            
            chain_members = [order]
            processed_orders.add(order['order_id'])
            
            # FIXED: Build chains by finding continuation orders (ROLLING or CLOSING)
            # Removed exclusion of orders with expiration/assignment flags
            if not is_system_closed and order['order_type'] != 'CLOSING':
                current_order = order
                
                # Continue building chain by finding rolling orders that close current positions
                while True:
                    found_continuation = False
                    
                    for candidate in orders:
                        # FIXED: Removed the exclusion of has_expiration/assignment/exercise
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
                cursor.execute("""
                    SELECT SUM(pnl) FROM positions_new
                    WHERE order_id IN ({})
                """.format(','.join('?' * len(chain_members))), 
                [m['order_id'] for m in chain_members])
                
                total_pnl = cursor.fetchone()[0] or 0
                
                # Determine chain status
                has_closing = any(m['order_type'] == 'CLOSING' for m in chain_members)
                chain_status = 'CLOSED' if has_closing else 'OPEN'
                
                # Insert chain
                cursor.execute("""
                    INSERT INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id,
                        strategy_type, chain_status, total_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain_id, opening_order['underlying'], account,
                    opening_order['order_id'], opening_order['strategy_type'],
                    chain_status, total_pnl
                ))
                
                # Insert chain members
                for i, member in enumerate(chain_members):
                    cursor.execute("""
                        INSERT INTO order_chain_members (
                            chain_id, order_id, sequence_number
                        ) VALUES (?, ?, ?)
                    """, (chain_id, member['order_id'], i + 1))
                
                print(f"Created chain {chain_id} with {len(chain_members)} orders, status={chain_status}")

def main():
    """Fix chain detection logic and rebuild"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        print("ERROR: Database not found")
        return
    
    print("FIXING CORE CHAIN DETECTION LOGIC")
    print("Issue: Orders with expiration flags were excluded from chain continuations")
    print("Fix: Allow orders with expiration flags to be valid roll continuations")
    print("")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        rebuild_order_chains_fixed(conn)
        conn.commit()
        
        # Check specific fix
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o1.order_id as order1, o2.order_id as order2, oc.chain_id,
                   ocm1.sequence_number as seq1, ocm2.sequence_number as seq2
            FROM order_chain_members ocm1
            JOIN order_chain_members ocm2 ON ocm1.chain_id = ocm2.chain_id
            JOIN orders o1 ON ocm1.order_id = o1.order_id
            JOIN orders o2 ON ocm2.order_id = o2.order_id
            JOIN order_chains oc ON ocm1.chain_id = oc.chain_id
            WHERE (o1.order_id = '380086981' AND o2.order_id = '380871211')
               OR (o1.order_id = '380871211' AND o2.order_id = '380086981')
        """)
        
        linked = cursor.fetchone()
        if linked:
            print(f"✅ SUCCESS: Orders 380086981 and 380871211 are now linked in {linked['chain_id']}")
            print(f"   Sequence: {linked['order1']} (seq {linked['seq1']}) → {linked['order2']} (seq {linked['seq2']})")
        else:
            print(f"❌ Orders 380086981 and 380871211 are still not linked")
            
        print("\nCore logic fix complete!")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()