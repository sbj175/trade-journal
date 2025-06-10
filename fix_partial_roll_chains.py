#!/usr/bin/env python3
"""
Fix chain detection to handle multiple partial rolling orders
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

def is_position_based_roll_continuation(prev_order, candidate_order, conn):
    """Check if candidate order is a roll continuation based on matching positions"""
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

def rebuild_chains_with_partial_roll_support(conn):
    """Rebuild chains with support for multiple partial rolling orders"""
    cursor = conn.cursor()
    
    print("Rebuilding chains with PARTIAL ROLL support...")
    
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
            
            # Only exclude system-closed orders from starting chains
            is_system_closed = (order['has_expiration'] or order['has_assignment'] or order['has_exercise'])
            
            # Start a new chain
            chain_id = f"CHAIN_{account}_{order['underlying']}_{chain_id_counter:04d}"
            chain_id_counter += 1
            
            chain_members = [order]
            processed_orders.add(order['order_id'])
            
            # Build chains by finding continuation orders
            if not is_system_closed and order['order_type'] != 'CLOSING':
                current_order = order
                
                # Continue building chain
                while True:
                    # FIXED: Find ALL continuations from current order, not just the first one
                    continuations_found = []
                    
                    for candidate in orders:
                        if (candidate['order_id'] not in processed_orders and
                            candidate['order_type'] in ['ROLLING', 'CLOSING'] and
                            is_position_based_roll_continuation(current_order, candidate, conn)):
                            
                            continuations_found.append(candidate)
                    
                    if not continuations_found:
                        break
                    
                    # Sort continuations by date to maintain chronological order
                    continuations_found.sort(key=lambda x: x['order_date'])
                    
                    # Add all continuations to the chain
                    for continuation in continuations_found:
                        chain_members.append(continuation)
                        processed_orders.add(continuation['order_id'])
                        
                        # Update linked_order_id
                        cursor.execute("""
                            UPDATE orders SET linked_order_id = ?
                            WHERE order_id = ?
                        """, (current_order['order_id'], continuation['order_id']))
                        
                        print(f"  Added {continuation['order_id']} as continuation of {current_order['order_id']}")
                    
                    # If any continuations are CLOSING orders, stop building the chain
                    has_closing = any(c['order_type'] == 'CLOSING' for c in continuations_found)
                    if has_closing:
                        break
                    
                    # Continue from the last (most recent) continuation for further chain building
                    current_order = continuations_found[-1]
            
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
                if len(chain_members) > 1:
                    order_list = [f"{m['order_id']} ({m['order_type']})" for m in chain_members]
                    print(f"  Sequence: {' → '.join(order_list)}")

def main():
    """Fix partial roll chain detection"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        print("ERROR: Database not found")
        return
    
    print("FIXING PARTIAL ROLL CHAIN DETECTION")
    print("Issue: Only first partial roll was linked, subsequent partial rolls were orphaned")
    print("Fix: Find ALL continuations from each order, not just the first one")
    print("")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        rebuild_chains_with_partial_roll_support(conn)
        conn.commit()
        
        # Check the specific partial roll case
        cursor = conn.cursor()
        cursor.execute("""
            SELECT oc.chain_id, 
                   GROUP_CONCAT(ocm.order_id || ' (seq:' || ocm.sequence_number || ')' ORDER BY ocm.sequence_number) as sequence
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE oc.chain_id IN (
                SELECT DISTINCT ocm2.chain_id 
                FROM order_chain_members ocm2 
                WHERE ocm2.order_id IN ('384591905', '385368404', '385369891')
            )
            GROUP BY oc.chain_id
        """)
        
        result = cursor.fetchone()
        if result:
            print(f"\n✅ SUCCESS: Partial roll orders are linked in {result['chain_id']}")
            print(f"   Sequence: {result['sequence']}")
        else:
            print(f"\n❌ Partial roll orders are still not properly linked")
            
        print("\nPartial roll fix complete!")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()