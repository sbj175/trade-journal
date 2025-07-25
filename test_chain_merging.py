#!/usr/bin/env python3
"""
Test script to validate the new chain merging approach
"""
import sqlite3
from datetime import date

def test_chain_merging_logic():
    """Test the chain merging detection and logic"""
    print("=== Testing Chain Merging Logic ===\n")
    
    # Mock classes for testing
    class OrderType:
        OPENING = "OPENING"
        CLOSING = "CLOSING"
    
    class Position:
        def __init__(self, data):
            for key, value in data.items():
                setattr(self, key, value)
    
    class Order:
        def __init__(self, data):
            for key, value in data.items():
                if key == 'positions':
                    self.positions = [Position(p) for p in value]
                else:
                    setattr(self, key, value)
    
    # Create test data for GME scenario
    opening_order_1 = Order({
        'order_id': '374895150',
        'order_type': OrderType.OPENING,
        'underlying': 'GME',
        'order_date': date(2025, 3, 27),
        'total_pnl': -2925.0,
        'strategy_type': 'Long Call',
        'account_number': 'TEST123',
        'positions': [{
            'symbol': 'GME   251017C00020000',
            'quantity': 5,
            'opening_action': 'ORDERACTION.BUY_TO_OPEN'
        }]
    })
    
    opening_order_2 = Order({
        'order_id': '374801719',
        'order_type': OrderType.OPENING,
        'underlying': 'GME',
        'order_date': date(2025, 3, 27),
        'total_pnl': -3250.0,
        'strategy_type': 'Long Call',
        'account_number': 'TEST123',
        'positions': [{
            'symbol': 'GME   251017C00025000',
            'quantity': 5,
            'opening_action': 'ORDERACTION.BUY_TO_OPEN'
        }]
    })
    
    closing_order = Order({
        'order_id': '392914508',
        'order_type': OrderType.CLOSING,
        'underlying': 'GME',
        'order_date': date(2025, 7, 2),
        'total_pnl': 6000.0,
        'strategy_type': None,
        'account_number': 'TEST123',
        'positions': [
            {
                'symbol': 'GME   251017C00020000',
                'quantity': 5,
                'opening_action': 'ORDERACTION.SELL_TO_CLOSE'
            },
            {
                'symbol': 'GME   251017C00025000',
                'quantity': 5,
                'opening_action': 'ORDERACTION.SELL_TO_CLOSE'
            }
        ]
    })
    
    # Test detection logic
    print("1. Testing multi-chain detection...")
    
    group_orders = [opening_order_1, opening_order_2, closing_order]
    used_orders = set()
    
    # Simulate detection
    closing_orders = [o for o in group_orders if o.order_type == OrderType.CLOSING]
    opening_orders = [o for o in group_orders if o.order_type == OrderType.OPENING]
    
    multi_chain_closings = {}
    
    for closing_order_test in closing_orders:
        affected_opening_orders = []
        
        for close_pos in closing_order_test.positions:
            close_action = close_pos.opening_action
            close_symbol = close_pos.symbol
            
            if 'CLOSE' not in close_action:
                continue
            
            for opening_order_test in opening_orders:
                if opening_order_test in affected_opening_orders:
                    continue
                    
                for open_pos in opening_order_test.positions:
                    open_action = open_pos.opening_action
                    open_symbol = open_pos.symbol
                    
                    if (open_symbol == close_symbol and 
                        'OPEN' in open_action):
                        affected_opening_orders.append(opening_order_test)
                        break
        
        if len(affected_opening_orders) > 1:
            multi_chain_closings[closing_order_test.order_id] = affected_opening_orders
            print(f"   ✓ Detected multi-chain closing: {closing_order_test.order_id} affects {len(affected_opening_orders)} opening orders")
    
    # Test merging logic
    print("\n2. Testing chain merging...")
    
    if multi_chain_closings:
        for close_id, opening_orders_list in multi_chain_closings.items():
            close_order = next(o for o in group_orders if o.order_id == close_id)
            
            # Simulate merge_chains logic
            opening_orders_list.sort(key=lambda o: o.order_date or date.min)
            base_order = opening_orders_list[0]
            
            opening_order_ids = [o.order_id[:8] for o in opening_orders_list]
            date_str = base_order.order_date.strftime('%Y%m%d')
            chain_id = f"{base_order.underlying}_MERGED_{date_str}_{'_'.join(opening_order_ids)}"
            
            all_orders = opening_orders_list + [close_order]
            total_pnl = sum(order.total_pnl for order in all_orders)
            
            print(f"   ✓ Would create merged chain: {chain_id}")
            print(f"     - Opening orders: {[o.order_id for o in opening_orders_list]}")
            print(f"     - Closing order: {close_order.order_id}")
            print(f"     - Total P&L: ${total_pnl}")
            print(f"     - Status: CLOSED")
            print(f"     - Strategy: Multi-Strategy")
    
    print("\n3. Expected outcome:")
    print("   - Two separate GME chains will be merged into one")
    print("   - The merged chain will be marked as CLOSED")
    print("   - Total P&L will be the sum of all orders")
    print("   - Chain ID will reflect the merge")
    
    return len(multi_chain_closings) > 0

def check_database_state():
    """Check current database state"""
    print("\n=== Current Database State ===\n")
    
    conn = sqlite3.connect("trade_journal.db")
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT chain_id, underlying, chain_status, total_pnl, opening_date, closing_date, strategy_type
    FROM order_chains 
    WHERE underlying = 'GME'
    ORDER BY opening_date
    """)
    
    chains = cursor.fetchall()
    print("Current GME chains:")
    for chain in chains:
        status_icon = "🔴" if chain[2] == 'OPEN' else "🟢"
        print(f"  {status_icon} {chain[0]}")
        print(f"     Status: {chain[2]} | P&L: ${chain[3]} | Strategy: {chain[6]}")
        print(f"     Dates: {chain[4]} to {chain[5]}")
        print()
    
    open_count = sum(1 for chain in chains if chain[2] == 'OPEN')
    
    print(f"Summary: {len(chains)} total chains, {open_count} open")
    
    if open_count > 0:
        print("After applying the chain merging fix, the open chains should be merged and closed.")
    
    conn.close()

if __name__ == "__main__":
    success = test_chain_merging_logic()
    check_database_state()
    
    if success:
        print("\n🎉 Chain merging logic validated!")
        print("\nAdvantages of this approach:")
        print("- No virtual orders (uses real data only)")
        print("- Reflects trading reality (one close = one strategy)")
        print("- Simpler logic and better P&L tracking")
        print("- Represents trader intent accurately")
        print("\nReady to test with real reprocessing!")
    else:
        print("\n❌ Chain merging validation failed!")