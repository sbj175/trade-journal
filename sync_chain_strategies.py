#!/usr/bin/env python3
"""
Sync chain strategies with their opening order strategies
This should be run after any strategy recognition updates
"""
import sqlite3
from pathlib import Path

def sync_all_chain_strategies():
    """Ensure all chain strategies match their opening order strategies"""
    db_path = Path("trade_journal.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Syncing chain strategies with opening order strategies...")
        
        # Update ALL chains to match their opening orders
        cursor.execute("""
            UPDATE order_chains 
            SET strategy_type = (
                SELECT o.strategy_type 
                FROM orders o 
                WHERE o.order_id = order_chains.opening_order_id
            )
            WHERE opening_order_id IN (
                SELECT order_id FROM orders
            )
        """)
        
        total_updated = cursor.rowcount
        conn.commit()
        
        print(f"Updated {total_updated} chain strategies")
        
        # Show some examples
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.strategy_type, 
                   COUNT(ocm.order_id) as order_count
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE oc.strategy_type IN ('Zebra', 'Butterfly', 'Iron Condor', 'Iron Butterfly')
               OR oc.strategy_type LIKE '%Ratio%'
            GROUP BY oc.chain_id
            ORDER BY oc.underlying, oc.chain_id
            LIMIT 10
        """)
        
        special_strategies = cursor.fetchall()
        if special_strategies:
            print("\nExample special strategies:")
            for chain_id, underlying, strategy, order_count in special_strategies:
                print(f"  {underlying} {strategy} (Chain: {chain_id}, Orders: {order_count})")
                
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    sync_all_chain_strategies()