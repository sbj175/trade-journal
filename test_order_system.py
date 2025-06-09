#!/usr/bin/env python3
"""
Comprehensive testing of the order-based transaction matching system
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer
from collections import defaultdict
import json

def main():
    db = DatabaseManager()
    
    print("🧪 Comprehensive Testing of Order-Based System")
    print("=" * 60)
    
    # Test 1: Overall Statistics
    print("\n📊 TEST 1: Overall Database Statistics")
    print("-" * 40)
    
    all_trades = db.get_trades(limit=1000)
    raw_txns = db.get_raw_transactions()
    
    print(f"Total trades: {len(all_trades)}")
    print(f"Total raw transactions: {len(raw_txns)}")
    print(f"Avg transactions per trade: {len(raw_txns) / len(all_trades):.1f}")
    
    # Test 2: Strategy Distribution
    print("\n📈 TEST 2: Strategy Distribution Analysis")
    print("-" * 40)
    
    strategy_counts = defaultdict(int)
    leg_distribution = defaultdict(int)
    confidence_info = defaultdict(list)
    
    for trade in all_trades:
        strategy = trade['strategy_type']
        strategy_counts[strategy] += 1
        
        # Extract leg count from trade_id
        if 'legs' in trade['trade_id']:
            try:
                leg_count = int(trade['trade_id'].split('_')[2].replace('legs', ''))
                leg_distribution[leg_count] += 1
            except:
                pass
        
        # Extract confidence from notes
        notes = trade.get('original_notes', '')
        if 'Confidence:' in notes:
            conf = notes.split('Confidence: ')[1].split(',')[0].strip()
            confidence_info[strategy].append(conf)
    
    print("Strategy breakdown:")
    for strategy, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
        avg_conf = "N/A"
        if confidence_info[strategy]:
            high_count = confidence_info[strategy].count('HIGH')
            med_count = confidence_info[strategy].count('MEDIUM')
            low_count = confidence_info[strategy].count('LOW')
            avg_conf = f"H:{high_count} M:{med_count} L:{low_count}"
        print(f"  {strategy}: {count} trades ({avg_conf})")
    
    print(f"\nLeg count distribution:")
    for leg_count in sorted(leg_distribution.keys()):
        count = leg_distribution[leg_count]
        print(f"  {leg_count} legs: {count} trades")
    
    # Test 3: Problem Trade Detection
    print("\n⚠️  TEST 3: Problem Trade Detection")
    print("-" * 40)
    
    problem_trades = []
    suspicious_trades = []
    
    for trade in all_trades:
        if 'legs' in trade['trade_id']:
            try:
                leg_count = int(trade['trade_id'].split('_')[2].replace('legs', ''))
                if leg_count > 10:
                    problem_trades.append((trade['trade_id'], trade['strategy_type'], leg_count))
                elif leg_count > 5:
                    suspicious_trades.append((trade['trade_id'], trade['strategy_type'], leg_count))
            except:
                pass
    
    if problem_trades:
        print(f"❌ {len(problem_trades)} problematic trades (>10 legs):")
        for trade_id, strategy, leg_count in sorted(problem_trades, key=lambda x: x[2], reverse=True)[:5]:
            print(f"  {trade_id}: {strategy} ({leg_count} legs)")
    else:
        print("✅ No problematic trades found (>10 legs)")
    
    if suspicious_trades:
        print(f"\n⚠️  {len(suspicious_trades)} suspicious trades (6-10 legs):")
        for trade_id, strategy, leg_count in sorted(suspicious_trades, key=lambda x: x[2], reverse=True)[:5]:
            print(f"  {trade_id}: {strategy} ({leg_count} legs)")
    else:
        print("✅ No suspicious trades found (6-10 legs)")
    
    # Test 4: Order ID Coverage
    print("\n🔍 TEST 4: Order ID Coverage Analysis")
    print("-" * 40)
    
    txns_with_order_id = [tx for tx in raw_txns if tx.get('order_id')]
    txns_without_order_id = [tx for tx in raw_txns if not tx.get('order_id')]
    
    print(f"Transactions with order_id: {len(txns_with_order_id)} ({len(txns_with_order_id)/len(raw_txns)*100:.1f}%)")
    print(f"Transactions without order_id: {len(txns_without_order_id)} ({len(txns_without_order_id)/len(raw_txns)*100:.1f}%)")
    
    # Count unique order IDs
    unique_order_ids = set(tx['order_id'] for tx in txns_with_order_id if tx.get('order_id'))
    print(f"Unique order IDs: {len(unique_order_ids)}")
    print(f"Avg transactions per order: {len(txns_with_order_id) / len(unique_order_ids):.1f}")
    
    # Test 5: Specific Symbol Deep Dive
    print("\n🎯 TEST 5: Symbol-Specific Analysis")
    print("-" * 40)
    
    # Get top 5 most active symbols
    symbol_counts = defaultdict(int)
    for trade in all_trades:
        symbol_counts[trade['underlying']] += 1
    
    top_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    for symbol, count in top_symbols:
        print(f"\n{symbol} ({count} trades):")
        symbol_trades = db.get_trades(underlying=symbol, limit=100)
        
        # Strategy breakdown for this symbol
        symbol_strategies = defaultdict(int)
        for trade in symbol_trades:
            symbol_strategies[trade['strategy_type']] += 1
        
        for strategy, strategy_count in sorted(symbol_strategies.items(), key=lambda x: x[1], reverse=True):
            print(f"  {strategy}: {strategy_count}")
    
    # Test 6: Sample Trade Details
    print("\n📋 TEST 6: Sample Trade Details")
    print("-" * 40)
    
    # Show details for a few different strategy types
    sample_strategies = ['Diagonal Spread', 'Iron Condor', 'Vertical Spread', 'Naked Call']
    
    for strategy_type in sample_strategies:
        matching_trades = [t for t in all_trades if t['strategy_type'] == strategy_type]
        if matching_trades:
            trade = matching_trades[0]
            trade_details = db.get_trade_details(trade['trade_id'])
            
            print(f"\nSample {strategy_type}: {trade['trade_id']}")
            print(f"  Status: {trade['status']}, Entry: {trade['entry_date']}")
            print(f"  Option legs: {len(trade_details.get('option_legs', []))}")
            print(f"  Stock legs: {len(trade_details.get('stock_legs', []))}")
            
            if trade.get('original_notes'):
                print(f"  Notes: {trade['original_notes']}")
    
    # Test 7: Potential ROLL Detection
    print("\n🔄 TEST 7: Potential ROLL Analysis")
    print("-" * 40)
    
    diagonal_trades = [t for t in all_trades if t['strategy_type'] == 'Diagonal Spread']
    potential_rolls = []
    
    for trade in diagonal_trades[:10]:  # Check first 10 diagonal spreads
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        
        if len(option_legs) == 2:
            leg1, leg2 = option_legs
            
            # Look for BTC + STO pattern
            actions1 = leg1.get('transaction_actions', [])
            actions2 = leg2.get('transaction_actions', [])
            
            if actions1 and actions2:
                try:
                    actions1 = json.loads(actions1) if isinstance(actions1, str) else actions1
                    actions2 = json.loads(actions2) if isinstance(actions2, str) else actions2
                    
                    has_btc = any('BUY' in str(action) and 'CLOSE' in str(action) for action in actions1 + actions2)
                    has_sto = any('SELL' in str(action) and 'OPEN' in str(action) for action in actions1 + actions2)
                    
                    if has_btc and has_sto:
                        potential_rolls.append(trade['trade_id'])
                except:
                    pass
    
    print(f"Diagonal Spreads analyzed: {min(10, len(diagonal_trades))}")
    print(f"Potential ROLLs detected: {len(potential_rolls)}")
    
    if potential_rolls:
        print("Sample potential ROLLs:")
        for roll_id in potential_rolls[:3]:
            print(f"  {roll_id}")
    
    print(f"\n" + "=" * 60)
    print("🎯 TESTING SUMMARY")
    print("=" * 60)
    print(f"✅ Total trades processed: {len(all_trades)}")
    print(f"✅ Problem trades (>10 legs): {len(problem_trades)}")
    print(f"✅ Order ID coverage: {len(txns_with_order_id)/len(raw_txns)*100:.1f}%")
    print(f"✅ Avg legs per trade: {sum(leg_distribution[k] * k for k in leg_distribution) / len(all_trades):.1f}")
    print(f"✅ Potential ROLLs identified: {len(potential_rolls)}")

if __name__ == '__main__':
    main()