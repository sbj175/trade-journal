#!/usr/bin/env python3
"""
Fix account separation issue - process each account separately
"""

from src.database.db_manager import DatabaseManager
from src.models.transaction_matcher import TransactionMatcher
from src.models.trade_strategy import StrategyRecognizer

def process_account_separately():
    """Test processing each account separately"""
    db = DatabaseManager()
    
    print("🔧 Testing Account-Separated Processing")
    print("=" * 60)
    
    # Get all accounts
    accounts = db.get_accounts()
    all_raw_txns = db.get_raw_transactions()
    
    print(f"Total accounts: {len(accounts)}")
    print(f"Total transactions: {len(all_raw_txns)}")
    
    # Process each account separately
    all_strategy_matches = []
    
    for account in accounts:
        account_number = account['account_number']
        account_name = account.get('account_name', 'Unknown')
        
        # Get transactions for this account only
        account_txns = [tx for tx in all_raw_txns if tx.get('account_number') == account_number]
        
        print(f"\n📊 Processing Account {account_number} ({account_name})")
        print(f"   Transactions: {len(account_txns)}")
        
        if len(account_txns) == 0:
            continue
        
        # Calculate stock positions for this account only
        stock_positions = StrategyRecognizer.get_stock_positions(account_txns)
        existing_positions = {}
        for symbol, quantity in stock_positions.items():
            if symbol not in existing_positions:
                existing_positions[symbol] = {'stock': 0, 'options': {}}
            existing_positions[symbol]['stock'] = quantity
        
        print(f"   Stock positions: {len([s for s, data in existing_positions.items() if data['stock'] > 0])}")
        
        # Process with TransactionMatcher
        matcher = TransactionMatcher()
        strategy_matches = matcher.match_transactions_to_strategies(account_txns, existing_positions)
        
        print(f"   Strategies identified: {len(strategy_matches)}")
        
        # Show breakdown
        strategy_counts = {}
        for match in strategy_matches:
            strategy = match.strategy_type.value
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        
        for strategy, count in sorted(strategy_counts.items()):
            print(f"     {strategy}: {count}")
        
        all_strategy_matches.extend(strategy_matches)
    
    print(f"\n📋 COMBINED RESULTS")
    print("-" * 40)
    
    # Combined strategy counts
    combined_counts = {}
    for match in all_strategy_matches:
        strategy = match.strategy_type.value
        combined_counts[strategy] = combined_counts.get(strategy, 0) + 1
    
    print(f"Total strategies: {len(all_strategy_matches)}")
    for strategy, count in sorted(combined_counts.items()):
        print(f"  {strategy}: {count}")
    
    # Check for IBIT $61 calls specifically
    print(f"\n🎯 IBIT $61 Call Analysis")
    print("-" * 40)
    
    ibit_matches = [m for m in all_strategy_matches if any(tx.get('underlying_symbol') == 'IBIT' for tx in m.transactions)]
    
    for match in ibit_matches:
        # Check if this involves $61 calls
        has_61_call = False
        for tx in match.transactions:
            symbol = tx.get('symbol', '')
            if 'C00061000' in symbol:
                has_61_call = True
                break
        
        if has_61_call:
            account = match.transactions[0].get('account_number')
            account_name = "Traditional IRA" if account == "5WZ26959" else "Roth IRA" if account == "5WZ28644" else "Individual Margin"
            
            print(f"\n  {match.strategy_type.value} in {account} ({account_name}):")
            print(f"    Transactions: {len(match.transactions)}")
            print(f"    Confidence: {match.confidence.value}")
            
            # Show transaction details
            for tx in match.transactions:
                action = tx.get('action', 'Unknown')
                qty = tx.get('quantity', 0)
                symbol = tx.get('symbol', '')
                if 'C00061000' in symbol:
                    print(f"      {action} {qty} $61 Call")
                else:
                    print(f"      {action} {qty} {symbol[:20]}...")
    
    return all_strategy_matches

def compare_with_current():
    """Compare account-separated results with current database"""
    print(f"\n🔍 COMPARISON WITH CURRENT DATABASE")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Current database state
    current_ibit = db.get_trades(underlying='IBIT', limit=50)
    
    print(f"Current IBIT trades by account:")
    by_account = {}
    for trade in current_ibit:
        account = trade.get('account_number')
        if account not in by_account:
            by_account[account] = []
        by_account[account].append(trade)
    
    for account, trades in by_account.items():
        account_name = "Traditional IRA" if account == "5WZ26959" else "Roth IRA" if account == "5WZ28644" else "Individual Margin"
        print(f"\n  {account} ({account_name}): {len(trades)} trades")
        
        for trade in trades:
            print(f"    {trade['trade_id']}: {trade['strategy_type']}")

if __name__ == '__main__':
    strategy_matches = process_account_separately()
    compare_with_current()
    
    print(f"\n" + "=" * 60)
    print("🎯 ACCOUNT SEPARATION ANALYSIS")
    print("=" * 60)
    
    print(f"Solution: Process each account separately to prevent cross-account grouping")
    print(f"Current system processes all accounts together, causing assignment errors")