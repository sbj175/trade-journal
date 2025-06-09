#!/usr/bin/env python3
"""
Test the fixed stock position calculation
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer

def main():
    db = DatabaseManager()
    raw_txns = db.get_raw_transactions()

    print('🧪 Testing Fixed Stock Position Calculation')
    print('=' * 50)

    # Test the fixed method
    stock_positions = StrategyRecognizer.get_stock_positions(raw_txns)

    print(f'Stock positions detected:')
    has_positions = False
    for symbol, qty in stock_positions.items():
        if qty != 0:
            print(f'  {symbol}: {qty} shares')
            has_positions = True

    if not has_positions:
        print('  ❌ Still no stock positions detected!')

    # Focus on IBIT
    ibit_position = stock_positions.get('IBIT', 0)
    print(f'\n🎯 IBIT position: {ibit_position} shares')

    if ibit_position > 0:
        print('✅ IBIT stock position detected! This should enable covered call recognition.')
    else:
        print('❌ IBIT position still zero.')
        
        # Debug IBIT transactions
        ibit_txns = db.get_raw_transactions(underlying='IBIT')
        stock_txns = []
        for tx in ibit_txns:
            inst_type = str(tx.get('instrument_type', ''))
            if 'EQUITY' in inst_type and 'OPTION' not in inst_type:
                stock_txns.append(tx)
        
        print(f'\nDebug: Found {len(stock_txns)} IBIT stock transactions')
        
        # Manual calculation
        total_bought = 0
        total_sold = 0
        
        for tx in stock_txns:
            qty = tx.get('quantity', 0) or 0
            action = str(tx.get('action', ''))
            
            if 'BUY' in action:
                total_bought += qty
            elif 'SELL' in action:
                total_sold += qty
        
        print(f'Manual calc: {total_bought} bought, {total_sold} sold')
        print(f'Net should be: {total_bought - total_sold}')

    # Test XYL too
    xyl_position = stock_positions.get('XYL', 0)
    print(f'XYL position: {xyl_position} shares')

if __name__ == '__main__':
    main()