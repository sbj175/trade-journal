#!/usr/bin/env python3
"""
Test script to analyze IBIT transactions and compare old vs new grouping
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    
    # Get IBIT raw transactions
    raw_txns = db.get_raw_transactions(underlying='IBIT')
    print(f'Analyzing {len(raw_txns)} IBIT raw transactions...')
    
    # Separate stock vs option transactions
    equity_txns = []
    option_txns = []
    
    for tx in raw_txns:
        inst_type = str(tx.get('instrument_type', ''))
        if 'EQUITY_OPTION' in inst_type:
            option_txns.append(tx)
        elif 'EQUITY' in inst_type and 'OPTION' not in inst_type:
            equity_txns.append(tx)
    
    print(f'\nTransaction breakdown:')
    print(f'  Equity (stock) transactions: {len(equity_txns)}')
    print(f'  Option transactions: {len(option_txns)}')
    
    # Show equity transactions if any
    if equity_txns:
        print(f'\nIBIT stock transactions:')
        for tx in equity_txns:
            print(f"  {tx['executed_at'][:10]}: {tx['action']} {tx['quantity']} shares at ${tx['price']}")
    
    # Calculate current stock position from all accounts
    print(f'\n--- Calculating stock positions from all accounts ---')
    all_raw_txns = []
    accounts = db.get_accounts()
    for account in accounts:
        account_txns = db.get_raw_transactions(account_number=account['account_number'])
        all_raw_txns.extend(account_txns)
    
    stock_positions = StrategyRecognizer.get_stock_positions(all_raw_txns)
    print(f'Stock positions calculated:')
    for symbol, qty in stock_positions.items():
        if qty != 0:
            print(f'  {symbol}: {qty} shares')
    
    ibit_stock_qty = stock_positions.get('IBIT', 0)
    print(f'\nIBIT stock position: {ibit_stock_qty} shares')
    
    # Check current trades vs what new system would create
    current_trades = db.get_trades(underlying='IBIT', limit=50)
    print(f'\nCurrent database has {len(current_trades)} IBIT trades')
    
    # Show problem trades (many legs)
    problem_trades = [t for t in current_trades if 'legs' in t['trade_id'] and int(t['trade_id'].split('_')[2].replace('legs', '')) > 10]
    if problem_trades:
        print(f'\nProblem trades with many legs:')
        for trade in problem_trades:
            print(f"  {trade['trade_id']}: {trade['strategy_type']}")
    
    # Test new system
    print(f'\n--- Testing new TransactionMatcher system ---')
    from src.models.transaction_matcher import TransactionMatcher
    
    existing_positions = {}
    if ibit_stock_qty > 0:
        existing_positions['IBIT'] = {'stock': ibit_stock_qty, 'options': {}}
        print(f'Using existing position: {ibit_stock_qty} IBIT shares for covered call detection')
    
    matcher = TransactionMatcher()
    strategy_matches = matcher.match_transactions_to_strategies(raw_txns, existing_positions)
    
    print(f'\nNew system would create {len(strategy_matches)} trades:')
    for i, match in enumerate(strategy_matches):
        tx_count = len(match.transactions)
        confidence = match.confidence.value
        strategy = match.strategy_type.value
        
        order_ids = set(tx.get('order_id') for tx in match.transactions if tx.get('order_id'))
        order_id_str = f" (Order: {list(order_ids)[0]})" if order_ids else ""
        
        print(f"  {i+1}. {strategy} - {tx_count} transactions - {confidence} confidence{order_id_str}")

if __name__ == '__main__':
    main()