#!/usr/bin/env python3
"""
Investigate IBIT positions in positions_new table
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

def investigate_positions_new():
    """Investigate IBIT positions in positions_new"""
    
    db = DatabaseManager()
    db.ensure_initialized()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get IBIT positions for the chain orders
        print("=== IBIT POSITIONS IN positions_new FOR CHAIN ORDERS ===")
        cursor.execute("""
            SELECT p.* FROM positions_new p
            WHERE p.order_id IN ('388512672', '397401079')
            ORDER BY p.order_id, p.symbol, p.position_id
        """)
        positions = [dict(row) for row in cursor.fetchall()]
        
        total_pnl = 0
        for pos in positions:
            print(f"Position {pos['position_id']} (Order {pos['order_id']}):")
            print(f"  Symbol: {pos['symbol']}")
            print(f"  Underlying: {pos['underlying']}")
            print(f"  Instrument: {pos['instrument_type']}")
            print(f"  Strike: {pos['strike']} {pos['option_type']}")
            print(f"  Expiration: {pos['expiration']}")
            print(f"  Quantity: {pos['quantity']}")
            print(f"  Opening Price: {pos['opening_price']}")
            print(f"  Closing Price: {pos['closing_price']}")
            print(f"  Opening Action: {pos['opening_action']}")
            print(f"  Closing Action: {pos['closing_action']}")
            print(f"  Status: {pos['status']}")
            print(f"  P&L: {pos['pnl']}")
            print(f"  Opening Order: {pos['opening_order_id']}")
            print(f"  Closing Order: {pos['closing_order_id']}")
            
            if pos['pnl']:
                total_pnl += pos['pnl']
            print()
        
        print(f"Total P&L from positions_new: {total_pnl}")
        
        # Now test the actual P&L calculation methods
        print("\n=== TESTING P&L CALCULATION METHODS ===")
        from src.models.order_models import OrderManager
        
        order_manager = OrderManager(db)
        chain_id = 'IBIT_OPENING_20250609_38851267'
        chain_status = 'OPEN'
        
        realized_pnl = order_manager.calculate_chain_realized_pnl(chain_id, chain_status)
        unrealized_pnl = order_manager.calculate_chain_unrealized_pnl(chain_id, chain_status)
        
        print(f"Calculated realized P&L: {realized_pnl}")
        print(f"Calculated unrealized P&L: {unrealized_pnl}")
        print(f"Calculated total P&L: {realized_pnl + unrealized_pnl}")
        
        # Update the chain P&L
        print("\n=== UPDATING CHAIN P&L ===")
        new_total_pnl = order_manager.update_chain_pnl(chain_id)
        print(f"Updated chain P&L: {new_total_pnl}")
        
        # Check what's now in the database
        cursor.execute("""
            SELECT realized_pnl, unrealized_pnl, total_pnl
            FROM order_chains
            WHERE chain_id = ?
        """, (chain_id,))
        updated_chain = cursor.fetchone()
        if updated_chain:
            print(f"Chain table now shows:")
            print(f"  Realized P&L: {updated_chain[0]}")
            print(f"  Unrealized P&L: {updated_chain[1]}")
            print(f"  Total P&L: {updated_chain[2]}")

if __name__ == "__main__":
    investigate_positions_new()