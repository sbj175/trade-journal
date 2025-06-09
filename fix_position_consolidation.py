#!/usr/bin/env python3
"""
Fix position consolidation and expiration linking issues
"""

import sqlite3
from datetime import datetime
from loguru import logger

def consolidate_positions_by_order():
    """Consolidate multiple transactions of same symbol into single positions"""
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    try:
        # Get all orders that need position consolidation
        cursor.execute("""
            SELECT order_id, symbol, instrument_type, option_type, strike, expiration, 
                   opening_action, account_number
            FROM positions_new 
            GROUP BY order_id, symbol, option_type, strike, expiration
            HAVING COUNT(*) > 1
        """)
        
        consolidation_groups = cursor.fetchall()
        logger.info(f"Found {len(consolidation_groups)} position groups needing consolidation")
        
        for group in consolidation_groups:
            order_id, symbol, instrument_type, option_type, strike, expiration, opening_action, account_number = group
            
            # Get all positions in this group
            cursor.execute("""
                SELECT position_id, quantity, opening_price, pnl, opening_transaction_id
                FROM positions_new
                WHERE order_id = ? AND symbol = ? 
                AND (option_type = ? OR (option_type IS NULL AND ? IS NULL))
                AND (strike = ? OR (strike IS NULL AND ? IS NULL))
                AND (expiration = ? OR (expiration IS NULL AND ? IS NULL))
            """, (order_id, symbol, option_type, option_type, strike, strike, expiration, expiration))
            
            positions = cursor.fetchall()
            
            if len(positions) > 1:
                logger.info(f"Consolidating {len(positions)} positions for {symbol} in order {order_id}")
                
                # Calculate consolidated values
                total_quantity = sum(pos[1] for pos in positions)
                # Use weighted average for opening price
                total_value = sum(pos[1] * pos[2] for pos in positions)
                avg_opening_price = total_value / total_quantity if total_quantity != 0 else 0
                total_pnl = sum(pos[3] for pos in positions)
                
                # Keep the first position, update its values
                first_position_id = positions[0][0]
                first_transaction_id = positions[0][4]
                
                cursor.execute("""
                    UPDATE positions_new 
                    SET quantity = ?, opening_price = ?, pnl = ?
                    WHERE position_id = ?
                """, (total_quantity, avg_opening_price, total_pnl, first_position_id))
                
                # Delete the duplicate positions
                position_ids_to_delete = [pos[0] for pos in positions[1:]]
                cursor.executemany("DELETE FROM positions_new WHERE position_id = ?", 
                                 [(pid,) for pid in position_ids_to_delete])
                
                logger.info(f"Consolidated to single position: qty={total_quantity}, price=${avg_opening_price:.2f}")
        
        conn.commit()
        logger.info("Position consolidation completed")
        
    except Exception as e:
        logger.error(f"Error during position consolidation: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def link_expiration_transactions():
    """Link expiration transactions to their original positions"""
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    try:
        # Find expiration transactions without order_id
        cursor.execute("""
            SELECT id, symbol, quantity, executed_at, description
            FROM raw_transactions
            WHERE order_id IS NULL 
            AND (description LIKE '%expiration%' OR description LIKE '%Expiration%')
        """)
        
        expiration_txs = cursor.fetchall()
        logger.info(f"Found {len(expiration_txs)} expiration transactions to link")
        
        for tx_id, symbol, quantity, executed_at, description in expiration_txs:
            logger.info(f"Processing expiration: {symbol}, qty={quantity}")
            
            # Find matching open position
            cursor.execute("""
                SELECT p.position_id, p.order_id, p.quantity
                FROM positions_new p
                WHERE p.symbol = ? 
                AND p.status = 'OPEN'
                AND ABS(p.quantity) = ABS(?)
                ORDER BY p.created_at ASC
                LIMIT 1
            """, (symbol, quantity))
            
            matching_position = cursor.fetchone()
            
            if matching_position:
                position_id, order_id, pos_quantity = matching_position
                
                logger.info(f"Linking expiration to position {position_id} in order {order_id}")
                
                # Update the position as expired
                cursor.execute("""
                    UPDATE positions_new
                    SET closing_action = 'EXPIRED',
                        closing_price = 0.0,
                        closing_transaction_id = ?,
                        status = 'CLOSED',
                        pnl = ? * 100  -- For options, multiply by 100
                    WHERE position_id = ?
                """, (tx_id, pos_quantity * 0.22, position_id))  # Original premium was $0.22
                
                # Update the order status
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'CLOSED',
                        has_expiration = 1,
                        total_pnl = (
                            SELECT COALESCE(SUM(pnl), 0) 
                            FROM positions_new 
                            WHERE order_id = orders.order_id
                        )
                    WHERE order_id = ?
                """, (order_id,))
                
                logger.info(f"Updated order {order_id} as CLOSED with expiration")
            else:
                logger.warning(f"No matching position found for expiration: {symbol}, qty={quantity}")
        
        conn.commit()
        logger.info("Expiration linking completed")
        
    except Exception as e:
        logger.error(f"Error during expiration linking: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def fix_rolling_chain_detection():
    """Fix rolling chain detection for expired orders"""
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    try:
        # Find orders that are marked as OPENING but should not be in rolling chains
        cursor.execute("""
            SELECT DISTINCT oc.chain_id, oc.opening_order_id
            FROM order_chains oc
            JOIN orders o ON oc.opening_order_id = o.order_id
            WHERE o.has_expiration = 1
            AND o.status = 'CLOSED'
            AND oc.chain_id IN (
                SELECT chain_id FROM order_chain_members GROUP BY chain_id HAVING COUNT(*) > 1
            )
        """)
        
        expired_chains = cursor.fetchall()
        
        for chain_id, opening_order_id in expired_chains:
            logger.info(f"Fixing chain {chain_id} - removing expired order {opening_order_id} from multi-order chain")
            
            # Remove this order from multi-order chains and create its own chain
            new_chain_id = f"{chain_id}_EXPIRED"
            
            # Create new chain for just this expired order
            cursor.execute("""
                INSERT OR REPLACE INTO order_chains (
                    chain_id, underlying, account_number, opening_order_id,
                    strategy_type, chain_status, total_pnl
                )
                SELECT ?, underlying, account_number, order_id, strategy_type, 'CLOSED', total_pnl
                FROM orders WHERE order_id = ?
            """, (new_chain_id, opening_order_id))
            
            # Move the order to the new chain
            cursor.execute("""
                UPDATE order_chain_members 
                SET chain_id = ?
                WHERE order_id = ? AND chain_id = ?
            """, (new_chain_id, opening_order_id, chain_id))
            
            logger.info(f"Created separate chain {new_chain_id} for expired order")
        
        conn.commit()
        logger.info("Rolling chain detection fixed")
        
    except Exception as e:
        logger.error(f"Error fixing rolling chains: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def main():
    """Run all fixes"""
    logger.info("Starting position consolidation and expiration fixes...")
    
    # Step 1: Consolidate duplicate positions
    consolidate_positions_by_order()
    
    # Step 2: Link expiration transactions
    link_expiration_transactions()
    
    # Step 3: Fix rolling chain detection
    fix_rolling_chain_detection()
    
    logger.info("All fixes completed successfully!")

if __name__ == "__main__":
    main()