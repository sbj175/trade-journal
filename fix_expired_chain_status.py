#!/usr/bin/env python3
"""
Fix chain status for chains with expired/assigned positions
These chains should show as CLOSED, not OPEN
"""

import sqlite3
from pathlib import Path

def fix_expired_chain_status():
    """Update chain status for chains with expiration/assignment/exercise"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        print("ERROR: Database not found")
        return
    
    print("FIXING CHAIN STATUS FOR EXPIRED/ASSIGNED POSITIONS")
    print("Chains with expiration/assignment/exercise should show as CLOSED, not OPEN")
    print("")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        cursor = conn.cursor()
        
        # Find chains that should be CLOSED but are marked as OPEN
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.chain_status,
                   COUNT(CASE WHEN o.has_expiration = 1 THEN 1 END) as expired_orders,
                   COUNT(CASE WHEN o.has_assignment = 1 THEN 1 END) as assigned_orders,
                   COUNT(CASE WHEN o.has_exercise = 1 THEN 1 END) as exercised_orders,
                   COUNT(CASE WHEN o.order_type = 'CLOSING' THEN 1 END) as closing_orders,
                   GROUP_CONCAT(o.order_id) as order_ids
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            JOIN orders o ON ocm.order_id = o.order_id
            WHERE oc.chain_status = 'OPEN'
            GROUP BY oc.chain_id
            HAVING expired_orders > 0 OR assigned_orders > 0 OR exercised_orders > 0 OR closing_orders > 0
        """)
        
        chains_to_fix = cursor.fetchall()
        
        print(f"Found {len(chains_to_fix)} chains that should be CLOSED:")
        
        for chain in chains_to_fix:
            reasons = []
            if chain['expired_orders'] > 0:
                reasons.append(f"{chain['expired_orders']} expired")
            if chain['assigned_orders'] > 0:
                reasons.append(f"{chain['assigned_orders']} assigned")
            if chain['exercised_orders'] > 0:
                reasons.append(f"{chain['exercised_orders']} exercised")
            if chain['closing_orders'] > 0:
                reasons.append(f"{chain['closing_orders']} closing")
            
            print(f"  {chain['chain_id']}: {chain['underlying']} ({', '.join(reasons)})")
        
        if chains_to_fix:
            # Update chain status
            cursor.execute("""
                UPDATE order_chains 
                SET chain_status = 'CLOSED'
                WHERE chain_id IN (
                    SELECT oc.chain_id
                    FROM order_chains oc
                    JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
                    JOIN orders o ON ocm.order_id = o.order_id
                    WHERE oc.chain_status = 'OPEN'
                    GROUP BY oc.chain_id
                    HAVING COUNT(CASE WHEN o.has_expiration = 1 THEN 1 END) > 0 
                        OR COUNT(CASE WHEN o.has_assignment = 1 THEN 1 END) > 0
                        OR COUNT(CASE WHEN o.has_exercise = 1 THEN 1 END) > 0
                        OR COUNT(CASE WHEN o.order_type = 'CLOSING' THEN 1 END) > 0
                )
            """)
            
            updated_count = cursor.rowcount
            conn.commit()
            
            print(f"\n✅ Updated {updated_count} chains from OPEN to CLOSED")
        else:
            print("No chains need status updates")
        
        # Show examples of chains with their correct status
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.chain_status,
                   COUNT(CASE WHEN o.has_expiration = 1 THEN 1 END) as expired_orders,
                   COUNT(CASE WHEN o.has_assignment = 1 THEN 1 END) as assigned_orders,
                   COUNT(CASE WHEN o.order_type = 'CLOSING' THEN 1 END) as closing_orders
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            JOIN orders o ON ocm.order_id = o.order_id
            GROUP BY oc.chain_id
            HAVING expired_orders > 0 OR assigned_orders > 0 OR closing_orders > 0
            ORDER BY oc.underlying
            LIMIT 10
        """)
        
        examples = cursor.fetchall()
        if examples:
            print(f"\nExample chains with correct status:")
            for chain in examples:
                status_color = "🟢" if chain['chain_status'] == 'OPEN' else "🔴"
                reasons = []
                if chain['expired_orders'] > 0:
                    reasons.append(f"expired")
                if chain['assigned_orders'] > 0:
                    reasons.append(f"assigned")
                if chain['closing_orders'] > 0:
                    reasons.append(f"closing")
                
                print(f"  {status_color} {chain['chain_id']}: {chain['underlying']} {chain['chain_status']} ({', '.join(reasons)})")
        
        print("\nChain status fix complete!")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    fix_expired_chain_status()