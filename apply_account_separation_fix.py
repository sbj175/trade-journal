#!/usr/bin/env python3
"""
Apply the account separation fix by resyncing trades from raw transactions
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer
import sys

def main():
    """Apply account separation fix"""
    print("🔄 Applying Account Separation Fix")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get current trade count
    current_trades = db.get_trades(limit=10000)
    print(f"Current trades in database: {len(current_trades)}")
    
    # Clear existing trades to avoid conflicts
    print("\n🗑️  Clearing existing trades...")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM option_legs")
        cursor.execute("DELETE FROM stock_legs")
        cursor.execute("DELETE FROM trades")
        conn.commit()
    print("Trades cleared")
    
    # Get raw transactions
    print("\n📊 Processing raw transactions with account separation...")
    raw_transactions = db.get_raw_transactions()
    print(f"Raw transactions to process: {len(raw_transactions)}")
    
    # Apply the fixed grouping logic using TransactionMatcher (with account separation)
    from src.models.transaction_matcher import TransactionMatcher
    
    # Process each account separately with TransactionMatcher
    all_trades = []
    matcher = TransactionMatcher()
    
    # Group transactions by account
    accounts = {}
    for tx in raw_transactions:
        account_number = tx.get('account_number', 'UNKNOWN')
        if account_number not in accounts:
            accounts[account_number] = []
        accounts[account_number].append(tx)
    
    for account_number, account_txns in accounts.items():
        if not account_txns:
            continue
            
        print(f"  Processing account {account_number}: {len(account_txns)} transactions")
        
        # Calculate stock positions for this account only
        stock_positions = StrategyRecognizer.get_stock_positions(account_txns)
        existing_positions = {}
        for symbol, quantity in stock_positions.items():
            existing_positions[symbol] = {'stock': quantity, 'options': {}}
        
        # Use TransactionMatcher for superior consolidation and grouping
        strategy_matches = matcher.match_transactions_to_strategies(account_txns, existing_positions)
        
        # Convert StrategyMatch objects to Trade objects
        for match in strategy_matches:
            trade = StrategyRecognizer._create_trade_from_strategy_match(match)
            if trade:
                all_trades.append(trade)
    
    trades = all_trades
    print(f"Generated trades: {len(trades)}")
    
    # Save trades to database
    print("\n💾 Saving trades to database...")
    saved_count = 0
    for trade in trades:
        try:
            db.save_trade(trade)
            saved_count += 1
        except Exception as e:
            print(f"Error saving trade {trade.trade_id}: {e}")
            continue
    
    print(f"Successfully saved {saved_count} trades")
    
    # Analyze IBIT trades specifically
    print(f"\n🎯 IBIT Trade Analysis")
    print("-" * 40)
    
    ibit_trades_by_account = {}
    for trade in trades:
        if trade.underlying == 'IBIT':
            account = trade.account_number
            if account not in ibit_trades_by_account:
                ibit_trades_by_account[account] = []
            ibit_trades_by_account[account].append(trade)
    
    for account, account_trades in ibit_trades_by_account.items():
        account_name = "Traditional IRA" if account == "5WZ26959" else "Roth IRA" if account == "5WZ28644" else "Individual Margin"
        print(f"\nAccount {account} ({account_name}): {len(account_trades)} trades")
        
        # Count trades by strategy type
        strategy_counts = {}
        covered_call_details = []
        
        for trade in account_trades:
            strategy = trade.strategy_type.value
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
            
            # Collect covered call details
            if strategy == "Covered Call":
                for leg in trade.option_legs:
                    covered_call_details.append({
                        'strike': leg.strike,
                        'quantity': abs(leg.quantity),
                        'expiration': leg.expiration,
                        'trade_id': trade.trade_id
                    })
        
        for strategy, count in strategy_counts.items():
            print(f"  {strategy}: {count}")
            
        # Show covered call details
        if covered_call_details:
            print(f"  Covered Call Details:")
            for detail in covered_call_details:
                print(f"    ${detail['strike']} x{detail['quantity']} exp {detail['expiration']} ({detail['trade_id']})")
    
    print(f"\n" + "=" * 60)
    print("✅ ACCOUNT SEPARATION FIX COMPLETE")
    print("=" * 60)
    print(f"Summary:")
    print(f"  Total trades processed: {len(trades)}")
    print(f"  Trades saved: {saved_count}")
    print(f"  IBIT trades: {sum(len(trades) for trades in ibit_trades_by_account.values())}")
    
    # Check for the specific missing calls
    traditional_covered = ibit_trades_by_account.get('5WZ26959', [])
    roth_covered = ibit_trades_by_account.get('5WZ28644', [])
    
    traditional_covered_calls = [t for t in traditional_covered if t.strategy_type.value == "Covered Call"]
    roth_covered_calls = [t for t in roth_covered if t.strategy_type.value == "Covered Call"]
    
    print(f"\nSpecific Issue Resolution:")
    print(f"  Traditional IRA covered calls: {len(traditional_covered_calls)} (expected: trades with 150 calls)")
    print(f"  Roth IRA covered calls: {len(roth_covered_calls)} (expected: trades with 48 calls)")

if __name__ == '__main__':
    main()