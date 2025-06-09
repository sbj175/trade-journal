#!/usr/bin/env python3
"""
Apply ROLL detection to the database - re-sync with improved strategy recognition
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔄 Applying ROLL Detection to Database")
    print("=" * 60)
    
    # Step 1: Backup user data
    current_trades = db.get_trades(limit=10000)
    user_data = {}
    
    for trade in current_trades:
        if trade.get('current_notes') or trade.get('tags'):
            user_data[trade['trade_id']] = {
                'current_notes': trade.get('current_notes'),
                'tags': trade.get('tags')
            }
    
    print(f"📝 Backed up user data for {len(user_data)} trades")
    
    # Step 2: Show current state
    current_strategy_counts = {}
    for trade in current_trades:
        strategy = trade['strategy_type']
        current_strategy_counts[strategy] = current_strategy_counts.get(strategy, 0) + 1
    
    print(f"\nCURRENT STATE:")
    print(f"  Diagonal Spread: {current_strategy_counts.get('Diagonal Spread', 0)}")
    print(f"  Calendar Spread: {current_strategy_counts.get('Calendar Spread', 0)}")
    print(f"  Call Roll: {current_strategy_counts.get('Call Roll', 0)}")
    print(f"  Put Roll: {current_strategy_counts.get('Put Roll', 0)}")
    print(f"  Total trades: {len(current_trades)}")
    
    # Step 3: Clear existing trades
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM option_legs")
        cursor.execute("DELETE FROM stock_legs")
        cursor.execute("DELETE FROM trades")
        conn.commit()
    
    print(f"\n🗑️  Cleared existing trades")
    
    # Step 4: Re-process with ROLL detection
    raw_txns = db.get_raw_transactions()
    print(f"📊 Processing {len(raw_txns)} raw transactions with ROLL detection")
    
    # Calculate stock positions
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
    
    print(f"🎯 Identified {len(strategy_matches)} strategies with ROLL detection")
    
    # Step 5: Convert to trades and save
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
    
    # Step 6: Restore user data
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
    
    # Step 7: Show final results
    final_trades = db.get_trades(limit=10000)
    final_strategy_counts = {}
    for trade in final_trades:
        strategy = trade['strategy_type']
        final_strategy_counts[strategy] = final_strategy_counts.get(strategy, 0) + 1
    
    print(f"\n✅ ROLL Detection Applied Successfully!")
    print(f"   📈 {saved_count} trades saved")
    print(f"   ❌ {failed_count} failed")
    print(f"   📝 {restored_count} user notes restored")
    
    print(f"\nFINAL STATE:")
    print(f"  Diagonal Spread: {final_strategy_counts.get('Diagonal Spread', 0)}")
    print(f"  Calendar Spread: {final_strategy_counts.get('Calendar Spread', 0)}")
    print(f"  Call Roll: {final_strategy_counts.get('Call Roll', 0)}")
    print(f"  Put Roll: {final_strategy_counts.get('Put Roll', 0)}")
    print(f"  Total trades: {len(final_trades)}")
    
    # Show changes
    diagonal_change = final_strategy_counts.get('Diagonal Spread', 0) - current_strategy_counts.get('Diagonal Spread', 0)
    calendar_change = final_strategy_counts.get('Calendar Spread', 0) - current_strategy_counts.get('Calendar Spread', 0)
    call_roll_change = final_strategy_counts.get('Call Roll', 0) - current_strategy_counts.get('Call Roll', 0)
    put_roll_change = final_strategy_counts.get('Put Roll', 0) - current_strategy_counts.get('Put Roll', 0)
    
    print(f"\nCHANGES:")
    print(f"  Diagonal Spread: {diagonal_change:+d}")
    print(f"  Calendar Spread: {calendar_change:+d}")
    print(f"  Call Roll: {call_roll_change:+d}")
    print(f"  Put Roll: {put_roll_change:+d}")
    
    # Show sample rolls
    roll_trades = [t for t in final_trades if 'Roll' in t['strategy_type']]
    print(f"\nSample ROLLs detected:")
    for trade in roll_trades[:5]:
        print(f"  {trade['trade_id']}: {trade['strategy_type']} - {trade['entry_date']}")

if __name__ == '__main__':
    main()