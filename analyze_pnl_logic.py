#!/usr/bin/env python3
"""
Analyze P&L calculation logic for IBIT chain with order 397401079
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

def analyze_pnl_logic():
    """Analyze the P&L calculation logic step by step"""
    
    db = DatabaseManager()
    db.ensure_initialized()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get IBIT positions for the chain orders
        print("=== POSITIONS ANALYSIS ===")
        cursor.execute("""
            SELECT p.* FROM positions_new p
            WHERE p.order_id IN ('388512672', '397401079')
            ORDER BY p.strike, p.expiration, p.opening_action
        """)
        positions = [dict(row) for row in cursor.fetchall()]
        
        # Group by strike and expiration
        from collections import defaultdict
        position_groups = defaultdict(list)
        
        for pos in positions:
            key = (pos['symbol'], pos['strike'], pos['expiration'])
            position_groups[key].append(pos)
        
        print("Positions grouped by strike/expiration:")
        for key, group in position_groups.items():
            symbol, strike, expiration = key
            print(f"\n{symbol} Strike ${strike} Exp {expiration}:")
            
            opening_pnl = 0.0
            closing_pnl = 0.0
            has_opening = False
            has_closing = False
            
            for pos in group:
                action_type = "OPENING" if 'TO_OPEN' in pos['opening_action'] else "CLOSING"
                print(f"  {action_type}: {pos['opening_action']} x{pos['quantity']} @ ${pos['opening_price']} = ${pos['pnl']}")
                
                if 'TO_OPEN' in pos['opening_action']:
                    opening_pnl += pos['pnl']
                    has_opening = True
                elif 'TO_CLOSE' in pos['opening_action']:
                    closing_pnl += pos['pnl']
                    has_closing = True
            
            print(f"  Opening P&L: ${opening_pnl}")
            print(f"  Closing P&L: ${closing_pnl}")
            print(f"  Has opening: {has_opening}, Has closing: {has_closing}")
            
            if has_opening and has_closing:
                round_trip_pnl = opening_pnl + closing_pnl
                print(f"  -> REALIZED ROUND TRIP: ${round_trip_pnl}")
            elif has_opening and not has_closing:
                print(f"  -> UNREALIZED (open position): ${opening_pnl}")
            else:
                print(f"  -> ORPHAN CLOSING: ${closing_pnl}")
        
        print("\n=== CURRENT CALCULATION RESULTS ===")
        from src.models.order_models import OrderManager
        
        order_manager = OrderManager(db)
        chain_id = 'IBIT_OPENING_20250609_38851267'
        chain_status = 'OPEN'
        
        realized_pnl = order_manager.calculate_chain_realized_pnl(chain_id, chain_status)
        unrealized_pnl = order_manager.calculate_chain_unrealized_pnl(chain_id, chain_status)
        
        print(f"Current method calculates:")
        print(f"  Realized P&L: ${realized_pnl}")
        print(f"  Unrealized P&L: ${unrealized_pnl}")
        print(f"  Total P&L: ${realized_pnl + unrealized_pnl}")
        
        print("\n=== WHAT SHOULD THE CALCULATION BE? ===")
        print("Based on the positions:")
        print("1. $47 calls: 8 opened (BTO), 2 closed (STC) = 6 still open")
        print("   - Round trip: (2 × $21.925 credit) + (2 × -$18.37 debit) = $4385 + (-$3674) = $711")
        print("   - Still open: 6 × -$18.37 = -$11022 (unrealized)")
        print()
        print("2. $61 calls: 4 opened (STO), 1 closed (BTC) = 3 still open") 
        print("   - Round trip: (4 × $9.935 credit) + (1 × -$11.78 debit) = $3974 + (-$1178) = $2796")
        print("   - Still open: 3 × $9.935 = $2980.5 (unrealized)")
        print()
        print("Expected:")
        print(f"  Realized P&L: $711 + $2796 = $3507")
        print(f"  Unrealized P&L: -$11022 + $2980.5 = -$8041.5")
        print(f"  Total P&L: $3507 + (-$8041.5) = -$4534.5")
        print()
        print("But the system currently shows all P&L as realized because:")
        print("- It sees completed round trips for both strikes")
        print("- It doesn't account for the remaining open quantities")
        
        print("\n=== THE ISSUE ===")
        print("The P&L calculation logic has a flaw:")
        print("1. It groups by strike/expiration correctly")
        print("2. But it treats ANY opening + closing as a complete round trip")
        print("3. It doesn't consider that partial closing leaves remaining open positions")
        print("4. It should calculate P&L proportionally based on quantities")

if __name__ == "__main__":
    analyze_pnl_logic()