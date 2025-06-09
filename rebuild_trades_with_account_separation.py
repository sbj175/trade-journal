#!/usr/bin/env python3
"""
Rebuild all trades from scratch with proper account separation
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def rebuild_all_trades():
    """Completely rebuild all trades from raw transactions with proper account separation"""
    print("🔄 Rebuilding All Trades with Account Separation")
    print("=" * 70)
    
    db = DatabaseManager()
    
    # Step 1: Get current state
    current_trades = db.get_trades(limit=10000)
    raw_transactions = db.get_raw_transactions()
    
    print(f"Current trades in database: {len(current_trades)}")
    print(f"Raw transactions to process: {len(raw_transactions)}")
    
    # Step 2: Backup current state and clear trades
    print("\n🗑️  Clearing existing trades...")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM option_legs")
        cursor.execute("DELETE FROM stock_legs")  
        cursor.execute("DELETE FROM trades")
        conn.commit()
    print("All trades cleared")
    
    # Step 3: Process each account separately
    print("\n📊 Processing transactions with account separation...")
    
    # Group transactions by account
    accounts = {}
    for tx in raw_transactions:
        account_number = tx.get('account_number', 'UNKNOWN')
        if account_number not in accounts:
            accounts[account_number] = []
        accounts[account_number].append(tx)
    
    print(f"Found {len(accounts)} accounts to process")
    
    all_trades = []
    matcher = TransactionMatcher()
    
    # Process each account independently  
    for account_number, account_txns in accounts.items():
        if not account_txns:
            continue
            
        account_name = get_account_name(account_number)
        print(f"\\n  Processing {account_number} ({account_name}): {len(account_txns)} transactions")
        
        # Calculate stock positions for this account only
        stock_positions = StrategyRecognizer.get_stock_positions(account_txns)
        existing_positions = {}
        for symbol, quantity in stock_positions.items():
            existing_positions[symbol] = {'stock': quantity, 'options': {}}
        
        print(f"    Stock positions: {len([s for s, data in existing_positions.items() if data['stock'] > 0])}")
        
        # Use TransactionMatcher for superior consolidation and grouping
        strategy_matches = matcher.match_transactions_to_strategies(account_txns, existing_positions)
        
        print(f"    Strategy matches: {len(strategy_matches)}")
        
        # Convert StrategyMatch objects to Trade objects
        account_trades = []
        for match in strategy_matches:
            trade = StrategyRecognizer._create_trade_from_strategy_match(match)
            if trade:
                account_trades.append(trade)
                all_trades.append(trade)
        
        print(f"    Generated trades: {len(account_trades)}")
        
        # Show account summary
        if account_trades:
            strategy_counts = {}
            for trade in account_trades:
                strategy = trade.strategy_type.value
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
            
            print(f"    Strategies:")
            for strategy, count in sorted(strategy_counts.items()):
                print(f"      {strategy}: {count}")
    
    # Step 4: Save all trades to database
    print(f"\\n💾 Saving {len(all_trades)} trades to database...")
    saved_count = 0
    
    for trade in all_trades:
        try:
            db.save_trade(trade)
            saved_count += 1
        except Exception as e:
            print(f"Error saving trade {trade.trade_id}: {e}")
            continue
    
    print(f"Successfully saved {saved_count} trades")
    
    # Step 5: Analyze IBIT specifically
    print(f"\\n🎯 IBIT Analysis After Rebuild")
    print("-" * 50)
    
    ibit_trades = db.get_trades(underlying='IBIT', limit=50)
    
    by_account = {}
    for trade in ibit_trades:
        account = trade.get('account_number')
        if account not in by_account:
            by_account[account] = []
        by_account[account].append(trade)
    
    for account, trades in by_account.items():
        account_name = get_account_name(account)
        print(f"\\n{account} ({account_name}): {len(trades)} trades")
        
        # Look for May 5th trades specifically
        may_5_trades = [t for t in trades if t.get('entry_date') == '2025-05-05']
        for trade in may_5_trades:
            print(f"  📅 {trade['trade_id']} (May 5th)")
            print(f"     Strategy: {trade['strategy_type']}")
            
            try:
                details = db.get_trade_details(trade['trade_id'])
                option_legs = details.get('option_legs', [])
                
                for leg in option_legs:
                    strike = leg.get('strike', 'N/A')
                    qty = leg.get('quantity', 0)
                    exp = leg.get('expiration', 'N/A')
                    print(f"     Position: \\${strike} x{abs(qty)} exp {exp}")
            except Exception as e:
                print(f"     Error: {e}")
    
    print(f"\\n✅ REBUILD COMPLETE")
    print(f"=" * 70)
    print(f"Summary:")
    print(f"  Total trades: {len(all_trades)}")
    print(f"  Trades saved: {saved_count}")
    print(f"  Accounts processed: {len(accounts)}")
    
    # Expected result
    print(f"\\n🎯 Expected Results:")
    print(f"  Traditional IRA should show: IBIT \\$55.5 x150 calls")
    print(f"  Roth IRA should show: IBIT \\$55.5 x48 calls")

def get_account_name(account_number):
    """Get friendly account name"""
    if account_number == "5WZ26959":
        return "Traditional IRA"
    elif account_number == "5WZ28644":
        return "Roth IRA"
    elif account_number == "5WZ27378":
        return "Individual Margin"
    else:
        return "Unknown"

if __name__ == '__main__':
    rebuild_all_trades()