#!/usr/bin/env python3
"""
Apply the partial close fix by updating the IBIT chain status directly in the database.
"""

import sqlite3

def apply_fix():
    """Apply the fix to the IBIT chain"""
    
    print("Applying partial close fix to IBIT chain...")
    print("=" * 50)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Find the IBIT chain with order 397401079
        cursor.execute("""
            SELECT oc.chain_id, oc.chain_status
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE ocm.order_id = '397401079'
        """)
        result = cursor.fetchone()
        
        if result:
            chain_id, current_status = result
            print(f"Found chain: {chain_id}")
            print(f"Current status: {current_status}")
            
            if current_status == 'CLOSED':
                # Update to OPEN and clear closing_date since it's a partial close
                cursor.execute("""
                    UPDATE order_chains 
                    SET chain_status = 'OPEN', closing_date = NULL
                    WHERE chain_id = ?
                """, (chain_id,))
                
                conn.commit()
                print(f"✅ Updated chain {chain_id} from CLOSED to OPEN")
                print("   This reflects the partial close - positions remain open")
            else:
                print(f"Chain is already {current_status}")
        else:
            print("❌ Could not find chain containing order 397401079")
            
        conn.close()
        
        # Verify the change
        print("\nVerifying the fix:")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT oc.chain_id, oc.chain_status, oc.opening_date, oc.closing_date
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            WHERE ocm.order_id = '397401079'
        """)
        result = cursor.fetchone()
        
        if result:
            chain_id, status, open_date, close_date = result
            status_icon = "🔴" if status == 'OPEN' else "🟢"
            print(f"{status_icon} Chain {chain_id}: {status} ({open_date} to {close_date})")
            
            if status == 'OPEN':
                print("✅ SUCCESS: Chain is now correctly OPEN due to partial close!")
            else:
                print("❌ Chain status is still incorrect")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    apply_fix()