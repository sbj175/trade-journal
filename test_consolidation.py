#!/usr/bin/env python3
"""Test script to verify position consolidation logic"""

import sys
import sqlite3
sys.path.append('.')

from src.models.order_models import OrderManager, Order, Position, OrderType, OrderStatus, PositionStatus
from src.database.db_manager import DatabaseManager
from datetime import datetime, date

def test_consolidation():
    """Test position consolidation with order 375557880"""
    print("Testing position consolidation...")
    
    db = DatabaseManager()
    
    # Get the order with multiple fills
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # Get order details
    cursor.execute("""
        SELECT * FROM orders WHERE order_id = '375557880'
    """)
    order_row = cursor.fetchone()
    
    if not order_row:
        print("Order 375557880 not found")
        return
    
    # Get positions for this order
    cursor.execute("""
        SELECT * FROM positions_new WHERE order_id = '375557880'
        ORDER BY symbol, quantity
    """)
    positions_data = cursor.fetchall()
    
    print(f"Found {len(positions_data)} individual positions")
    
    # Convert to dictionaries
    order_columns = [description[0] for description in cursor.description]
    positions_columns = [description[0] for description in cursor.description]
    
    cursor.execute("SELECT * FROM orders WHERE order_id = '375557880'")
    order_row = cursor.fetchone()
    order_columns = [description[0] for description in cursor.description]
    order_dict = dict(zip(order_columns, order_row))
    
    cursor.execute("SELECT * FROM positions_new WHERE order_id = '375557880'")
    positions_rows = cursor.fetchall()
    positions_columns = [description[0] for description in cursor.description]
    
    # Create Order object
    order_type = OrderType(order_dict['order_type'])
    order_status = OrderStatus(order_dict['status'])
    
    order_obj = Order(
        order_id=order_dict['order_id'],
        account_number=order_dict['account_number'],
        underlying=order_dict['underlying'],
        order_type=order_type,
        strategy_type=order_dict.get('strategy_type'),
        order_date=order_dict['order_date'],
        status=order_status,
        total_quantity=order_dict['total_quantity'],
        total_pnl=order_dict['total_pnl'],
        has_assignment=order_dict.get('has_assignment', False),
        has_expiration=order_dict.get('has_expiration', False),
        has_exercise=order_dict.get('has_exercise', False),
        linked_order_id=order_dict.get('linked_order_id'),
        positions=[]
    )
    
    # Convert positions to Position objects
    for pos_row in positions_rows:
        pos_dict = dict(zip(positions_columns, pos_row))
        position_status = PositionStatus(pos_dict['status'])
        position = Position(
            position_id=pos_dict['position_id'],
            order_id=pos_dict['order_id'],
            account_number=pos_dict['account_number'],
            symbol=pos_dict['symbol'],
            underlying=pos_dict['underlying'],
            instrument_type=pos_dict['instrument_type'],
            option_type=pos_dict.get('option_type'),
            strike=pos_dict.get('strike'),
            expiration=pos_dict.get('expiration'),
            quantity=pos_dict['quantity'],
            opening_price=pos_dict['opening_price'],
            closing_price=pos_dict.get('closing_price'),
            opening_transaction_id=pos_dict['opening_transaction_id'],
            closing_transaction_id=pos_dict.get('closing_transaction_id'),
            opening_action=pos_dict['opening_action'],
            closing_action=pos_dict.get('closing_action'),
            status=position_status,
            pnl=pos_dict['pnl'],
            fill_count=pos_dict.get('fill_count', 1),
            created_at=pos_dict.get('created_at'),
            updated_at=pos_dict.get('updated_at')
        )
        order_obj.positions.append(position)
    
    print(f"Original positions: {len(order_obj.positions)}")
    
    # Test consolidation
    consolidated_positions = order_obj.consolidate_positions()
    
    print(f"Consolidated positions: {len(consolidated_positions)}")
    print()
    
    # Show consolidated results
    for i, pos in enumerate(consolidated_positions):
        print(f"Position {i+1}:")
        print(f"  Symbol: {pos.symbol}")
        print(f"  Quantity: {pos.quantity}")
        print(f"  Opening Action: {pos.opening_action}")
        print(f"  Opening Price: ${pos.opening_price}")
        print(f"  P&L: ${pos.pnl}")
        print(f"  Fill Count: {pos.fill_count}")
        print()
    
    # Test with a multi-leg strategy (if available)
    test_multileg_strategy(cursor)
    
    conn.close()

