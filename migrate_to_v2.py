#!/usr/bin/env python3
"""
Migration script to transition from old chain system to new position-based system
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.models.position_inventory import PositionInventoryManager
from src.models.order_processor import OrderProcessor
from src.models.pnl_calculator import PnLCalculator
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_to_v2_system():
    """Main migration function"""
    logger.info("Starting migration to V2 order processing system...")
    
    # Initialize managers
    db_manager = DatabaseManager()
    position_manager = PositionInventoryManager(db_manager)
    pnl_calculator = PnLCalculator(db_manager, position_manager)
    order_processor = OrderProcessor(db_manager, position_manager)
    
    try:
        # Step 1: Clear existing position data (if any)
        logger.info("Step 1: Clearing existing position data...")
        position_manager.clear_all_positions()
        
        # Step 2: Load all raw transactions
        logger.info("Step 2: Loading raw transactions...")
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM raw_transactions
                WHERE symbol IS NOT NULL
                ORDER BY executed_at ASC
            """)
            
            columns = [description[0] for description in cursor.description]
            raw_transactions = []
            for row in cursor.fetchall():
                tx_dict = dict(zip(columns, row))
                raw_transactions.append(tx_dict)
        
        logger.info(f"Loaded {len(raw_transactions)} transactions")
        
        # Step 3: Rebuild position lots for P&L tracking
        logger.info("Step 3: Rebuilding position lots...")
        pnl_calculator.rebuild_lots_from_transactions()
        
        # Step 4: Process all transactions through new system
        logger.info("Step 4: Processing transactions through new system...")
        chains_by_account = order_processor.process_transactions(raw_transactions)
        
        # Step 5: Display results
        logger.info("Step 5: Migration results...")
        total_chains = 0
        for account, chains in chains_by_account.items():
            logger.info(f"\nAccount {account}:")
            logger.info(f"  Total chains: {len(chains)}")
            logger.info(f"  Open chains: {sum(1 for c in chains if c.status == 'OPEN')}")
            logger.info(f"  Closed chains: {sum(1 for c in chains if c.status == 'CLOSED')}")
            total_chains += len(chains)
        
        # Step 6: Verify position inventory
        logger.info("\nStep 6: Verifying position inventory...")
        all_positions = position_manager.get_open_positions()
        logger.info(f"Total open positions: {len(all_positions)}")
        
        # Show sample positions
        for i, position in enumerate(all_positions[:5]):
            logger.info(f"  {position.symbol}: {position.current_quantity} @ ${position.cost_basis:.2f}")
            if i >= 4:
                logger.info(f"  ... and {len(all_positions) - 5} more")
                break
        
        # Step 7: Compare with old system
        logger.info("\nStep 7: Comparing with old system...")
        compare_with_old_system(db_manager, chains_by_account)
        
        logger.info("\n✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def compare_with_old_system(db_manager, new_chains_by_account):
    """Compare results with the old system"""
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get old chain counts
        cursor.execute("""
            SELECT 
                COUNT(*) as total_chains,
                SUM(CASE WHEN chain_status = 'OPEN' THEN 1 ELSE 0 END) as open_chains,
                SUM(CASE WHEN chain_status = 'CLOSED' THEN 1 ELSE 0 END) as closed_chains
            FROM order_chains
        """)
        
        old_stats = cursor.fetchone()
        
        # Calculate new stats
        new_total = sum(len(chains) for chains in new_chains_by_account.values())
        new_open = sum(sum(1 for c in chains if c.status == 'OPEN') 
                      for chains in new_chains_by_account.values())
        new_closed = sum(sum(1 for c in chains if c.status == 'CLOSED') 
                        for chains in new_chains_by_account.values())
        
        logger.info("Comparison with old system:")
        logger.info(f"  Old system: {old_stats[0]} total, {old_stats[1]} open, {old_stats[2]} closed")
        logger.info(f"  New system: {new_total} total, {new_open} open, {new_closed} closed")
        
        # Check specific problem chains
        logger.info("\nChecking previously problematic IBIT chains...")
        
        # Find IBIT chains with expirations in new system
        ibit_expiration_chains = []
        for account, chains in new_chains_by_account.items():
            for chain in chains:
                if chain.underlying == 'IBIT':
                    # Check if any order has expiration
                    has_expiration = any(
                        any(tx.is_expiration for tx in order.transactions)
                        for order in chain.orders
                    )
                    if has_expiration:
                        ibit_expiration_chains.append(chain)
        
        logger.info(f"Found {len(ibit_expiration_chains)} IBIT chains with expirations")
        
        # Check their status
        correct_status = sum(1 for c in ibit_expiration_chains if c.status == 'CLOSED')
        logger.info(f"  {correct_status} are correctly marked as CLOSED")
        
        # Show any that are still open
        still_open = [c for c in ibit_expiration_chains if c.status == 'OPEN']
        if still_open:
            logger.warning(f"  {len(still_open)} are still marked as OPEN:")
            for chain in still_open[:3]:
                logger.warning(f"    - {chain.chain_id}")


def test_specific_chain(chain_id='IBIT_OPENING_20250630_39244084'):
    """Test a specific chain that had issues before"""
    logger.info(f"\nTesting specific chain: {chain_id}")
    
    db_manager = DatabaseManager()
    position_manager = PositionInventoryManager(db_manager)
    
    # Get transactions for this chain
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rt.*
            FROM raw_transactions rt
            JOIN (
                SELECT DISTINCT p.symbol, o.account_number
                FROM orders o
                JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                JOIN positions_new p ON o.order_id = p.order_id
                WHERE ocm.chain_id = ?
            ) chain_info ON rt.symbol = chain_info.symbol 
                         AND rt.account_number = chain_info.account_number
            ORDER BY rt.executed_at
        """, (chain_id,))
        
        columns = [description[0] for description in cursor.description]
        transactions = []
        for row in cursor.fetchall():
            tx_dict = dict(zip(columns, row))
            transactions.append(tx_dict)
    
    logger.info(f"Found {len(transactions)} transactions")
    
    # Process through new system
    order_processor = OrderProcessor(db_manager, position_manager)
    chains_by_account = order_processor.process_transactions(transactions)
    
    # Find the specific chain
    for account, chains in chains_by_account.items():
        for chain in chains:
            logger.info(f"\nChain: {chain.chain_id}")
            logger.info(f"  Status: {chain.status}")
            logger.info(f"  Orders: {len(chain.orders)}")
            
            for order in chain.orders:
                logger.info(f"    Order {order.order_id} ({order.order_type.value}):")
                for tx in order.transactions:
                    logger.info(f"      {tx.symbol}: {tx.action} {tx.quantity} @ ${tx.price}")
            
            # Check positions
            for symbol in chain.orders[0].symbols:
                position = position_manager.get_position(account, symbol)
                if position:
                    logger.info(f"  Position {symbol}: {position.current_quantity}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate to V2 order processing system')
    parser.add_argument('--test-chain', help='Test a specific chain ID')
    parser.add_argument('--dry-run', action='store_true', help='Run without making changes')
    
    args = parser.parse_args()
    
    if args.test_chain:
        test_specific_chain(args.test_chain)
    else:
        migrate_to_v2_system()