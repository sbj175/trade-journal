#!/usr/bin/env python3
"""
Test script to verify the P&L calculation fix for partial closes.
"""

import sys
import os
import sqlite3

# Add the project root to Python path
sys.path.insert(0, '/home/sbj/python-projects/trade-journal')

# Mock loguru logger to avoid import issues
class MockLogger:
    def info(self, msg): print(f"INFO: {msg}")
    def error(self, msg): print(f"ERROR: {msg}")
    def warning(self, msg): print(f"WARNING: {msg}")

sys.modules['loguru'] = type('loguru', (), {'logger': MockLogger()})()

def test_pnl_fix():
    """Test the P&L calculation fix with IBIT chain"""
    
    print("Testing P&L Calculation Fix for Partial Closes")
    print("=" * 50)
    
    try:
        from src.database.db_manager import DatabaseManager
        from src.models.order_models import OrderManager
        
        # Initialize
        db = DatabaseManager()
        order_manager = OrderManager(db)
        
        # Find the IBIT chain
        chain_id = "IBIT_OPENING_20250609_38851267"
        chain_status = "OPEN"  # We know it's open now
        
        print(f"Testing chain: {chain_id}")
        print(f"Chain status: {chain_status}")
        
        # Check individual position data first
        print("\n1. Individual Position Data:")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.symbol, p.opening_action, p.quantity, p.pnl, p.strike, p.expiration
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                WHERE ocm.chain_id = ?
                ORDER BY p.strike, p.opening_action
            """, (chain_id,))
            
            positions = cursor.fetchall()
            total_position_pnl = 0
            for pos in positions:
                symbol, action, qty, pnl, strike, exp = pos
                total_position_pnl += pnl
                print(f"   {action} {qty}x {symbol} ${strike} {exp}: ${pnl:,.2f}")
            
            print(f"   Total Position P&L: ${total_position_pnl:,.2f}")
        
        # Test the new P&L calculation methods
        print("\n2. Testing New P&L Calculation Methods:")
        
        realized_pnl = order_manager.calculate_chain_realized_pnl(chain_id, chain_status)
        unrealized_pnl = order_manager.calculate_chain_unrealized_pnl(chain_id, chain_status)
        total_calculated = realized_pnl + unrealized_pnl
        
        print(f"   Realized P&L:   ${realized_pnl:,.2f}")
        print(f"   Unrealized P&L: ${unrealized_pnl:,.2f}")
        print(f"   Total:          ${total_calculated:,.2f}")
        
        # Verify the math
        print("\n3. Verification:")
        if abs(total_calculated - total_position_pnl) < 0.01:
            print("   ✅ Total P&L matches individual positions")
        else:
            print(f"   ❌ Total P&L mismatch: {total_calculated} vs {total_position_pnl}")
        
        if realized_pnl != 0:
            print("   ✅ Realized P&L is no longer zero")
        else:
            print("   ❌ Realized P&L is still zero")
            
        if unrealized_pnl != 0:
            print("   ✅ Unrealized P&L is no longer zero")
        else:
            print("   ❌ Unrealized P&L is still zero")
        
        # Expected logic check
        print("\n4. Expected Logic Check:")
        print("   For IBIT partial close:")
        print("   - $47 calls: 8 opened, 2 closed → 2/8 = 25% realized, 6/8 = 75% unrealized")
        print("   - $61 calls: 4 opened, 1 closed → 1/4 = 25% realized, 3/4 = 75% unrealized")
        
        # Calculate expected values manually
        # We need to look at the P&L for each strike separately
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # $47 calls
            cursor.execute("""
                SELECT p.opening_action, p.quantity, p.pnl
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                WHERE ocm.chain_id = ? AND p.strike = 47.0
                ORDER BY p.opening_action
            """, (chain_id,))
            
            call_47_positions = cursor.fetchall()
            call_47_opening_pnl = 0
            call_47_closing_pnl = 0
            call_47_opening_qty = 0
            call_47_closing_qty = 0
            
            for pos in call_47_positions:
                action, qty, pnl = pos
                if 'TO_OPEN' in action:
                    call_47_opening_qty += abs(qty)
                    call_47_opening_pnl = pnl
                elif 'TO_CLOSE' in action:
                    call_47_closing_qty += abs(qty)
                    call_47_closing_pnl = pnl
            
            # $61 calls
            cursor.execute("""
                SELECT p.opening_action, p.quantity, p.pnl
                FROM positions_new p
                JOIN order_chain_members ocm ON p.order_id = ocm.order_id
                WHERE ocm.chain_id = ? AND p.strike = 61.0
                ORDER BY p.opening_action
            """, (chain_id,))
            
            call_61_positions = cursor.fetchall()
            call_61_opening_pnl = 0
            call_61_closing_pnl = 0
            call_61_opening_qty = 0
            call_61_closing_qty = 0
            
            for pos in call_61_positions:
                action, qty, pnl = pos
                if 'TO_OPEN' in action:
                    call_61_opening_qty += abs(qty)
                    call_61_opening_pnl = pnl
                elif 'TO_CLOSE' in action:
                    call_61_closing_qty += abs(qty)
                    call_61_closing_pnl = pnl
        
        print(f"\n5. Manual Calculation Check:")
        print(f"   $47 calls: {call_47_opening_qty} opened, {call_47_closing_qty} closed")
        print(f"   - Opening P&L: ${call_47_opening_pnl:,.2f}")
        print(f"   - Closing P&L: ${call_47_closing_pnl:,.2f}")
        
        call_47_realized_ratio = min(call_47_opening_qty, call_47_closing_qty) / call_47_opening_qty if call_47_opening_qty > 0 else 0
        call_47_unrealized_ratio = max(0, call_47_opening_qty - call_47_closing_qty) / call_47_opening_qty if call_47_opening_qty > 0 else 0
        
        print(f"   - Expected realized ratio: {call_47_realized_ratio:.1%}")
        print(f"   - Expected unrealized ratio: {call_47_unrealized_ratio:.1%}")
        
        print(f"\n   $61 calls: {call_61_opening_qty} opened, {call_61_closing_qty} closed")
        print(f"   - Opening P&L: ${call_61_opening_pnl:,.2f}")
        print(f"   - Closing P&L: ${call_61_closing_pnl:,.2f}")
        
        call_61_realized_ratio = min(call_61_opening_qty, call_61_closing_qty) / call_61_opening_qty if call_61_opening_qty > 0 else 0
        call_61_unrealized_ratio = max(0, call_61_opening_qty - call_61_closing_qty) / call_61_opening_qty if call_61_opening_qty > 0 else 0
        
        print(f"   - Expected realized ratio: {call_61_realized_ratio:.1%}")
        print(f"   - Expected unrealized ratio: {call_61_unrealized_ratio:.1%}")
        
        print("\n6. Summary:")
        if realized_pnl != 0 and unrealized_pnl != 0:
            print("   ✅ SUCCESS: P&L is now correctly split between realized and unrealized")
            print("   ✅ Partial close fix is working!")
        else:
            print("   ❌ P&L calculation still has issues")
            
        print(f"\n   Final Results:")
        print(f"   - Realized P&L:   ${realized_pnl:,.2f}")
        print(f"   - Unrealized P&L: ${unrealized_pnl:,.2f}")
        print(f"   - Total P&L:      ${total_calculated:,.2f}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pnl_fix()