def test_multileg_strategy(cursor):
    """Test consolidation with a multi-leg strategy to ensure legs stay separate"""
    print("\nTesting multi-leg strategy consolidation...")
    
    # Find an order with multiple different symbols (multi-leg)
    cursor.execute("""
        SELECT order_id, COUNT(DISTINCT symbol) as symbol_count
        FROM positions_new
        GROUP BY order_id
        HAVING symbol_count > 1
        ORDER BY symbol_count DESC
        LIMIT 1
    """)
    
    result = cursor.fetchone()
    if not result:
        print("No multi-leg strategies found")
        return
    
    order_id, symbol_count = result
    print(f"Testing order {order_id} with {symbol_count} different symbols")
    
    # Get positions for this order
    cursor.execute("""
        SELECT * FROM positions_new WHERE order_id = ?
        ORDER BY symbol
    """, (order_id,))
    
    positions_rows = cursor.fetchall()
    positions_columns = [description[0] for description in cursor.description]
    
    # Create simplified Order object for testing
    order_obj = Order(
        order_id=order_id,
        account_number="test",
        underlying="TEST",
        order_type=OrderType.OPENING,
        positions=[]
    )
    
    # Convert positions
    for pos_row in positions_rows:
        pos_dict = dict(zip(positions_columns, pos_row))
        position = Position(
            position_id=pos_dict['position_id'],
            order_id=pos_dict['order_id'],
            account_number=pos_dict['account_number'],
            symbol=pos_dict['symbol'],
            underlying=pos_dict['underlying'],
            instrument_type=pos_dict['instrument_type'],
            option_type=pos_dict.get('option_type'),
            strike=pos_dict.get('strike'),
            expiration=pos_dict.get('expiration'),
            quantity=pos_dict['quantity'],
            opening_price=pos_dict['opening_price'],
            closing_price=pos_dict.get('closing_price'),
            opening_transaction_id=pos_dict['opening_transaction_id'],
            closing_transaction_id=pos_dict.get('closing_transaction_id'),
            opening_action=pos_dict['opening_action'],
            closing_action=pos_dict.get('closing_action'),
            status=PositionStatus.CLOSED,
            pnl=pos_dict['pnl'],
            fill_count=1
        )
        order_obj.positions.append(position)
    
    print(f"Original positions: {len(order_obj.positions)}")
    
    # Show original positions by symbol
    from collections import defaultdict
    symbol_groups = defaultdict(list)
    for pos in order_obj.positions:
        symbol_groups[pos.symbol].append(pos)
    
    print("Original position breakdown:")
    for symbol, positions in symbol_groups.items():
        print(f"  {symbol}: {len(positions)} positions")
    
    # Test consolidation
    consolidated_positions = order_obj.consolidate_positions()
    
    print(f"Consolidated positions: {len(consolidated_positions)}")
    
    # Show consolidated results
    consolidated_symbols = defaultdict(list)
    for pos in consolidated_positions:
        consolidated_symbols[pos.symbol].append(pos)
    
    print("Consolidated position breakdown:")
    for symbol, positions in consolidated_symbols.items():
        print(f"  {symbol}: {len(positions)} positions")
        for pos in positions:
            print(f"    Qty: {pos.quantity}, Action: {pos.opening_action}, Price: ${pos.opening_price}, Fills: {pos.fill_count}")

if __name__ == "__main__":
    test_consolidation()