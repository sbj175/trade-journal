#!/usr/bin/env python3
"""
Fix chain strategies to match their opening order strategies
"""
import sqlite3
from pathlib import Path

def fix_chain_strategies():
    db_path = Path("trade_journal.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # First, find mismatched chains
        cursor.execute("""
            SELECT oc.chain_id, oc.strategy_type as chain_strategy, 
                   o.order_id, o.strategy_type as order_strategy
            FROM order_chains oc
            JOIN orders o ON oc.opening_order_id = o.order_id
            WHERE oc.strategy_type != o.strategy_type
        """)
        
        mismatches = cursor.fetchall()
        print(f"Found {len(mismatches)} chains with mismatched strategies:")
        
        for chain_id, chain_strat, order_id, order_strat in mismatches:
            print(f"  Chain {chain_id}: '{chain_strat}' -> '{order_strat}' (from order {order_id})")
        
        if mismatches:
            # Update all mismatched chains
            cursor.execute("""
                UPDATE order_chains 
                SET strategy_type = (
                    SELECT o.strategy_type 
                    FROM orders o 
                    WHERE o.order_id = order_chains.opening_order_id
                )
                WHERE chain_id IN (
                    SELECT oc.chain_id
                    FROM order_chains oc
                    JOIN orders o ON oc.opening_order_id = o.order_id
                    WHERE oc.strategy_type != o.strategy_type
                )
            """)
            
            updated = cursor.rowcount
            conn.commit()
            print(f"\nUpdated {updated} chain strategies to match their opening orders")
        
        # Verify the specific fix
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.strategy_type, o.strategy_type as opening_order_strategy
            FROM order_chains oc
            JOIN orders o ON oc.opening_order_id = o.order_id
            WHERE oc.chain_id = 'CHAIN_5WZ28644_IBIT_0075'
        """)
        
        result = cursor.fetchone()
        if result:
            print(f"\nVerification - Chain {result[0]}: {result[1]} {result[2]} (Opening order: {result[3]})")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_chain_strategies()