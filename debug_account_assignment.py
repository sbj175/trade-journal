#!/usr/bin/env python3
"""
Debug account assignment issues for trades
"""

from src.database.db_manager import DatabaseManager

def main():
    db = DatabaseManager()
    
    print("🔍 Debugging Account Assignment Issues")
    print("=" * 60)
    
    # Check all accounts
    accounts = db.get_accounts()
    print(f"Available accounts: {len(accounts)}")
    for account in accounts:
        print(f"  {account['account_number']}: {account.get('account_name', 'Unknown')} ({account.get('account_type', 'Unknown')})")
    
    # Get all IBIT trades and their account assignments
    ibit_trades = db.get_trades(underlying='IBIT', limit=50)
    print(f"\nIBIT trades: {len(ibit_trades)}")
    
    # Group by account
    trades_by_account = {}
    for trade in ibit_trades:
        account = trade.get('account_number', 'UNKNOWN')
        if account not in trades_by_account:
            trades_by_account[account] = []
        trades_by_account[account].append(trade)
    
    print(f"\nIBIT trades by account:")
    for account, trades in trades_by_account.items():
        print(f"\n  Account {account}: {len(trades)} trades")
        
        # Show details for each trade
        for trade in trades:
            print(f"    {trade['trade_id']}: {trade['strategy_type']} - {trade['status']}")
            
            # Get detailed info for naked calls and covered calls
            if trade['strategy_type'] in ['Naked Call', 'Covered Call']:
                trade_details = db.get_trade_details(trade['trade_id'])
                option_legs = trade_details.get('option_legs', [])
                
                for leg in option_legs:
                    strike = leg.get('strike', 'Unknown')
                    quantity = leg.get('quantity', 0)
                    print(f"      ${strike} Call x{abs(quantity)} ({'short' if quantity < 0 else 'long'})")
    
    # Check raw transactions to see actual account distribution
    print(f"\n🔍 Raw Transaction Analysis")
    print("-" * 40)
    
    ibit_raw_txns = db.get_raw_transactions(underlying='IBIT')
    
    # Group raw transactions by account
    raw_by_account = {}
    for tx in ibit_raw_txns:
        account = tx.get('account_number', 'UNKNOWN')
        if account not in raw_by_account:
            raw_by_account[account] = []
        raw_by_account[account].append(tx)
    
    print(f"IBIT raw transactions by account:")
    for account, txns in raw_by_account.items():
        print(f"\n  Account {account}: {len(txns)} transactions")
        
        # Look for $61 strike transactions specifically
        strike_61_txns = []
        for tx in txns:
            symbol = tx.get('symbol', '')
            if '61' in symbol and 'Call' in symbol:  # Simplified check
                strike_61_txns.append(tx)
        
        if strike_61_txns:
            print(f"    $61 Call transactions: {len(strike_61_txns)}")
            
            # Show sample transactions
            for tx in strike_61_txns[:3]:
                action = tx.get('action', 'Unknown')
                qty = tx.get('quantity', 0)
                symbol = tx.get('symbol', '')[:30]  # Truncate long symbols
                date = tx.get('executed_at', '')[:10]
                print(f"      {date}: {action} {qty} {symbol}...")
    
    # Look for specific quantities mentioned (150 and 48)
    print(f"\n🎯 Looking for Specific Quantities (150 and 48)")
    print("-" * 40)
    
    for account, txns in raw_by_account.items():
        quantities_found = {}
        for tx in txns:
            qty = tx.get('quantity', 0)
            symbol = tx.get('symbol', '')
            if qty in [150, 48, -150, -48] and 'Call' in symbol and '61' in symbol:
                if qty not in quantities_found:
                    quantities_found[qty] = []
                quantities_found[qty].append({
                    'symbol': symbol,
                    'action': tx.get('action'),
                    'date': tx.get('executed_at', '')[:10],
                    'order_id': tx.get('order_id')
                })
        
        if quantities_found:
            print(f"\n  Account {account} - Target quantities found:")
            for qty, txns_list in quantities_found.items():
                print(f"    Quantity {qty}: {len(txns_list)} transactions")
                for tx_info in txns_list[:2]:  # Show first 2
                    print(f"      {tx_info['date']}: {tx_info['action']} order {tx_info['order_id']}")
    
    print(f"\n" + "=" * 60)
    print("🎯 ACCOUNT ASSIGNMENT ANALYSIS")
    print("=" * 60)
    
    print(f"Issues Identified:")
    print(f"🔍 Need to verify account assignment logic in trade creation")
    print(f"🔍 Check if TransactionMatcher preserves account info correctly")
    print(f"🔍 Verify that specific quantities (150, 48) are properly grouped")

if __name__ == '__main__':
    main()