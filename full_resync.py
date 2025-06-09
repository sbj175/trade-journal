#!/usr/bin/env python3
"""
Full re-sync of all trades using the new order-based system
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔄 Full re-sync of all trades with new order-based system...")
    
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
    
    # Step 2: Clear existing trades
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all trade IDs first
        cursor.execute("SELECT trade_id FROM trades")
        all_trade_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete legs first (foreign key constraints)
        cursor.execute("DELETE FROM option_legs")
        cursor.execute("DELETE FROM stock_legs")
        cursor.execute("DELETE FROM trades")
        conn.commit()
        
    print(f"🗑️  Deleted {len(all_trade_ids)} existing trades")
    
    # Step 3: Get all raw transactions
    raw_txns = db.get_raw_transactions()
    print(f"📊 Processing {len(raw_txns)} raw transactions")
    
    if not raw_txns:
        print("❌ No raw transactions found!")
        return
    
    # Step 4: Calculate stock positions for covered call detection
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
    
    print(f"📈 Calculated stock positions for {len(existing_positions)} symbols")
    
    # Step 5: Process with new system
    matcher = TransactionMatcher()
    strategy_matches = matcher.match_transactions_to_strategies(raw_txns, existing_positions)
    
    print(f"🎯 New system identified {len(strategy_matches)} strategies")
    
    # Step 6: Convert to trades and save
    saved_count = 0
    failed_count = 0
    
    for match in strategy_matches:
        try:
            # Create trade from strategy match
            trade = StrategyRecognizer._create_trade_from_strategy_match(match)
            if trade:
                # Set account number from first transaction
                if match.transactions:
                    account_number = match.transactions[0].get('account_number', 'UNKNOWN')
                    trade.account_number = account_number
                
                # Save trade
                if db.save_trade(trade, account_number):
                    saved_count += 1
                    if saved_count % 50 == 0:  # Progress indicator
                        print(f"  📈 Saved {saved_count} trades...")
                else:
                    failed_count += 1
            else:
                failed_count += 1
                
        except Exception as e:
            failed_count += 1
            print(f"  ❌ Error processing strategy match: {e}")
    
    # Step 7: Restore user notes
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
                except Exception as e:
                    continue  # Skip failed restorations
    
    print(f"\n✅ Full re-sync complete!")
    print(f"   📈 {saved_count} trades saved")
    print(f"   ❌ {failed_count} failed") 
    print(f"   📝 {restored_count} user notes restored")
    
    # Step 8: Show summary
    final_trades = db.get_trades(limit=10000)
    print(f"\n📋 Final result: {len(final_trades)} total trades")
    
    # Strategy breakdown
    strategy_counts = {}
    for trade in final_trades:
        strategy = trade['strategy_type']
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
    
    print(f"\nStrategy breakdown:")
    for strategy, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   {strategy}: {count} trades")
    
    # Check for problematic trades
    problem_trades = []
    for trade in final_trades:
        if 'legs' in trade['trade_id']:
            try:
                leg_count = int(trade['trade_id'].split('_')[2].replace('legs', ''))
                if leg_count > 10:  # Consider 10+ legs as problematic
                    problem_trades.append((trade['trade_id'], leg_count))
            except:
                pass
    
    if problem_trades:
        print(f"\n⚠️  Remaining problematic trades:")
        for trade_id, leg_count in sorted(problem_trades, key=lambda x: x[1], reverse=True)[:5]:
            print(f"   {trade_id} ({leg_count} legs)")
    else:
        print(f"\n🎉 No problematic multi-leg trades found!")

if __name__ == '__main__':
    main()