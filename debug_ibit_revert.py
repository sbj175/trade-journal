#!/usr/bin/env python3
"""
Debug why IBIT trades reverted to old state
"""

from src.database.db_manager import DatabaseManager

def main():
    db = DatabaseManager()
    
    # Check when trades were last updated
    trades = db.get_trades(underlying='IBIT', limit=50)
    
    print(f'Current IBIT trades: {len(trades)}')
    print()
    
    recent_updates = []
    for trade in trades:
        updated_at = trade.get('updated_at', trade.get('created_at', 'Unknown'))
        recent_updates.append((trade['trade_id'], trade['strategy_type'], updated_at))
    
    # Sort by update time
    recent_updates.sort(key=lambda x: x[2] if x[2] != 'Unknown' else '1900-01-01', reverse=True)
    
    print('Most recently updated trades:')
    for trade_id, strategy, updated_at in recent_updates[:10]:
        print(f'  {trade_id}: {strategy} - Updated: {updated_at}')
    
    # Check if our test trades exist
    diagonal_trades = [t for t in trades if 'Diagonal' in t['strategy_type']]
    print(f'\nDiagonal Spread trades: {len(diagonal_trades)}')
    for trade in diagonal_trades:
        print(f'  {trade["trade_id"]}: {trade["strategy_type"]}')
    
    # Check raw transactions status
    raw_txns = db.get_raw_transactions(underlying='IBIT')
    print(f'\nRaw IBIT transactions: {len(raw_txns)}')
    
    # Check if there are any 2-leg trades that might be our new ones
    two_leg_trades = [t for t in trades if '_2legs' in t['trade_id']]
    print(f'\n2-leg trades: {len(two_leg_trades)}')
    for trade in two_leg_trades:
        print(f'  {trade["trade_id"]}: {trade["strategy_type"]} - {trade.get("updated_at", "N/A")}')

if __name__ == '__main__':
    main()