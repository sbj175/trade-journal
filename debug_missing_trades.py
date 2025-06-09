#!/usr/bin/env python3
"""
Debug why all trades disappeared after resync
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔍 Debugging missing trades...")
    
    # Check database state
    all_trades = db.get_trades(limit=1000)
    raw_txns = db.get_raw_transactions()
    print(f"Database state: {len(all_trades)} trades, {len(raw_txns)} raw transactions")
    
    if not raw_txns:
        print("❌ No raw transactions - this is the root problem")
        return
    
    # Test the processing pipeline
    print(f"\n🧪 Testing transaction processing pipeline...")
    
    # Step 1: Group by symbol
    symbols = {}
    for tx in raw_txns:
        symbol = tx.get('underlying_symbol', 'Unknown')
        if symbol not in symbols:
            symbols[symbol] = []
        symbols[symbol].append(tx)
    
    print(f"Symbols found: {list(symbols.keys())}")
    
    # Step 2: Test with a small subset
    test_symbol = 'IBIT' if 'IBIT' in symbols else list(symbols.keys())[0]
    test_txns = symbols[test_symbol]
    print(f"\n🧪 Testing with {test_symbol}: {len(test_txns)} transactions")
    
    # Step 3: Calculate stock positions
    stock_positions = StrategyRecognizer.get_stock_positions(test_txns)
    existing_positions = {}
    for symbol, quantity in stock_positions.items():
        if symbol not in existing_positions:
            existing_positions[symbol] = {'stock': 0, 'options': {}}
        existing_positions[symbol]['stock'] = quantity
    
    print(f"Stock positions: {existing_positions}")
    
    # Step 4: Test TransactionMatcher
    try:
        matcher = TransactionMatcher()
        strategy_matches = matcher.match_transactions_to_strategies(test_txns, existing_positions)
        print(f"✅ TransactionMatcher created {len(strategy_matches)} strategy matches")
        
        for i, match in enumerate(strategy_matches[:3]):  # Show first 3
            print(f"  {i+1}. {match.strategy_type.value} - {len(match.transactions)} txns - {match.confidence.value}")
            
    except Exception as e:
        print(f"❌ TransactionMatcher failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Test trade creation
    if strategy_matches:
        try:
            trade = StrategyRecognizer._create_trade_from_strategy_match(strategy_matches[0])
            if trade:
                print(f"✅ Trade creation succeeded: {trade.trade_id}")
                print(f"   Strategy: {trade.strategy_type.value}")
                print(f"   Account: {trade.account_number}")
                print(f"   Option legs: {len(trade.option_legs)}")
                print(f"   Stock legs: {len(trade.stock_legs)}")
            else:
                print(f"❌ Trade creation returned None")
        except Exception as e:
            print(f"❌ Trade creation failed: {e}")
            import traceback
            traceback.print_exc()
            return
    
    # Step 6: Test trade saving
    if strategy_matches:
        try:
            trade = StrategyRecognizer._create_trade_from_strategy_match(strategy_matches[0])
            if trade:
                account_number = test_txns[0].get('account_number', 'UNKNOWN')
                success = db.save_trade(trade, account_number)
                if success:
                    print(f"✅ Trade saving succeeded")
                    
                    # Verify it's in database
                    saved_trades = db.get_trades(underlying=trade.underlying, limit=10)
                    print(f"   Verified: {len(saved_trades)} trades found for {trade.underlying}")
                else:
                    print(f"❌ Trade saving failed")
        except Exception as e:
            print(f"❌ Trade saving failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()