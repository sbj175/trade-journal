#!/usr/bin/env python3
"""
Test the system's handling of expiration transactions
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.models.order_processor import OrderProcessor
from src.models.lot_manager import LotManager


def test_expiration_handling():
    """Test that expirations correctly close chains"""
    print("Testing Expiration Handling")
    print("=" * 60)

    db_manager = DatabaseManager()
    lot_manager = LotManager(db_manager)
    order_processor = OrderProcessor(db_manager, lot_manager)

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
                    print(f"    EXPIRATION")

            # Process through new system
            order_processor.process_transactions(transactions)

            print(f"\nResults: processed transactions for {symbol}")

    # Test the specific problematic chain
    print(f"\n{'='*60}")
    print("Testing specific problematic chain IBIT_OPENING_20250630_39244084:")
    print('-' * 40)

    test_problematic_ibit_chain(db_manager, order_processor)


def test_problematic_ibit_chain(db_manager, order_processor):
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

        # Process
        order_processor.process_transactions(account_txs)
        print(f"  Processed {len(account_txs)} transactions")


if __name__ == "__main__":
    test_expiration_handling()
