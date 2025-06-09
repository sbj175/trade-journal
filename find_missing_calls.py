#!/usr/bin/env python3
"""
Find the specific missing IBIT $61 calls (150 in Traditional IRA, 48 in Roth IRA)
"""

from src.database.db_manager import DatabaseManager
import json

def main():
    db = DatabaseManager()
    
    print("🔍 Finding Missing IBIT $61 Calls")
    print("=" * 60)
    
    # Get all IBIT raw transactions
    ibit_raw_txns = db.get_raw_transactions(underlying='IBIT')
    
    # Look for $61 strike call transactions
    strike_61_calls = []
    
    for tx in ibit_raw_txns:
        symbol = tx.get('symbol', '')
        if 'C00061000' in symbol:  # $61 call option format
            strike_61_calls.append(tx)
    
    print(f"Found {len(strike_61_calls)} transactions for IBIT $61 calls")
    
    # Group by account
    by_account = {}
    for tx in strike_61_calls:
        account = tx.get('account_number')
        if account not in by_account:
            by_account[account] = []
        by_account[account].append(tx)
    
    print(f"\nIBIT $61 calls by account:")
    
    for account, txns in by_account.items():
        account_name = "Traditional IRA" if account == "5WZ26959" else "Roth IRA" if account == "5WZ28644" else "Individual Margin"
        print(f"\n  {account} ({account_name}): {len(txns)} transactions")
        
        # Calculate net position for this account
        net_position = 0
        transactions_detail = []
        
        for tx in txns:
            qty = tx.get('quantity', 0)
            action = tx.get('action', '')
            date = tx.get('executed_at', '')[:10]
            order_id = tx.get('order_id')
            
            # Calculate net position (negative for short calls)
            if 'SELL' in str(action):
                net_position -= qty
            elif 'BUY' in str(action):
                net_position += qty
            
            transactions_detail.append({
                'date': date,
                'action': action,
                'quantity': qty,
                'order_id': order_id,
                'running_total': net_position
            })
        
        print(f"    Net position: {net_position} (negative = short calls)")
        
        # Show transaction details
        print(f"    Transaction history:")
        for tx_detail in transactions_detail:
            action_str = str(tx_detail['action'])
            print(f"      {tx_detail['date']}: {action_str} {tx_detail['quantity']} (Net: {tx_detail['running_total']}) Order: {tx_detail['order_id']}")
    
    # Check if there are any $61 calls in current trades
    print(f"\n🔍 Current Trades with $61 Calls")
    print("-" * 40)
    
    all_trades = db.get_trades(underlying='IBIT', limit=50)
    
    for trade in all_trades:
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        
        has_61_strike = False
        for leg in option_legs:
            if leg.get('strike') == 61.0:
                has_61_strike = True
                break
        
        if has_61_strike:
            print(f"\n  {trade['trade_id']} ({trade['account_number']}):")
            for leg in option_legs:
                strike = leg.get('strike')
                qty = leg.get('quantity', 0)
                option_type = leg.get('option_type')
                print(f"    {option_type} ${strike} x{abs(qty)} ({'short' if qty < 0 else 'long'})")
    
    # Check if any transactions are not being grouped into trades
    print(f"\n🔍 Checking for Ungrouped Transactions")
    print("-" * 40)
    
    # Get all order IDs for $61 calls
    order_ids_61 = set(tx.get('order_id') for tx in strike_61_calls if tx.get('order_id'))
    print(f"Order IDs with $61 calls: {len(order_ids_61)}")
    
    # Check if these orders are represented in current trades
    all_trade_notes = []
    for trade in all_trades:
        if trade.get('original_notes'):
            all_trade_notes.append(trade['original_notes'])
    
    # This is a simplified check - would need more sophisticated matching
    missing_orders = []
    for order_id in order_ids_61:
        found_in_trades = any(str(order_id) in notes for notes in all_trade_notes)
        if not found_in_trades:
            missing_orders.append(order_id)
    
    if missing_orders:
        print(f"Potentially missing orders: {missing_orders}")
    else:
        print(f"All orders seem to be represented in trades")
    
    print(f"\n" + "=" * 60)
    print("🎯 SUMMARY")
    print("=" * 60)
    
    print(f"Expected positions:")
    print(f"  Traditional IRA (5WZ26959): -150 IBIT $61 calls")
    print(f"  Roth IRA (5WZ28644): -48 IBIT $61 calls")
    
    traditional_net = by_account.get('5WZ26959', [])
    roth_net = by_account.get('5WZ28644', [])
    
    if traditional_net:
        trad_position = sum(-tx.get('quantity', 0) if 'SELL' in str(tx.get('action', '')) else tx.get('quantity', 0) for tx in traditional_net)
        print(f"  Traditional IRA actual: {trad_position}")
    
    if roth_net:
        roth_position = sum(-tx.get('quantity', 0) if 'SELL' in str(tx.get('action', '')) else tx.get('quantity', 0) for tx in roth_net)
        print(f"  Roth IRA actual: {roth_position}")

if __name__ == '__main__':
    main()