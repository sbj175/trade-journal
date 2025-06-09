#!/usr/bin/env python3
"""
Debug stock position detection issues
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔍 Debugging Stock Position Detection")
    print("=" * 60)
    
    # Check current strategy distribution
    all_trades = db.get_trades(limit=1000)
    
    covered_calls = [t for t in all_trades if t['strategy_type'] == 'Covered Call']
    naked_calls = [t for t in all_trades if t['strategy_type'] == 'Naked Call']
    call_rolls = [t for t in all_trades if t['strategy_type'] == 'Call Roll']
    
    print(f"Current strategy distribution:")
    print(f"  Covered Calls: {len(covered_calls)}")
    print(f"  Naked Calls: {len(naked_calls)}")
    print(f"  Call Rolls: {len(call_rolls)}")
    
    # Check stock position detection
    print(f"\n🔍 Stock Position Analysis")
    print("-" * 40)
    
    raw_txns = db.get_raw_transactions()
    
    # Separate stock and option transactions
    stock_txns = []
    option_txns = []
    
    for tx in raw_txns:
        inst_type = str(tx.get('instrument_type', ''))
        if 'EQUITY' in inst_type and 'OPTION' not in inst_type:
            stock_txns.append(tx)
        elif 'EQUITY_OPTION' in inst_type:
            option_txns.append(tx)
    
    print(f"Total transactions: {len(raw_txns)}")
    print(f"Stock transactions: {len(stock_txns)}")
    print(f"Option transactions: {len(option_txns)}")
    
    # Show sample stock transactions
    if stock_txns:
        print(f"\nSample stock transactions:")
        for tx in stock_txns[:5]:
            symbol = tx.get('symbol', 'Unknown')
            action = tx.get('action', 'Unknown')
            qty = tx.get('quantity', 0)
            price = tx.get('price', 0)
            date = tx.get('executed_at', '')[:10]
            print(f"  {date}: {action} {qty} {symbol} @ ${price}")
    else:
        print(f"\n❌ No stock transactions found!")
    
    # Test stock position calculation
    stock_positions = StrategyRecognizer.get_stock_positions(raw_txns)
    
    print(f"\nStock positions calculated:")
    has_positions = False
    for symbol, qty in stock_positions.items():
        if qty != 0:
            print(f"  {symbol}: {qty} shares")
            has_positions = True
    
    if not has_positions:
        print("  ❌ No stock positions detected!")
    
    # Check IBIT specifically
    print(f"\n🎯 IBIT Analysis")
    print("-" * 40)
    
    ibit_stock_txns = [tx for tx in stock_txns if tx.get('underlying_symbol') == 'IBIT']
    ibit_option_txns = [tx for tx in option_txns if tx.get('underlying_symbol') == 'IBIT']
    
    print(f"IBIT stock transactions: {len(ibit_stock_txns)}")
    print(f"IBIT option transactions: {len(ibit_option_txns)}")
    
    if ibit_stock_txns:
        print(f"\nIBIT stock transactions:")
        for tx in ibit_stock_txns:
            action = tx.get('action', 'Unknown')
            qty = tx.get('quantity', 0)
            price = tx.get('price', 0)
            date = tx.get('executed_at', '')[:10]
            print(f"  {date}: {action} {qty} IBIT @ ${price}")
    
    # Calculate IBIT position specifically
    ibit_position = StrategyRecognizer.get_stock_positions(ibit_stock_txns + ibit_option_txns)
    ibit_qty = ibit_position.get('IBIT', 0)
    
    print(f"\nIBIT calculated position: {ibit_qty} shares")
    
    # Check how this affects strategy recognition
    ibit_trades = [t for t in all_trades if t['underlying'] == 'IBIT']
    
    print(f"\nIBIT trade analysis:")
    strategy_counts = {}
    for trade in ibit_trades:
        strategy = trade['strategy_type']
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
    
    for strategy, count in strategy_counts.items():
        print(f"  {strategy}: {count}")
    
    # Test what happens if we manually set stock position
    print(f"\n🧪 Testing Manual Stock Position")
    print("-" * 40)
    
    if ibit_qty == 0:
        print("Testing with manual IBIT position of 100 shares...")
        
        # Test a single naked call trade to see if it would become covered call
        ibit_naked = [t for t in ibit_trades if t['strategy_type'] == 'Naked Call']
        if ibit_naked:
            sample_trade = ibit_naked[0]
            print(f"Sample naked call: {sample_trade['trade_id']}")
            
            # This would require re-running strategy recognition with stock positions
            print("Need to test TransactionMatcher with stock positions...")

if __name__ == '__main__':
    main()