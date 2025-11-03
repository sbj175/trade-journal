#!/usr/bin/env python3
"""
Test the chain creation logic directly
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.db_manager import DatabaseManager
from models.order_models import OrderManager
import sqlite3

def test_chain_creation():
    """Test the chain creation logic directly for the problematic IBIT chain"""
    
    print('🔍 Testing Chain Creation Logic')
    print('=' * 50)
    
    db_path = '/home/sbj/python-projects/trade-journal/trade_journal.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get the orders for the problematic chain
        chain_id = 'IBIT_OPENING_20250630_39244084'
        
        cursor.execute('''
            SELECT DISTINCT o.order_id
            FROM orders o
            JOIN order_chain_members ocm ON o.order_id = ocm.order_id
            WHERE ocm.chain_id = ?
            ORDER BY o.order_date
        ''', (chain_id,))
        
        order_ids = [row[0] for row in cursor.fetchall()]
        print(f'Order IDs in chain: {order_ids}')
        
        # Get the order data
        orders_data = []
        for order_id in order_ids:
            cursor.execute('''
                SELECT order_id, account_number, underlying, order_type, order_date, 
                       strategy_type, status, total_pnl, created_at, updated_at
                FROM orders 
                WHERE order_id = ?
            ''', (order_id,))
            order_row = cursor.fetchone()
            if order_row:
                orders_data.append(order_row)
        
        print(f'Found {len(orders_data)} orders')
        
        # Create an OrderManager instance to test the logic
        db_manager = DatabaseManager()
        order_manager = OrderManager(db_manager)
        
        # Build order objects (simplified)
        from models.order_models import Order, OrderType
        from datetime import datetime, date
        
        orders = []
        for order_data in orders_data:
            order_id, account, underlying, order_type, order_date, strategy_type, status, total_pnl, created_at, updated_at = order_data
            
            # Convert strings to enums
            if order_type == 'OPENING':
                order_type_enum = OrderType.OPENING
            elif order_type == 'CLOSING':
                order_type_enum = OrderType.CLOSING
            elif order_type == 'ROLLING':
                order_type_enum = OrderType.ROLLING
            else:
                order_type_enum = OrderType.OPENING
            
            # Convert date string to date object
            if isinstance(order_date, str):
                order_date = datetime.strptime(order_date, '%Y-%m-%d').date()
            
            order = Order(
                order_id=order_id,
                account_number=account,
                underlying=underlying,
                order_type=order_type_enum,
                order_date=order_date,
                strategy_type=strategy_type,
                status=status,
                total_pnl=total_pnl or 0.0,
                positions=[]  # We'll add positions separately
            )
            orders.append(order)
        
        # Load positions for each order
        for order in orders:
            cursor.execute('''
                SELECT position_id, symbol, underlying, instrument_type, option_type,
                       strike, expiration, quantity, opening_price, closing_price,
                       opening_action, closing_action, status, pnl
                FROM positions_new 
                WHERE order_id = ?
            ''', (order.order_id,))
            
            position_rows = cursor.fetchall()
            for pos_row in position_rows:
                from models.order_models import Position, PositionStatus
                
                pos_id, symbol, underlying, instrument_type, option_type, strike, expiration, quantity, opening_price, closing_price, opening_action, closing_action, status, pnl = pos_row
                
                if status == 'OPEN':
                    status_enum = PositionStatus.OPEN
                else:
                    status_enum = PositionStatus.CLOSED
                
                position = Position(
                    position_id=pos_id,
                    order_id=order.order_id,
                    account_number=order.account_number,
                    symbol=symbol,
                    underlying=underlying,
                    instrument_type=instrument_type,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiration,
                    quantity=quantity,
                    opening_price=opening_price,
                    closing_price=closing_price,
                    opening_action=opening_action,
                    closing_action=closing_action,
                    status=status_enum,
                    pnl=pnl or 0.0
                )
                order.positions.append(position)
        
        print(f'\nTesting is_chain_fully_closed() method:')
        is_closed = order_manager.is_chain_fully_closed(orders)
        print(f'is_chain_fully_closed() returned: {is_closed}')
        
        # Test the position balance calculation directly
        print(f'\nTesting position balance calculation:')
        position_balances = order_manager.calculate_chain_position_balance(orders)
        print(f'Position balances: {position_balances}')
        
        has_open_positions = any(abs(balance) > 1e-6 for balance in position_balances.values())
        print(f'Has open positions: {has_open_positions}')
        print(f'Should be closed: {not has_open_positions}')
        
        # Test creating a new chain
        print(f'\nTesting create_order_chain_from_orders():')
        new_chain = order_manager.create_order_chain_from_orders(orders)
        if new_chain:
            print(f'New chain status would be: {new_chain.get("chain_status")}')
            print(f'New chain closing date: {new_chain.get("closing_date")}')
        else:
            print('Failed to create new chain')
            
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
    
    conn.close()

if __name__ == "__main__":
    test_chain_creation()