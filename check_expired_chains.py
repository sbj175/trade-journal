#!/usr/bin/env python3
"""
Check for IBIT chains that should be closed due to expiration but are showing as OPEN
"""

import sqlite3
from datetime import datetime, date

def check_expired_chains():
    """Check for chains with expired options that are still showing as OPEN"""
    
    print("Checking for Expired IBIT Chains Showing as OPEN")
    print("=" * 55)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current date
        today = date.today()
        print(f"Today's date: {today}")
        
        # Find IBIT chains that are OPEN but have expired options
        cursor.execute("""
            SELECT DISTINCT 
                oc.chain_id,
                oc.chain_status,
                oc.opening_date,
                oc.closing_date,
                p.expiration,
                p.symbol,
                p.option_type,
                p.strike
            FROM order_chains oc
            JOIN order_chain_members ocm ON oc.chain_id = ocm.chain_id
            JOIN positions_new p ON p.order_id = ocm.order_id
            WHERE oc.underlying = 'IBIT' 
            AND oc.chain_status = 'OPEN'
            AND p.expiration IS NOT NULL
            AND p.expiration < ?
            ORDER BY p.expiration, oc.chain_id
        """, (today.strftime('%Y-%m-%d'),))
        
        expired_chains = cursor.fetchall()
        
        if expired_chains:
            print(f"\n❌ Found {len(expired_chains)} expired positions in OPEN IBIT chains:")
            
            current_chain = None
            for chain_data in expired_chains:
                chain_id, status, open_date, close_date, exp, symbol, opt_type, strike = chain_data
                
                if chain_id != current_chain:
                    if current_chain is not None:
                        print()  # Add spacing between chains
                    print(f"\n🔴 Chain: {chain_id}")
                    print(f"   Status: {status} (should be CLOSED)")
                    print(f"   Dates: {open_date} to {close_date}")
                    current_chain = chain_id
                
                days_expired = (today - datetime.strptime(exp, '%Y-%m-%d').date()).days
                print(f"   - ${strike} {opt_type} expired {exp} ({days_expired} days ago)")
            
            # Check if there are expiration orders for these chains
            print(f"\n" + "="*55)
            print("Checking for Expiration Orders:")
            
            for chain_data in expired_chains:
                chain_id = chain_data[0]
                exp_date = chain_data[4]
                
                # Look for expiration orders
                cursor.execute("""
                    SELECT o.order_id, o.order_type, o.order_date
                    FROM orders o
                    JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                    WHERE ocm.chain_id = ?
                    AND o.order_type = 'CLOSING'
                    AND o.order_date >= ?
                """, (chain_id, exp_date))
                
                exp_orders = cursor.fetchall()
                
                # Also check for system expiration orders
                cursor.execute("""
                    SELECT o.order_id, o.order_type, o.order_date
                    FROM orders o
                    WHERE o.order_id LIKE 'SYSTEM_EXPIRATION_%'
                    AND o.order_date >= ?
                """, (exp_date,))
                
                system_exp_orders = cursor.fetchall()
                
                print(f"\nChain {chain_id}:")
                if exp_orders:
                    print(f"   Expiration orders in chain: {len(exp_orders)}")
                    for order in exp_orders:
                        print(f"   - {order[0]} ({order[1]}) on {order[2]}")
                else:
                    print(f"   ❌ No expiration orders found in chain")
                
                if system_exp_orders:
                    print(f"   System expiration orders around {exp_date}: {len(system_exp_orders)}")
                    for order in system_exp_orders[:3]:  # Show first 3
                        print(f"   - {order[0]} on {order[2]}")
                else:
                    print(f"   ❌ No system expiration orders found for {exp_date}")
            
            print(f"\n" + "="*55)
            print("Diagnosis:")
            print("   This suggests our position balance logic for chain closure")
            print("   is not properly handling expired options.")
            print("   Expired options should have zero remaining balance and")
            print("   mark the chain as CLOSED.")
            
        else:
            print(f"\n✅ No expired IBIT chains found showing as OPEN")
            
        # Also check all IBIT chains for reference
        print(f"\n" + "="*55)
        print("All IBIT Chains Summary:")
        
        cursor.execute("""
            SELECT chain_id, chain_status, opening_date, closing_date,
                   (SELECT MIN(p.expiration) FROM positions_new p 
                    JOIN order_chain_members ocm ON p.order_id = ocm.order_id 
                    WHERE ocm.chain_id = oc.chain_id) as min_exp
            FROM order_chains oc
            WHERE oc.underlying = 'IBIT'
            ORDER BY opening_date DESC
            LIMIT 10
        """)
        
        all_chains = cursor.fetchall()
        for chain in all_chains:
            chain_id, status, open_date, close_date, min_exp = chain
            status_icon = "🔴" if status == 'OPEN' else "🟢"
            
            if min_exp and min_exp < today.strftime('%Y-%m-%d'):
                exp_status = f"EXPIRED {min_exp}"
            else:
                exp_status = f"Active until {min_exp}" if min_exp else "No expiration"
                
            print(f"{status_icon} {chain_id}: {status} ({open_date} to {close_date}) - {exp_status}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_expired_chains()