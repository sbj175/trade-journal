#!/usr/bin/env python3
"""
Analyze the IBIT order 388512672 to confirm it's a Bull ZEBRA strategy
"""

import sqlite3

def analyze_ibit_strategy():
    """Analyze the IBIT opening order to understand the strategy structure"""
    
    print("Analyzing IBIT Order 388512672 Strategy")
    print("=" * 50)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get the positions for order 388512672
        cursor.execute("""
            SELECT symbol, quantity, opening_action, closing_action, strike, expiration, option_type
            FROM positions_new 
            WHERE order_id = '388512672'
            ORDER BY strike, option_type
        """)
        
        positions = cursor.fetchall()
        print(f"Order 388512672 has {len(positions)} positions:")
        
        for pos in positions:
            symbol, qty, open_action, close_action, strike, exp, opt_type = pos
            print(f"   {open_action} {qty}x {symbol} ${strike} {opt_type} {exp}")
        
        # Analyze the structure
        print("\nStrategy Analysis:")
        
        calls = [p for p in positions if p[6] == 'CALL']
        puts = [p for p in positions if p[6] == 'PUT']
        
        print(f"   Calls: {len(calls)}")
        print(f"   Puts: {len(puts)}")
        
        if len(calls) == 2 and len(puts) == 0:
            # This is a call-based strategy
            call_1 = calls[0]
            call_2 = calls[1]
            
            qty_1 = call_1[1]
            qty_2 = call_2[1] 
            strike_1 = call_1[4]
            strike_2 = call_2[4]
            action_1 = call_1[2]
            action_2 = call_2[2]
            
            print(f"\nCall Structure:")
            print(f"   Strike ${strike_1}: {action_1} {qty_1}x")
            print(f"   Strike ${strike_2}: {action_2} {qty_2}x")
            
            # Check for Bull ZEBRA pattern:
            # - Buy 2x lower strike calls (ITM)
            # - Sell 1x higher strike calls (ATM)
            # - Ratio 2:1
            
            long_positions = [(p[4], p[1]) for p in calls if 'BUY' in p[2]]
            short_positions = [(p[4], p[1]) for p in calls if 'SELL' in p[2]]
            
            print(f"\nLong positions: {long_positions}")
            print(f"Short positions: {short_positions}")
            
            if len(long_positions) == 1 and len(short_positions) == 1:
                long_strike, long_qty = long_positions[0]
                short_strike, short_qty = short_positions[0]
                
                print(f"\nStrategy Characteristics:")
                print(f"   Long Strike: ${long_strike} x{long_qty}")
                print(f"   Short Strike: ${short_strike} x{short_qty}")
                print(f"   Ratio: {long_qty}:{short_qty}")
                
                if long_qty == 8 and short_qty == 4:
                    print(f"   Ratio simplified: {long_qty//4}:{short_qty//4} = 2:1")
                    
                if long_strike < short_strike and long_qty > short_qty:
                    ratio = long_qty / short_qty
                    if ratio == 2.0:
                        print(f"\n✅ CONFIRMED: This is a Bull ZEBRA strategy!")
                        print(f"   - Buy {long_qty}x ITM calls @ ${long_strike}")
                        print(f"   - Sell {short_qty}x ATM calls @ ${short_strike}")
                        print(f"   - 2:1 ratio (characteristic of ZEBRA)")
                        print(f"   - Lower strike long, higher strike short (bullish)")
                    else:
                        print(f"\n⚠️  This looks like a ratio spread with {ratio}:1 ratio")
                else:
                    print(f"\n❓ Unknown call strategy pattern")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    analyze_ibit_strategy()