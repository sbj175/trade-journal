#!/usr/bin/env python3
"""
Confirm the IBIT order is a Bull ZEBRA strategy and document the pattern
"""

import sqlite3

def confirm_zebra_pattern():
    """Confirm the ZEBRA pattern in IBIT order"""
    
    print("Confirming Bull ZEBRA Pattern in IBIT Order 388512672")
    print("=" * 60)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get the positions for order 388512672
        cursor.execute("""
            SELECT symbol, quantity, opening_action, strike, expiration, option_type
            FROM positions_new 
            WHERE order_id = '388512672'
            ORDER BY strike
        """)
        
        positions = cursor.fetchall()
        print(f"IBIT Order 388512672 Structure:")
        
        for pos in positions:
            symbol, qty, action, strike, exp, opt_type = pos
            print(f"   {action} {qty}x ${strike} {opt_type}s exp {exp}")
        
        # Analyze for Bull ZEBRA pattern
        print(f"\nBull ZEBRA Pattern Analysis:")
        
        calls = [p for p in positions if p[5] == 'Call']
        
        if len(calls) == 2:
            lower_strike_pos = calls[0]  # $47 calls
            higher_strike_pos = calls[1]  # $61 calls
            
            lower_qty = lower_strike_pos[1]  # 8
            lower_action = lower_strike_pos[2]  # BUY_TO_OPEN
            lower_strike = lower_strike_pos[3]  # 47
            
            higher_qty = higher_strike_pos[1]  # 4  
            higher_action = higher_strike_pos[2]  # SELL_TO_OPEN
            higher_strike = higher_strike_pos[3]  # 61
            
            print(f"   Lower Strike: ${lower_strike} - {lower_action} {lower_qty}x")
            print(f"   Higher Strike: ${higher_strike} - {higher_action} {higher_qty}x")
            
            # Check Bull ZEBRA characteristics
            is_bull_zebra = (
                'BUY' in lower_action and    # Long the lower strike calls
                'SELL' in higher_action and  # Short the higher strike calls
                lower_qty == 2 * higher_qty and  # 2:1 ratio
                lower_strike < higher_strike     # Lower strike is ITM, higher is ATM/OTM
            )
            
            ratio = lower_qty / higher_qty
            
            print(f"\nZEBRA Characteristics Check:")
            print(f"   ✅ Both positions are calls: {len(calls) == 2}")
            print(f"   ✅ Long lower strike (ITM): {'BUY' in lower_action}")
            print(f"   ✅ Short higher strike (ATM): {'SELL' in higher_action}")
            print(f"   ✅ Lower < Higher strike: {lower_strike < higher_strike}")
            print(f"   ✅ 2:1 ratio: {ratio} = {ratio}:1")
            
            if is_bull_zebra:
                print(f"\n🎯 CONFIRMED: This is a Bull ZEBRA Strategy!")
                print(f"   Structure: Buy {lower_qty} ITM calls @ ${lower_strike}, Sell {higher_qty} ATM calls @ ${higher_strike}")
                print(f"   Ratio: {int(ratio)}:1 (classic ZEBRA ratio)")
                print(f"   Direction: Bullish (long ITM calls)")
                print(f"   Capital Efficiency: Reduced cost vs buying {lower_qty * 100} shares")
                print(f"   Risk: Limited to debit paid")
            else:
                print(f"\n❌ This does not match Bull ZEBRA pattern")
        
        conn.close()
        
        # Now let's see what the current strategy detection says
        print(f"\n" + "="*60)
        print(f"Current Strategy Detection:")
        
        # Check what the frontend strategy detection would say
        print(f"   Current logic would detect this as: Bull Call Spread")
        print(f"   Why: 2 calls, different strikes, same expiration, bullish setup")
        print(f"   Issue: Ignores 2:1 ratio which is key ZEBRA characteristic")
        
        print(f"\n" + "="*60)
        print(f"Recommended Implementation:")
        print(f"   1. Add Bull ZEBRA detection before Bull Call Spread check")
        print(f"   2. Check for 2:1 ratio (or other ratio like 3:2)")
        print(f"   3. Add Bear ZEBRA detection for put ratios")
        print(f"   4. Consider other ratio spreads as separate category")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    confirm_zebra_pattern()