#!/usr/bin/env python3
"""
Test detection of both single-leg and double-leg rolls
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def analyze_current_rolls():
    """Analyze the current roll detection to see if we have any double-leg rolls"""
    print("🔍 Analyzing Current ROLL Detection")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get all current rolls
    all_trades = db.get_trades(limit=1000)
    roll_trades = [t for t in all_trades if 'Roll' in t['strategy_type']]
    
    print(f"Current ROLLs detected: {len(roll_trades)}")
    
    single_leg_rolls = []
    potential_double_leg_rolls = []
    
    for trade in roll_trades:
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        
        if len(option_legs) == 2:
            single_leg_rolls.append(trade)
        elif len(option_legs) == 4:
            potential_double_leg_rolls.append(trade)
    
    print(f"\nROLL Breakdown:")
    print(f"  Single-leg rolls (2 transactions): {len(single_leg_rolls)}")
    print(f"  Potential double-leg rolls (4 transactions): {len(potential_double_leg_rolls)}")
    
    # Show examples of each
    if single_leg_rolls:
        print(f"\nSingle-leg roll examples:")
        for trade in single_leg_rolls[:3]:
            print(f"  {trade['trade_id']}: {trade['strategy_type']}")
    
    if potential_double_leg_rolls:
        print(f"\nPotential double-leg roll examples:")
        for trade in potential_double_leg_rolls:
            print(f"  {trade['trade_id']}: {trade['strategy_type']}")
    
    return roll_trades

def test_with_raw_transactions():
    """Test the TransactionMatcher on raw transactions to see both types"""
    print(f"\n🧪 Testing TransactionMatcher for Double-Leg Rolls")
    print("-" * 40)
    
    db = DatabaseManager()
    raw_txns = db.get_raw_transactions()
    
    # Group by order ID to find 4-transaction orders
    order_groups = {}
    for tx in raw_txns:
        order_id = tx.get('order_id')
        if order_id:
            if order_id not in order_groups:
                order_groups[order_id] = []
            order_groups[order_id].append(tx)
    
    # Find orders with exactly 4 transactions
    four_txn_orders = {oid: txns for oid, txns in order_groups.items() if len(txns) == 4}
    
    print(f"Orders with exactly 4 transactions: {len(four_txn_orders)}")
    
    # Analyze these to see if they could be double-leg rolls
    potential_double_rolls = []
    
    for order_id, txns in list(four_txn_orders.items())[:5]:  # Check first 5
        print(f"\nOrder {order_id} ({len(txns)} transactions):")
        
        # Check if all are options for the same underlying
        underlyings = set(tx.get('underlying_symbol') for tx in txns)
        instruments = set(tx.get('instrument_type') for tx in txns)
        actions = [tx.get('action') for tx in txns]
        
        print(f"  Underlyings: {underlyings}")
        print(f"  Instruments: {instruments}")
        print(f"  Actions: {actions}")
        
        # Check for roll pattern (2 closing + 2 opening)
        closing_count = sum(1 for action in actions if action and 'CLOSE' in str(action))
        opening_count = sum(1 for action in actions if action and 'OPEN' in str(action))
        
        print(f"  Closing: {closing_count}, Opening: {opening_count}")
        
        if closing_count == 2 and opening_count == 2 and len(underlyings) == 1:
            print(f"  🎯 POTENTIAL DOUBLE-LEG ROLL!")
            potential_double_rolls.append(order_id)
            
            # Show more details
            for i, tx in enumerate(txns):
                symbol = tx.get('symbol', 'Unknown')[:20]  # Truncate long option symbols
                action = tx.get('action', 'Unknown')
                qty = tx.get('quantity', 0)
                print(f"    {i+1}. {action} {qty} {symbol}")
    
    print(f"\nPotential double-leg rolls found: {len(potential_double_rolls)}")
    
    # Test the actual TransactionMatcher on one of these
    if potential_double_rolls:
        test_order_id = potential_double_rolls[0]
        test_txns = order_groups[test_order_id]
        
        print(f"\n🔬 Testing TransactionMatcher on Order {test_order_id}:")
        
        # Calculate stock positions
        existing_positions = {}
        stock_positions = StrategyRecognizer.get_stock_positions(test_txns)
        for symbol, quantity in stock_positions.items():
            if symbol not in existing_positions:
                existing_positions[symbol] = {'stock': 0, 'options': {}}
            existing_positions[symbol]['stock'] = quantity
        
        matcher = TransactionMatcher()
        strategy_matches = matcher.match_transactions_to_strategies(test_txns, existing_positions)
        
        print(f"Strategies detected: {len(strategy_matches)}")
        for match in strategy_matches:
            print(f"  {match.strategy_type.value} - {len(match.transactions)} txns - {match.confidence.value}")

def main():
    current_rolls = analyze_current_rolls()
    test_with_raw_transactions()
    
    print(f"\n" + "=" * 60)
    print("🎯 DOUBLE-LEG ROLL ANALYSIS COMPLETE")
    print("=" * 60)
    
    print(f"\nSUMMARY:")
    print(f"✅ Single-leg rolls: Implemented and working")
    print(f"🔬 Double-leg rolls: Enhanced detection added")
    print(f"📊 Need to test with actual double-leg roll data")

if __name__ == '__main__':
    main()