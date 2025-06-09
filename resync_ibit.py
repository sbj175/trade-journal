#!/usr/bin/env python3
"""
Re-sync IBIT trades using the new order-based system
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    print("🔄 Re-syncing IBIT trades with new order-based system...")
    
    # Step 1: Get current IBIT trades to backup user notes
    current_trades = db.get_trades(underlying='IBIT', limit=100)
    user_data = {}
    
    for trade in current_trades:
        if trade.get('current_notes') or trade.get('tags'):
            user_data[trade['trade_id']] = {
                'current_notes': trade.get('current_notes'),
                'tags': trade.get('tags')
            }
    
    print(f"📝 Backed up user data for {len(user_data)} trades")
    
    # Step 2: Delete existing IBIT trades
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get IBIT trade IDs first
        cursor.execute("SELECT trade_id FROM trades WHERE underlying = 'IBIT'")
        ibit_trade_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete legs first (foreign key constraints)
        for trade_id in ibit_trade_ids:
            cursor.execute("DELETE FROM option_legs WHERE trade_id = ?", (trade_id,))
            cursor.execute("DELETE FROM stock_legs WHERE trade_id = ?", (trade_id,))
        
        # Delete trades
        cursor.execute("DELETE FROM trades WHERE underlying = 'IBIT'")
        conn.commit()
        
    print(f"🗑️  Deleted {len(ibit_trade_ids)} existing IBIT trades")
    
    # Step 3: Get raw IBIT transactions
    raw_txns = db.get_raw_transactions(underlying='IBIT')
    print(f"📊 Processing {len(raw_txns)} raw IBIT transactions")
    
    # Step 4: Manually set IBIT stock position for covered call detection
    # Since you mentioned you own IBIT and sell covered calls against it
    existing_positions = {
        'IBIT': {'stock': 100, 'options': {}}  # Assuming 100 shares for covered calls
    }
    print(f"📈 Using manual position: 100 IBIT shares for covered call detection")
    
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
                    print(f"  ✅ Saved: {trade.trade_id} - {trade.strategy_type.value}")
                else:
                    failed_count += 1
                    print(f"  ❌ Failed to save: {trade.trade_id}")
            else:
                failed_count += 1
                print(f"  ❌ Failed to create trade from strategy match")
                
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
                    print(f"  ⚠️  Failed to restore user data for {trade_id}: {e}")
    
    print(f"\n✅ IBIT re-sync complete!")
    print(f"   📈 {saved_count} trades saved")
    print(f"   ❌ {failed_count} failed") 
    print(f"   📝 {restored_count} user notes restored")
    
    # Step 8: Show summary of new trades
    new_trades = db.get_trades(underlying='IBIT', limit=50)
    print(f"\n📋 New IBIT trades ({len(new_trades)} total):")
    
    strategy_counts = {}
    for trade in new_trades:
        strategy = trade['strategy_type']
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
    
    for strategy, count in strategy_counts.items():
        print(f"   {strategy}: {count} trades")

if __name__ == '__main__':
    main()