#!/usr/bin/env python3
"""
Fix all chains that should be closed due to expiration
"""

import sqlite3
from datetime import datetime

def fix_all_expired_chains():
    """Find and fix all chains that should be closed due to expiration"""
    
    print('🔧 Fixing All Expired Chains')
    print('=' * 50)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Find all chains that have expiration orders
    cursor.execute('''
        SELECT DISTINCT ocm.chain_id, oc.chain_status
        FROM order_chain_members ocm
        JOIN order_chains oc ON ocm.chain_id = oc.chain_id
        JOIN orders o ON ocm.order_id = o.order_id
        WHERE o.order_id LIKE 'SYSTEM_EXPIRATION_%'
        ORDER BY ocm.chain_id
    ''')
    
    chains_with_expiration = cursor.fetchall()
    print(f'Found {len(chains_with_expiration)} chains with expiration orders')
    
    fixed_chains = []
    
    for chain_id, current_status in chains_with_expiration:
        print(f'\n🔍 Checking chain: {chain_id} (currently {current_status})')
        
        # Get all positions in this chain
        cursor.execute('''
            SELECT p.symbol, p.quantity, p.opening_action, p.closing_action, 
                   p.strike, p.expiration, p.order_id, o.order_date, o.order_type
            FROM positions_new p
            JOIN order_chain_members ocm ON p.order_id = ocm.order_id
            JOIN orders o ON p.order_id = o.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date, p.order_id
        ''', (chain_id,))
        
        positions = cursor.fetchall()
        
        # Calculate position balances
        position_balances = {}
        latest_order_date = None
        
        for pos in positions:
            symbol, qty, open_action, close_action, strike, exp, order_id, order_date, order_type = pos
            
            # Track latest order date
            if order_date:
                if isinstance(order_date, str):
                    try:
                        order_date = datetime.strptime(order_date, '%Y-%m-%d').date()
                    except:
                        pass
                if latest_order_date is None or order_date > latest_order_date:
                    latest_order_date = order_date
            
            # Create position key
            if strike is not None and exp is not None:
                pos_key = f"{symbol}_{strike}_{exp}"
            else:
                pos_key = symbol
            
            if pos_key not in position_balances:
                position_balances[pos_key] = 0
            
            quantity = abs(qty)
            
            # Apply opening action
            if open_action:
                if 'SELL_TO_OPEN' in open_action:
                    position_balances[pos_key] += quantity
                elif 'BUY_TO_OPEN' in open_action:
                    position_balances[pos_key] -= quantity
                elif 'BUY_TO_CLOSE' in open_action:
                    position_balances[pos_key] -= quantity
                elif 'SELL_TO_CLOSE' in open_action:
                    position_balances[pos_key] += quantity
            
            # Apply closing action
            if close_action and 'EXPIRED' in close_action:
                current_balance = position_balances[pos_key]
                if current_balance > 0:
                    position_balances[pos_key] -= quantity
                elif current_balance < 0:
                    position_balances[pos_key] += quantity
        
        # Determine if chain should be closed
        has_open_positions = any(abs(balance) > 1e-6 for balance in position_balances.values())
        should_be_closed = not has_open_positions
        correct_status = 'CLOSED' if should_be_closed else 'OPEN'
        
        print(f'  Position balances: {position_balances}')
        print(f'  Should be: {correct_status}')
        
        if correct_status != current_status:
            print(f'  ⚠️  Fixing: {current_status} → {correct_status}')
            
            # Update the chain status
            closing_date = latest_order_date if should_be_closed else None
            cursor.execute('''
                UPDATE order_chains 
                SET chain_status = ?, closing_date = ?
                WHERE chain_id = ?
            ''', (correct_status, closing_date, chain_id))
            
            fixed_chains.append(chain_id)
        else:
            print(f'  ✅ Correct status')
    
    # Commit all changes
    conn.commit()
    
    print(f'\n🎉 Summary:')
    print(f'  Checked: {len(chains_with_expiration)} chains')
    print(f'  Fixed: {len(fixed_chains)} chains')
    
    if fixed_chains:
        print(f'  Fixed chains:')
        for chain_id in fixed_chains:
            print(f'    - {chain_id}')
    
    conn.close()

if __name__ == "__main__":
    fix_all_expired_chains()