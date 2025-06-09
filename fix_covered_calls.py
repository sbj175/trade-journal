#!/usr/bin/env python3
"""
Re-process trades with fixed stock position detection to restore covered calls
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔧 Fixing Covered Call Recognition")
    print("=" * 60)
    
    # Step 1: Check current state
    all_trades = db.get_trades(limit=1000)
    current_covered = len([t for t in all_trades if t['strategy_type'] == 'Covered Call'])
    current_naked = len([t for t in all_trades if t['strategy_type'] == 'Naked Call'])
    
    print(f"BEFORE fix:")
    print(f"  Covered Calls: {current_covered}")
    print(f"  Naked Calls: {current_naked}")
    
    # Step 2: Test what would happen with correct stock positions
    raw_txns = db.get_raw_transactions()
    
    # Calculate stock positions correctly
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
    
    print(f"\nStock positions for covered call detection:")
    for symbol, data in existing_positions.items():
        stock_qty = data['stock']
        if stock_qty > 0:
            print(f"  {symbol}: {stock_qty} shares")
    
    # Step 3: Re-process with correct positions
    print(f"\n🔄 Re-processing with correct stock positions...")
    
    matcher = TransactionMatcher()
    strategy_matches = matcher.match_transactions_to_strategies(raw_txns, existing_positions)
    
    # Count what strategies would be detected
    new_strategy_counts = {}
    for match in strategy_matches:
        strategy = match.strategy_type.value
        new_strategy_counts[strategy] = new_strategy_counts.get(strategy, 0) + 1
    
    print(f"\nWould be detected with correct positions:")
    print(f"  Covered Call: {new_strategy_counts.get('Covered Call', 0)}")
    print(f"  Naked Call: {new_strategy_counts.get('Naked Call', 0)}")
    print(f"  Call Roll: {new_strategy_counts.get('Call Roll', 0)}")
    print(f"  Put Roll: {new_strategy_counts.get('Put Roll', 0)}")
    
    # Step 4: Apply the fix
    proceed = input(f"\nApply fix to database? (y/N): ").lower().strip()
    
    if proceed == 'y':
        print(f"\n🔄 Applying fix to database...")
        
        # Backup user data
        user_data = {}
        for trade in all_trades:
            if trade.get('current_notes') or trade.get('tags'):
                user_data[trade['trade_id']] = {
                    'current_notes': trade.get('current_notes'),
                    'tags': trade.get('tags')
                }
        
        print(f"📝 Backed up user data for {len(user_data)} trades")
        
        # Clear and rebuild
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM option_legs")
            cursor.execute("DELETE FROM stock_legs")
            cursor.execute("DELETE FROM trades")
            conn.commit()
        
        print(f"🗑️  Cleared existing trades")
        
        # Save new trades
        saved_count = 0
        failed_count = 0
        
        for match in strategy_matches:
            try:
                trade = StrategyRecognizer._create_trade_from_strategy_match(match)
                if trade:
                    if match.transactions:
                        account_number = match.transactions[0].get('account_number', 'UNKNOWN')
                        trade.account_number = account_number
                    
                    if db.save_trade(trade, account_number):
                        saved_count += 1
                        if saved_count % 25 == 0:
                            print(f"  📈 Saved {saved_count} trades...")
                    else:
                        failed_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"  ❌ Error: {e}")
        
        # Restore user data
        restored_count = 0
        if user_data:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                for trade_id, data in user_data.items():
                    try:
                        cursor.execute("""
                            UPDATE trades 
                            SET current_notes = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE trade_id = ?
                        """, (data['current_notes'], data['tags'], trade_id))
                        if cursor.rowcount > 0:
                            restored_count += 1
                    except:
                        continue
        
        # Final results
        final_trades = db.get_trades(limit=1000)
        final_covered = len([t for t in final_trades if t['strategy_type'] == 'Covered Call'])
        final_naked = len([t for t in final_trades if t['strategy_type'] == 'Naked Call'])
        
        print(f"\n✅ Fix Applied Successfully!")
        print(f"   📈 {saved_count} trades saved")
        print(f"   ❌ {failed_count} failed")
        print(f"   📝 {restored_count} user notes restored")
        
        print(f"\nAFTER fix:")
        print(f"  Covered Calls: {final_covered}")
        print(f"  Naked Calls: {final_naked}")
        
        covered_change = final_covered - current_covered
        naked_change = final_naked - current_naked
        
        print(f"\nCHANGES:")
        print(f"  Covered Calls: {covered_change:+d}")
        print(f"  Naked Calls: {naked_change:+d}")
        
        # Show sample covered calls
        covered_calls = [t for t in final_trades if t['strategy_type'] == 'Covered Call']
        if covered_calls:
            print(f"\nSample Covered Calls:")
            for trade in covered_calls[:5]:
                print(f"  {trade['trade_id']}: {trade['underlying']}")
    else:
        print("Fix not applied.")

if __name__ == '__main__':
    main()