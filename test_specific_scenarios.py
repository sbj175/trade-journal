#!/usr/bin/env python3
"""
Test specific scenarios and edge cases for the order-based system
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer
import json
from datetime import datetime

def test_order_id_grouping():
    """Test how well order IDs are grouping related transactions"""
    print("🔍 TEST: Order ID Grouping Quality")
    print("-" * 40)
    
    db = DatabaseManager()
    raw_txns = db.get_raw_transactions()
    
    # Group transactions by order ID
    order_groups = {}
    no_order_id = []
    
    for tx in raw_txns:
        order_id = tx.get('order_id')
        if order_id:
            if order_id not in order_groups:
                order_groups[order_id] = []
            order_groups[order_id].append(tx)
        else:
            no_order_id.append(tx)
    
    print(f"Order groups: {len(order_groups)}")
    print(f"Transactions without order ID: {len(no_order_id)}")
    
    # Analyze group sizes
    group_sizes = [len(txns) for txns in order_groups.values()]
    from collections import Counter
    size_distribution = Counter(group_sizes)
    
    print(f"\nOrder group size distribution:")
    for size in sorted(size_distribution.keys()):
        count = size_distribution[size]
        print(f"  {size} transactions: {count} orders")
    
    # Show some sample groups
    print(f"\nSample order groups:")
    sample_orders = list(order_groups.items())[:5]
    for order_id, txns in sample_orders:
        symbols = set(tx.get('underlying_symbol') for tx in txns)
        actions = [tx.get('action') for tx in txns]
        print(f"  Order {order_id}: {len(txns)} txns, symbols: {symbols}, actions: {actions}")

def test_diagonal_vs_roll_detection():
    """Deep dive into diagonal spreads to identify potential rolls"""
    print("\n🔄 TEST: Diagonal Spread vs ROLL Analysis")
    print("-" * 40)
    
    db = DatabaseManager()
    diagonal_trades = db.get_trades(strategy='Diagonal Spread', limit=20)
    
    print(f"Analyzing {len(diagonal_trades)} diagonal spreads...")
    
    for trade in diagonal_trades:
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        
        if len(option_legs) == 2:
            leg1, leg2 = option_legs
            
            print(f"\n{trade['trade_id']}:")
            print(f"  Leg 1: {leg1['option_type']} ${leg1['strike']} {leg1['expiration']} x{leg1['quantity']}")
            print(f"  Leg 2: {leg2['option_type']} ${leg2['strike']} {leg2['expiration']} x{leg2['quantity']}")
            
            # Check for roll pattern
            is_same_type = leg1['option_type'] == leg2['option_type']
            different_exp = leg1['expiration'] != leg2['expiration']
            opposite_quantities = (leg1['quantity'] > 0) != (leg2['quantity'] > 0)
            
            roll_indicators = []
            if is_same_type: roll_indicators.append("same_type")
            if different_exp: roll_indicators.append("diff_exp")
            if opposite_quantities: roll_indicators.append("opp_qty")
            
            print(f"  Roll indicators: {roll_indicators}")
            
            # Check transaction actions
            try:
                actions1 = leg1.get('transaction_actions', '[]')
                actions2 = leg2.get('transaction_actions', '[]')
                
                if isinstance(actions1, str):
                    actions1 = json.loads(actions1)
                if isinstance(actions2, str):
                    actions2 = json.loads(actions2)
                
                all_actions = actions1 + actions2
                print(f"  Actions: {all_actions}")
                
                has_btc = any('BUY' in str(action) and 'CLOSE' in str(action) for action in all_actions)
                has_sto = any('SELL' in str(action) and 'OPEN' in str(action) for action in all_actions)
                
                if has_btc and has_sto:
                    print(f"  🔄 POTENTIAL ROLL: BTC + STO detected")
            except Exception as e:
                print(f"  ⚠️  Could not parse actions: {e}")

def test_timing_vs_order_grouping():
    """Compare what timing-based vs order-based grouping would create"""
    print("\n⏰ TEST: Timing vs Order-Based Grouping Comparison")
    print("-" * 40)
    
    db = DatabaseManager()
    
    # Pick a busy trading day
    raw_txns = db.get_raw_transactions()
    
    # Group by date
    date_groups = {}
    for tx in raw_txns:
        executed_at = tx.get('executed_at', '')
        if executed_at:
            date = executed_at[:10]  # YYYY-MM-DD
            if date not in date_groups:
                date_groups[date] = []
            date_groups[date].append(tx)
    
    # Find busiest day
    busiest_date = max(date_groups.keys(), key=lambda d: len(date_groups[d]))
    busy_day_txns = date_groups[busiest_date]
    
    print(f"Busiest trading day: {busiest_date} ({len(busy_day_txns)} transactions)")
    
    # Show how order-based grouping handles this day
    order_groups_that_day = {}
    timing_groups_that_day = {}
    
    for tx in busy_day_txns:
        order_id = tx.get('order_id')
        if order_id:
            if order_id not in order_groups_that_day:
                order_groups_that_day[order_id] = []
            order_groups_that_day[order_id].append(tx)
        
        # Simulate timing-based grouping (same symbol + within 1 hour)
        symbol = tx.get('underlying_symbol')
        executed_at = tx.get('executed_at', '')
        timing_key = f"{symbol}_{executed_at[:13]}"  # Hour precision
        
        if timing_key not in timing_groups_that_day:
            timing_groups_that_day[timing_key] = []
        timing_groups_that_day[timing_key].append(tx)
    
    print(f"\nOrder-based grouping: {len(order_groups_that_day)} groups")
    print(f"Timing-based grouping: {len(timing_groups_that_day)} groups")
    
    # Show potential over-grouping by timing
    timing_over_groups = [g for g in timing_groups_that_day.values() if len(g) > 4]
    print(f"Timing groups with >4 transactions: {len(timing_over_groups)}")
    
    if timing_over_groups:
        worst_timing_group = max(timing_over_groups, key=len)
        print(f"Worst timing group: {len(worst_timing_group)} transactions")
        print(f"  Actions: {[tx.get('action') for tx in worst_timing_group]}")

def test_edge_cases():
    """Test edge cases and unusual scenarios"""
    print("\n🔬 TEST: Edge Cases and Unusual Scenarios")
    print("-" * 40)
    
    db = DatabaseManager()
    all_trades = db.get_trades(limit=1000)
    
    # Find unusual patterns
    edge_cases = {
        'single_legs': [],
        'many_legs': [],
        'complex_strategies': [],
        'mixed_expirations': [],
    }
    
    for trade in all_trades:
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        stock_legs = trade_details.get('stock_legs', [])
        
        total_legs = len(option_legs) + len(stock_legs)
        
        if total_legs == 1:
            edge_cases['single_legs'].append(trade['trade_id'])
        elif total_legs > 4:
            edge_cases['many_legs'].append(trade['trade_id'])
        
        if trade['strategy_type'] == 'Complex Strategy':
            edge_cases['complex_strategies'].append(trade['trade_id'])
        
        # Check for mixed expirations
        if len(option_legs) > 1:
            expirations = set(leg['expiration'] for leg in option_legs)
            if len(expirations) > 1:
                edge_cases['mixed_expirations'].append(trade['trade_id'])
    
    print(f"Edge case analysis:")
    for case_type, trades in edge_cases.items():
        print(f"  {case_type}: {len(trades)} trades")
        if trades:
            print(f"    Examples: {trades[:3]}")

if __name__ == '__main__':
    test_order_id_grouping()
    test_diagonal_vs_roll_detection()
    test_timing_vs_order_grouping()
    test_edge_cases()
    
    print(f"\n" + "=" * 60)
    print("🎯 DETAILED TESTING COMPLETE")
    print("=" * 60)