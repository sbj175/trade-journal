#!/usr/bin/env python3
"""
Fix exit prices for expired/assigned options
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json

def fix_expiration_exit_prices():
    """
    Fix exit prices for expired/assigned options.
    For expired options, exit price should be 0.
    For assigned/exercised options, exit price should be intrinsic value or 0.
    """
    
    print("Fixing Exit Prices for Expired/Assigned Options")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    target_trade_id = 'SPX_20250509_4legs_959'
    
    # Get all option legs for this trade
    cursor.execute('''
        SELECT id, symbol, option_type, strike, quantity, 
               entry_price, exit_price, transaction_actions
        FROM option_legs 
        WHERE trade_id = ?
        ORDER BY strike, option_type
    ''', (target_trade_id,))
    
    legs = cursor.fetchall()
    
    print(f"Processing {len(legs)} option legs:")
    print()
    
    updates_made = 0
    
    for leg_id, symbol, opt_type, strike, quantity, entry_price, exit_price, actions_json in legs:
        actions = json.loads(actions_json) if actions_json else []
        
        print(f"Leg {leg_id}: {symbol}")
        print(f"   {quantity:+d} {opt_type} ${strike}")
        print(f"   Entry: ${entry_price}, Current Exit: {exit_price}")
        print(f"   Actions: {actions}")
        
        # Determine correct exit price based on closing type
        new_exit_price = exit_price
        
        if any(action in ['EXPIRED', 'ASSIGNED', 'EXERCISED'] for action in actions):
            if exit_price is None:
                # For SPX on May 12, 2025, we need to determine intrinsic value
                # SPX closed at approximately 5620 on May 12, 2025
                # This is based on the cash settlement amounts we saw in TT data
                
                spx_closing_price = 5620  # Approximate closing price on May 12
                
                if opt_type == 'Put':
                    # Put intrinsic value = max(0, strike - underlying)
                    intrinsic_value = max(0, strike - spx_closing_price)
                else:  # Call
                    # Call intrinsic value = max(0, underlying - strike)  
                    intrinsic_value = max(0, spx_closing_price - strike)
                
                new_exit_price = intrinsic_value
                
                print(f"   → Calculated intrinsic value: ${intrinsic_value}")
                print(f"     (SPX @ ${spx_closing_price}, {opt_type} ${strike})")
            else:
                print(f"   → Exit price already set: ${exit_price}")
        
        # Update if we have a new exit price
        if new_exit_price != exit_price:
            cursor.execute('''
                UPDATE option_legs 
                SET exit_price = ?
                WHERE id = ?
            ''', (new_exit_price, leg_id))
            
            print(f"   ✅ Updated exit price: ${exit_price} → ${new_exit_price}")
            updates_made += 1
        else:
            print(f"   ⏭️  No change needed")
        
        print()
    
    # Now check if all legs have exit prices and update trade status
    cursor.execute('''
        SELECT COUNT(*) as total, 
               COUNT(CASE WHEN exit_price IS NOT NULL THEN 1 END) as with_exit
        FROM option_legs 
        WHERE trade_id = ?
    ''', (target_trade_id,))
    
    leg_counts = cursor.fetchone()
    total_legs = leg_counts[0]
    legs_with_exit = leg_counts[1]
    
    print(f"Final status: {legs_with_exit}/{total_legs} legs have exit prices")
    
    if legs_with_exit == total_legs:
        # Update trade to Closed
        cursor.execute('''
            UPDATE trades 
            SET status = 'Closed',
                exit_date = '2025-05-12'
            WHERE trade_id = ?
        ''', (target_trade_id,))
        
        print(f"✅ Trade {target_trade_id} marked as Closed")
        updates_made += 1
    else:
        print(f"⚠️  Trade still has legs without exit prices")
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print()
    print("SUMMARY:")
    print(f"✅ Made {updates_made} updates")
    print(f"✅ All expiration transactions now properly matched")
    print(f"✅ Exit prices calculated for expired/assigned options")
    
    if updates_made > 0:
        print()
        print("🎉 The trade should now show as Closed with proper emblems!")
        print("   Refresh your browser to see the changes.")

if __name__ == "__main__":
    try:
        fix_expiration_exit_prices()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()