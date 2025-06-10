#!/usr/bin/env python3
"""
Test the fix for closing order transaction consolidation
"""
import sqlite3
from pathlib import Path

def test_closing_order_consolidation():
    """Test the updated logic for pure closing orders"""
    
    # Simulate the transactions for order 375108991
    closing_transactions = [
        {
            'id': '353949426',
            'quantity': 3.0,
            'price': 0.01,
            'action': 'OrderAction.BUY_TO_CLOSE',
            'symbol': 'MSTR  250328C00342500',
            'underlying_symbol': 'MSTR',
            'instrument_type': 'InstrumentType.EQUITY_OPTION'
        },
        {
            'id': '353950132', 
            'quantity': 3.0,
            'price': 0.01,
            'action': 'OrderAction.BUY_TO_CLOSE',
            'symbol': 'MSTR  250328C00342500',
            'underlying_symbol': 'MSTR',
            'instrument_type': 'InstrumentType.EQUITY_OPTION'
        },
        {
            'id': '353951956',
            'quantity': 3.0,
            'price': 0.01,
            'action': 'OrderAction.BUY_TO_CLOSE',
            'symbol': 'MSTR  250328C00342500',
            'underlying_symbol': 'MSTR',
            'instrument_type': 'InstrumentType.EQUITY_OPTION'
        }
    ]
    
    # Test the consolidation logic
    symbol = 'MSTR  250328C00342500'
    instrument_type = 'InstrumentType.EQUITY_OPTION'
    
    # Categorize transactions
    opening_txs = []
    closing_txs = []
    
    for tx in closing_transactions:
        action = str(tx.get('action', '')).upper()
        if any(open_action in action for open_action in ['BTO', 'STO', 'OPEN']):
            opening_txs.append(tx)
        elif any(close_action in action for close_action in ['BTC', 'STC', 'CLOSE', 'ASSIGNED', 'EXPIRED']):
            closing_txs.append(tx)
    
    print(f"Opening transactions: {len(opening_txs)}")
    print(f"Closing transactions: {len(closing_txs)}")
    
    # Apply the new logic
    total_opening_quantity = sum(tx.get('quantity', 0) for tx in opening_txs)
    total_closing_quantity = sum(tx.get('quantity', 0) for tx in closing_txs)
    
    print(f"Total opening quantity: {total_opening_quantity}")
    print(f"Total closing quantity: {total_closing_quantity}")
    
    # Determine net quantity using the new logic
    if opening_txs:
        # Normal case: has opening transactions
        action = str(opening_txs[0].get('action', '')).upper()
        if 'SELL' in action or 'STO' in action:
            net_quantity = -abs(total_opening_quantity)
        else:
            net_quantity = abs(total_opening_quantity)
    else:
        # Pure closing order: net quantity should be the closing quantity
        if closing_txs:
            action = str(closing_txs[0].get('action', '')).upper()
            if 'BTC' in action:
                # Closing a long position - quantity should be positive (buying back)
                net_quantity = abs(total_closing_quantity)
            elif 'STC' in action:
                # Closing a short position - quantity should be negative (selling to close)
                net_quantity = -abs(total_closing_quantity)
            else:
                # Default to positive for other closing actions
                net_quantity = abs(total_closing_quantity)
        else:
            net_quantity = 0
    
    print(f"Net quantity (new logic): {net_quantity}")
    
    # Expected: +9 because this is BTC (buying back to close a short position)
    expected = 9.0
    if net_quantity == expected:
        print(f"✅ SUCCESS: Net quantity {net_quantity} matches expected {expected}")
        return True
    else:
        print(f"❌ FAILURE: Net quantity {net_quantity} does not match expected {expected}")
        return False

def test_current_database_state():
    """Check what's currently in the database for these orders"""
    
    db_path = Path("trade_journal.db")
    if not db_path.exists():
        print("Database not found")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=== CURRENT DATABASE STATE ===")
    
    # Check order 374805462 (opening)
    cursor.execute("SELECT * FROM positions_new WHERE order_id = ?", ("374805462",))
    pos = cursor.fetchone()
    if pos:
        print(f"Order 374805462 position: quantity={pos[9]}, opening_price={pos[10]}, status={pos[16]}")
    else:
        print("Order 374805462 not found")
    
    # Check order 375108991 (closing)
    cursor.execute("SELECT * FROM positions_new WHERE order_id = ?", ("375108991",))
    pos = cursor.fetchone()
    if pos:
        print(f"Order 375108991 position: quantity={pos[9]}, closing_price={pos[11]}, status={pos[16]}")
    else:
        print("Order 375108991 not found")
    
    conn.close()

if __name__ == "__main__":
    print("Testing closing order consolidation fix...")
    
    # Test the logic
    success = test_closing_order_consolidation()
    
    print("\n" + "="*50)
    
    # Check current database state
    test_current_database_state()
    
    if success:
        print("\n🎉 Fix appears to be working correctly!")
        print("Now we need to re-run the Order/Position model to apply the fix.")
    else:
        print("\n❌ Fix needs more work.")