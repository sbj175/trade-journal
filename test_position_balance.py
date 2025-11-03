#!/usr/bin/env python3
"""
Test the actual is_chain_fully_closed method to see what's going wrong
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.db_manager import DatabaseManager
from models.order_models import OrderManager
import sqlite3

def test_is_chain_fully_closed():
    """Test the actual is_chain_fully_closed method"""
    
    print('🔍 Testing is_chain_fully_closed() Method')
    print('=' * 60)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Try to import the classes without dependencies
    try:
        chain_id = 'IBIT_OPENING_20250505_38216688'
        
        # Get all orders in this chain
        cursor.execute('''
            SELECT DISTINCT o.order_id
            FROM orders o
            JOIN order_chain_members ocm ON o.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date
        ''', (chain_id,))
        
        order_ids = [row[0] for row in cursor.fetchall()]
        
        print(f'Orders in chain {chain_id}:')
        for order_id in order_ids:
            print(f'  - {order_id}')
        
        # Manually simulate the position balance calculation that should happen
        print(f'\nManual Position Balance Calculation:')
        
        position_balances = {}
        
        for order_id in order_ids:
            cursor.execute('''
                SELECT symbol, quantity, opening_action, closing_action, strike, expiration
                FROM positions_new 
                WHERE order_id = ?
            ''', (order_id,))
            
            positions = cursor.fetchall()
            
            print(f'\n  Order {order_id}:')
            for pos in positions:
                symbol, qty, open_action, close_action, strike, exp = pos
                
                # Create position key like the fixed method should
                if strike is not None and exp is not None:
                    pos_key = f"{symbol}_{strike}_{exp}"
                else:
                    pos_key = symbol
                
                print(f'    Position: {pos_key}')
                print(f'      Actions: {open_action} | {close_action or "None"}')
                print(f'      Quantity: {qty}')
                
                if pos_key not in position_balances:
                    position_balances[pos_key] = 0
                
                quantity = abs(qty)
                
                # Apply opening action
                if open_action:
                    if 'SELL_TO_OPEN' in open_action:
                        position_balances[pos_key] += quantity
                        print(f'      → STO: {pos_key} += {quantity} = {position_balances[pos_key]}')
                    elif 'BUY_TO_OPEN' in open_action:
                        position_balances[pos_key] -= quantity
                        print(f'      → BTO: {pos_key} -= {quantity} = {position_balances[pos_key]}')
                    elif 'BUY_TO_CLOSE' in open_action:
                        position_balances[pos_key] -= quantity
                        print(f'      → BTC: {pos_key} -= {quantity} = {position_balances[pos_key]}')
                    elif 'SELL_TO_CLOSE' in open_action:
                        position_balances[pos_key] += quantity
                        print(f'      → STC: {pos_key} += {quantity} = {position_balances[pos_key]}')
                
                # Apply closing action
                if close_action and 'EXPIRED' in close_action:
                    current_balance = position_balances[pos_key]
                    if current_balance > 0:
                        position_balances[pos_key] -= quantity
                        print(f'      → EXPIRED (short): {pos_key} -= {quantity} = {position_balances[pos_key]}')
                    elif current_balance < 0:
                        position_balances[pos_key] += quantity
                        print(f'      → EXPIRED (long): {pos_key} += {quantity} = {position_balances[pos_key]}')
        
        print(f'\nFinal Position Balances:')
        has_open_positions = False
        for pos_key, balance in position_balances.items():
            is_open = abs(balance) > 1e-6
            if is_open:
                has_open_positions = True
            status = 'OPEN' if is_open else 'CLOSED'
            print(f'  {pos_key}: {balance} ({status})')
        
        chain_should_be_closed = not has_open_positions
        print(f'\nChain should be closed: {chain_should_be_closed}')
        
        # Check actual chain status
        cursor.execute('SELECT chain_status FROM order_chains WHERE chain_id = ?', (chain_id,))
        actual_status = cursor.fetchone()[0]
        print(f'Actual chain status: {actual_status}')
        
        if chain_should_be_closed != (actual_status == 'CLOSED'):
            print(f'❌ MISMATCH: Method should return {chain_should_be_closed} but chain is {actual_status}')
        else:
            print(f'✅ Status matches calculation')
            
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
    
    conn.close()

if __name__ == "__main__":
    test_is_chain_fully_closed()