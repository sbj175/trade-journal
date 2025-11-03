#!/usr/bin/env python3
"""
Test the ZEBRA strategy detection in the frontend logic
"""

import sqlite3
import json

def test_zebra_detection():
    """Test ZEBRA detection by simulating the frontend logic"""
    
    print("Testing ZEBRA Strategy Detection")
    print("=" * 40)
    
    db_path = "/home/sbj/python-projects/trade-journal/trade_journal.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get the IBIT opening order positions
        cursor.execute("""
            SELECT symbol, quantity, opening_action, option_type, strike, expiration
            FROM positions_new 
            WHERE order_id = '388512672'
            ORDER BY strike
        """)
        
        positions = cursor.fetchall()
        print(f"IBIT Order 388512672 Positions:")
        
        # Convert to the format the frontend expects
        frontend_positions = []
        for pos in positions:
            symbol, qty, action, opt_type, strike, exp = pos
            frontend_pos = {
                'symbol': symbol,
                'quantity': qty,
                'opening_action': action,
                'option_type': opt_type.upper() if opt_type else '',
                'strike': strike,
                'expiration': exp
            }
            frontend_positions.append(frontend_pos)
            print(f"   {action} {qty}x {symbol} ${strike} {opt_type} {exp}")
        
        # Simulate the frontend strategy detection logic
        print(f"\nStrategy Detection Logic:")
        
        # Filter option positions
        option_positions = [p for p in frontend_positions if 
                          p['option_type'] in ['CALL', 'PUT'] or 
                          'OPTION' in (p.get('instrument_type') or '')]
        
        print(f"   Option positions found: {len(option_positions)}")
        
        if len(option_positions) == 2:
            # Sort by strike
            opt_positions = sorted(option_positions, key=lambda x: x['strike'] or 0)
            opt1, opt2 = opt_positions
            
            print(f"   Position 1: {opt1['quantity']}x ${opt1['strike']} {opt1['option_type']} - {opt1['opening_action']}")
            print(f"   Position 2: {opt2['quantity']}x ${opt2['strike']} {opt2['option_type']} - {opt2['opening_action']}")
            
            # Check strategy detection logic
            opt1_type = (opt1.get('option_type') or '').upper()
            opt2_type = (opt2.get('option_type') or '').upper()
            same_type = opt1_type == opt2_type
            same_expiration = opt1['expiration'] == opt2['expiration']
            same_strike = opt1['strike'] == opt2['strike']
            
            print(f"   Same type: {same_type} ({opt1_type} vs {opt2_type})")
            print(f"   Same expiration: {same_expiration}")
            print(f"   Same strike: {same_strike}")
            
            if not same_strike and same_expiration and same_type:
                print(f"   ✅ Qualifies for vertical spread or ZEBRA analysis")
                
                # ZEBRA detection logic
                is_call = opt1_type == 'CALL'
                opt1_qty = abs(opt1['quantity'] or 0)
                opt2_qty = abs(opt2['quantity'] or 0)
                
                opt1_is_buy = 'BUY' in (opt1['opening_action'] or '').upper()
                opt2_is_buy = 'BUY' in (opt2['opening_action'] or '').upper()
                
                ratio1to2 = opt1_qty / opt2_qty if opt2_qty > 0 else 0
                ratio2to1 = opt2_qty / opt1_qty if opt1_qty > 0 else 0
                
                print(f"   Quantities: {opt1_qty} vs {opt2_qty}")
                print(f"   Ratio 1:2 = {ratio1to2}")
                print(f"   Ratio 2:1 = {ratio2to1}")
                print(f"   Opt1 is buy: {opt1_is_buy}")
                print(f"   Opt2 is buy: {opt2_is_buy}")
                print(f"   Is call: {is_call}")
                
                # Check ZEBRA patterns
                detected_strategy = None
                
                if is_call and opt1_is_buy and not opt2_is_buy and ratio1to2 == 2:
                    detected_strategy = 'Bull ZEBRA'
                elif not is_call and opt1_is_buy and not opt2_is_buy and ratio1to2 == 2:
                    detected_strategy = 'Bear ZEBRA'
                elif is_call and not opt1_is_buy and opt2_is_buy and ratio2to1 == 2:
                    detected_strategy = 'Bull ZEBRA'
                elif not is_call and not opt1_is_buy and opt2_is_buy and ratio2to1 == 2:
                    detected_strategy = 'Bear ZEBRA'
                else:
                    # Fall back to standard spreads
                    buy_lower = opt1_is_buy
                    sell_higher = not opt2_is_buy
                    
                    if is_call:
                        if buy_lower and sell_higher:
                            detected_strategy = 'Bull Call Spread'
                        elif not buy_lower and not sell_higher:
                            detected_strategy = 'Bear Call Spread'
                    else:
                        if buy_lower and sell_higher:
                            detected_strategy = 'Bull Put Spread'
                        elif not buy_lower and not sell_higher:
                            detected_strategy = 'Bear Put Spread'
                
                print(f"\n🎯 DETECTED STRATEGY: {detected_strategy}")
                
                if detected_strategy == 'Bull ZEBRA':
                    print(f"   ✅ SUCCESS: Correctly identified as Bull ZEBRA!")
                    print(f"   - 2:1 ratio detected")
                    print(f"   - Long ITM calls, short ATM calls")
                    print(f"   - Bullish setup")
                elif detected_strategy == 'Bull Call Spread':
                    print(f"   ❌ ISSUE: Still showing as Bull Call Spread")
                    print(f"   - May need to debug ratio calculation")
                else:
                    print(f"   ❓ Unexpected result: {detected_strategy}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_zebra_detection()