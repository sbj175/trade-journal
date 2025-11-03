#!/usr/bin/env python3
"""
Test the V2 system's handling of expiration transactions
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.models.position_inventory import PositionInventoryManager
from src.models.order_processor_v2 import OrderProcessorV2
from src.models.pnl_calculator_v2 import PnLCalculatorV2


def test_expiration_handling():
    """Test that expirations correctly close chains"""
    print("🧪 Testing V2 Expiration Handling")
    print("=" * 60)
    
    db_manager = DatabaseManager()
    position_manager = PositionInventoryManager(db_manager)
    order_processor = OrderProcessorV2(db_manager, position_manager)
    pnl_calculator = PnLCalculatorV2(db_manager, position_manager)
    
    # Get IBIT transactions that include expirations
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find IBIT positions that expired
        cursor.execute("""
            SELECT DISTINCT symbol
            FROM raw_transactions
            WHERE underlying_symbol = 'IBIT'
            AND transaction_sub_type = 'Expiration'
            LIMIT 5
        """)
        
        expired_symbols = [row[0] for row in cursor.fetchall()]
        
        print(f"Testing with {len(expired_symbols)} expired IBIT options:")
        for symbol in expired_symbols:
            print(f"  - {symbol}")
        
        # For each expired symbol, get all related transactions
        for symbol in expired_symbols:
            print(f"\n{'='*60}")
            print(f"Testing {symbol}:")
            print('-' * 40)
            
            # Get all transactions for this symbol
            cursor.execute("""
                SELECT * FROM raw_transactions
                WHERE symbol = ?
                ORDER BY executed_at
            """, (symbol,))
            
            columns = [description[0] for description in cursor.description]
            transactions = []
            for row in cursor.fetchall():
                tx_dict = dict(zip(columns, row))
                transactions.append(tx_dict)
            
            print(f"Found {len(transactions)} transactions:")
            for tx in transactions:
                print(f"  {tx['executed_at']}: {tx['action']} {tx['quantity']} @ ${tx.get('price', 0)}")
                if tx.get('transaction_sub_type') == 'Expiration':
                    print(f"    ⏰ EXPIRATION")
            
            # Clear positions for clean test
            position_manager.clear_all_positions()
            
            # Process through new system
            chains_by_account = order_processor.process_transactions(transactions)
            
            # Check results
            total_chains = sum(len(chains) for chains in chains_by_account.values())
            print(f"\nResults:")
            print(f"  Chains created: {total_chains}")
            
            for account, chains in chains_by_account.items():
                for chain in chains:
                    print(f"  Chain {chain.chain_id}:")
                    print(f"    Status: {chain.status}")
                    print(f"    Orders: {len(chain.orders)}")
                    
                    # Check final position
                    position = position_manager.get_position(account, symbol)
                    if position:
                        print(f"    Final position: {position.current_quantity}")
                        if position.is_closed:
                            print(f"    ✅ Position correctly closed")
                        else:
                            print(f"    ❌ Position still open!")
                    
                    if chain.status == "CLOSED":
                        print(f"    ✅ Chain correctly marked CLOSED")
                    else:
                        print(f"    ❌ Chain incorrectly marked OPEN")
    
    # Test the specific problematic chain
    print(f"\n{'='*60}")
    print("Testing specific problematic chain IBIT_OPENING_20250630_39244084:")
    print('-' * 40)
    
    test_problematic_ibit_chain(db_manager, position_manager, order_processor)


def test_problematic_ibit_chain(db_manager, position_manager, order_processor):
    """Test the specific IBIT chain that had issues"""
    
    # Get transactions for IBIT 250703C00063000
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM raw_transactions
            WHERE symbol = 'IBIT  250703C00063000'
            AND account_number IN ('5WZ28644', '5WZ26959')
            ORDER BY executed_at
        """)
        
        columns = [description[0] for description in cursor.description]
        transactions = []
        for row in cursor.fetchall():
            tx_dict = dict(zip(columns, row))
            transactions.append(tx_dict)
    
    print(f"Found {len(transactions)} transactions for IBIT 250703C00063000")
    
    # Process each account separately
    accounts = set(tx['account_number'] for tx in transactions)
    
    for account in accounts:
        print(f"\nAccount {account}:")
        account_txs = [tx for tx in transactions if tx['account_number'] == account]
        
        # Clear positions for clean test
        position_manager.clear_all_positions()
        
        # Process
        chains_by_account = order_processor.process_transactions(account_txs)
        
        if account in chains_by_account:
            chains = chains_by_account[account]
            print(f"  Created {len(chains)} chain(s)")
            
            for chain in chains:
                print(f"  Chain: {chain.chain_id}")
                print(f"    Status: {chain.status}")
                
                # Show orders
                for order in chain.orders:
                    print(f"    Order {order.order_id} ({order.order_type.value}):")
                    for tx in order.transactions:
                        action_str = f"{tx.action} {tx.quantity}"
                        if tx.is_expiration:
                            action_str += " [EXPIRATION]"
                        print(f"      {action_str}")
                
                # Check position
                position = position_manager.get_position(account, 'IBIT  250703C00063000')
                if position:
                    print(f"    Final position quantity: {position.current_quantity}")
                
                # Verify
                if chain.status == "CLOSED" and (not position or position.is_closed):
                    print(f"    ✅ Chain and position correctly handled!")
                else:
                    print(f"    ❌ Issue detected - chain status: {chain.status}, "
                          f"position qty: {position.current_quantity if position else 'None'}")


if __name__ == "__main__":
    test_expiration_handling()