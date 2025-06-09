#!/usr/bin/env python3
"""
Analyze the new IBIT trades created by the order-based system
"""

from src.database.db_manager import DatabaseManager

def main():
    db = DatabaseManager()
    
    # Get the new IBIT trades with details
    trades = db.get_trades(underlying='IBIT', limit=20)
    
    print(f'New IBIT trade analysis ({len(trades)} trades):')
    
    for trade in trades:
        trade_details = db.get_trade_details(trade['trade_id'])
        print(f'\n{trade["trade_id"]}: {trade["strategy_type"]}')
        print(f'  Entry: {trade["entry_date"]}, Status: {trade["status"]}')
        
        option_legs = trade_details.get('option_legs', [])
        stock_legs = trade_details.get('stock_legs', [])
        
        print(f'  Option legs: {len(option_legs)}')
        for leg in option_legs:
            action = 'BUY' if leg['quantity'] > 0 else 'SELL'
            strike = leg['strike']
            print(f'    {action} {abs(leg["quantity"])} {leg["option_type"]} ${strike} exp {leg["expiration"]}')
        
        print(f'  Stock legs: {len(stock_legs)}')
        for leg in stock_legs:
            action = 'BUY' if leg['quantity'] > 0 else 'SELL'
            print(f'    {action} {abs(leg["quantity"])} shares')
        
        # Show confidence info from original_notes
        if trade.get('original_notes'):
            print(f'  Notes: {trade["original_notes"]}')

if __name__ == '__main__':
    main()