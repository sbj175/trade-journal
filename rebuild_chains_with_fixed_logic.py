#!/usr/bin/env python3
"""
Rebuild order chains with the fixed chain detection logic
This will fix the core logic issue where orders with expiration flags were excluded from chains
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

# Import the fixed logic from implement_order_position_model
from implement_order_position_model import detect_order_chains_fixed

def main():
    """Rebuild order chains with fixed logic"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        print("ERROR: Database not found")
        return
    
    print("Rebuilding order chains with FIXED chain detection logic...")
    print("- Removing incorrect exclusion of orders with expiration/assignment flags")
    print("- These orders can still be valid roll continuations")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Clear existing chains
        cursor = conn.cursor()
        cursor.execute("DELETE FROM order_chain_members")
        cursor.execute("DELETE FROM order_chains")
        print("Cleared existing chains")
        
        # Rebuild with fixed logic
        detect_order_chains_fixed(conn)
        conn.commit()
        
        # Show results for the specific order we're fixing
        cursor.execute("""
            SELECT oc.chain_id, oc.underlying, oc.strategy_type, oc.chain_status,
                   COUNT(ocm.order_id) as order_count,
                   GROUP_CONCAT(ocm.order_id || ' (seq:' || ocm.sequence_number || ')') as order_sequence
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE oc.underlying = 'IBIT'
            GROUP BY oc.chain_id
            ORDER BY oc.chain_id
        """)
        
        ibit_chains = cursor.fetchall()
        print(f"\nIBIT Chains after rebuild:")
        for chain in ibit_chains:
            print(f"  {chain['chain_id']}: {chain['strategy_type']} ({chain['order_count']} orders)")
            print(f"    Orders: {chain['order_sequence']}")
        
        # Specifically check if our problematic orders are now linked
        cursor.execute("""
            SELECT o1.order_id as order1, o2.order_id as order2, oc.chain_id
            FROM order_chain_members ocm1
            JOIN order_chain_members ocm2 ON ocm1.chain_id = ocm2.chain_id
            JOIN orders o1 ON ocm1.order_id = o1.order_id
            JOIN orders o2 ON ocm2.order_id = o2.order_id
            JOIN order_chains oc ON ocm1.chain_id = oc.chain_id
            WHERE (o1.order_id = '380086981' AND o2.order_id = '380871211')
               OR (o1.order_id = '380871211' AND o2.order_id = '380086981')
        """)
        
        linked = cursor.fetchone()
        if linked:
            print(f"\n✅ SUCCESS: Orders 380086981 and 380871211 are now linked in chain {linked['chain_id']}")
        else:
            print(f"\n❌ ISSUE: Orders 380086981 and 380871211 are still not linked")
            
        print(f"\nRebuild complete!")
        
    except Exception as e:
        print(f"ERROR during rebuild: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()