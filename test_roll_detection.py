#!/usr/bin/env python3
"""
Test the new ROLL detection functionality
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def test_roll_detection():
    """Test ROLL detection on existing diagonal spreads"""
    print("🔄 Testing ROLL Detection")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get current diagonal spreads (should become rolls)
    current_diagonals = db.get_trades(strategy='Diagonal Spread', limit=50)
    print(f"Current Diagonal Spreads: {len(current_diagonals)}")
    
    # Test the new system on a subset of raw transactions
    # Focus on IBIT since we know those are rolls
    ibit_raw_txns = db.get_raw_transactions(underlying='IBIT')
    print(f"IBIT raw transactions: {len(ibit_raw_txns)}")
    
    # Calculate stock positions
    existing_positions = {}
    stock_positions = StrategyRecognizer.get_stock_positions(ibit_raw_txns)
    for symbol, quantity in stock_positions.items():
        if symbol not in existing_positions:
            existing_positions[symbol] = {'stock': 0, 'options': {}}
        existing_positions[symbol]['stock'] = quantity
    
    # Test with new TransactionMatcher (includes ROLL detection)
    matcher = TransactionMatcher()
    strategy_matches = matcher.match_transactions_to_strategies(ibit_raw_txns, existing_positions)
    
    print(f"\nNew system results for IBIT:")
    print(f"Total strategies identified: {len(strategy_matches)}")
    
    # Count by strategy type
    strategy_counts = {}
    roll_examples = []
    
    for match in strategy_matches:
        strategy = match.strategy_type.value
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        
        if 'Roll' in strategy:
            roll_examples.append(match)
    
    print(f"\nStrategy breakdown:")
    for strategy, count in sorted(strategy_counts.items()):
        print(f"  {strategy}: {count}")
    
    # Show details of detected rolls
    print(f"\nROLL Detection Details:")
    for i, roll in enumerate(roll_examples[:5]):  # Show first 5 rolls
        print(f"\n{i+1}. {roll.strategy_type.value} (Confidence: {roll.confidence.value})")
        print(f"   Transactions: {len(roll.transactions)}")
        
        # Show transaction details
        for j, tx in enumerate(roll.transactions):
            symbol = tx.get('symbol', 'Unknown')
            action = tx.get('action', 'Unknown')
            quantity = tx.get('quantity', 0)
            print(f"   Tx {j+1}: {action} {quantity} {symbol}")
    
    return strategy_matches

def compare_before_after():
    """Compare before/after ROLL detection"""
    print(f"\n📊 Before/After Comparison")
    print("-" * 40)
    
    db = DatabaseManager()
    
    # Before (current database)
    current_trades = db.get_trades(limit=1000)
    current_strategy_counts = {}
    for trade in current_trades:
        strategy = trade['strategy_type']
        current_strategy_counts[strategy] = current_strategy_counts.get(strategy, 0) + 1
    
    print(f"BEFORE (Current Database):")
    print(f"  Diagonal Spread: {current_strategy_counts.get('Diagonal Spread', 0)}")
    print(f"  Calendar Spread: {current_strategy_counts.get('Calendar Spread', 0)}")
    print(f"  Call Roll: {current_strategy_counts.get('Call Roll', 0)}")
    print(f"  Put Roll: {current_strategy_counts.get('Put Roll', 0)}")
    
    # After (if we re-process everything)
    raw_txns = db.get_raw_transactions()
    
    # Calculate all stock positions
    existing_positions = {}
    accounts = db.get_accounts()
    for account in accounts:
        account_number = account['account_number']
        account_txns = [tx for tx in raw_txns if tx.get('account_number') == account_number]
        stock_positions = StrategyRecognizer.get_stock_positions(account_txns)
        
        for symbol, quantity in stock_positions.items():
            if symbol not in existing_positions:
                existing_positions[symbol] = {'stock': 0, 'options': {}}
            existing_positions[symbol]['stock'] += quantity
    
    # Process with new ROLL detection
    matcher = TransactionMatcher()
    strategy_matches = matcher.match_transactions_to_strategies(raw_txns, existing_positions)
    
    new_strategy_counts = {}
    for match in strategy_matches:
        strategy = match.strategy_type.value
        new_strategy_counts[strategy] = new_strategy_counts.get(strategy, 0) + 1
    
    print(f"\nAFTER (With ROLL Detection):")
    print(f"  Diagonal Spread: {new_strategy_counts.get('Diagonal Spread', 0)}")
    print(f"  Calendar Spread: {new_strategy_counts.get('Calendar Spread', 0)}")
    print(f"  Call Roll: {new_strategy_counts.get('Call Roll', 0)}")
    print(f"  Put Roll: {new_strategy_counts.get('Put Roll', 0)}")
    
    # Calculate changes
    diagonal_change = new_strategy_counts.get('Diagonal Spread', 0) - current_strategy_counts.get('Diagonal Spread', 0)
    calendar_change = new_strategy_counts.get('Calendar Spread', 0) - current_strategy_counts.get('Calendar Spread', 0)
    call_roll_change = new_strategy_counts.get('Call Roll', 0) - current_strategy_counts.get('Call Roll', 0)
    put_roll_change = new_strategy_counts.get('Put Roll', 0) - current_strategy_counts.get('Put Roll', 0)
    
    print(f"\nCHANGES:")
    print(f"  Diagonal Spread: {diagonal_change:+d}")
    print(f"  Calendar Spread: {calendar_change:+d}")
    print(f"  Call Roll: {call_roll_change:+d}")
    print(f"  Put Roll: {put_roll_change:+d}")

if __name__ == '__main__':
    strategy_matches = test_roll_detection()
    compare_before_after()
    
    print(f"\n" + "=" * 60)
    print("🎯 ROLL DETECTION TESTING COMPLETE")
    print("=" * 60)