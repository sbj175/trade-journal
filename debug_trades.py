#!/usr/bin/env python3
"""
Debug script to check trade processing
"""

import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.trade_manager import TradeManager, StrategyRecognizer

def debug_transactions():
    """Debug transaction processing"""
    
    print("=== TRADE PROCESSING DEBUG ===\n")
    
    # Get transactions
    print("1. Fetching transactions...")
    client = TastytradeClient()
    if not client.authenticate():
        print("❌ Authentication failed")
        return
    
    transactions = client.get_transactions(days_back=30)
    print(f"✓ Found {len(transactions)} transactions")
    
    # Filter for relevant transactions
    print("\n2. Analyzing transaction types...")
    equity_options = []
    equities = []
    other = []
    
    instrument_types_seen = set()
    
    for tx in transactions:
        instrument_type = str(tx.get('instrument_type') or 'Unknown')
        instrument_types_seen.add(instrument_type)
        
        if 'EQUITY_OPTION' in instrument_type:
            equity_options.append(tx)
        elif 'InstrumentType.EQUITY' == instrument_type:
            equities.append(tx)
        else:
            other.append(tx)
    
    print(f"   Instrument types found: {sorted(instrument_types_seen)}")
    
    print(f"   Equity Options: {len(equity_options)}")
    print(f"   Equities: {len(equities)}")
    print(f"   Other: {len(other)}")
    
    if equity_options:
        print("\n   Sample option transaction:")
        sample = equity_options[0]
        for key, value in sample.items():
            print(f"     {key}: {value}")
    
    # Test option symbol parsing
    print("\n3. Testing option symbol parsing...")
    for tx in equity_options[:3]:  # Test first 3
        symbol = tx.get('symbol', '')
        parsed = StrategyRecognizer.parse_option_symbol(symbol)
        print(f"   Symbol: {symbol}")
        print(f"   Parsed: {parsed}")
        print()
    
    # Test trade grouping
    print("4. Testing trade grouping...")
    trades = StrategyRecognizer.group_transactions_into_trades(transactions)
    print(f"✓ Created {len(trades)} trades")
    
    if trades:
        print("\n   Sample trade:")
        trade = trades[0]
        print(f"     ID: {trade.trade_id}")
        print(f"     Underlying: {trade.underlying}")
        print(f"     Strategy: {trade.strategy_type}")
        print(f"     Option Legs: {len(trade.option_legs)}")
        print(f"     Stock Legs: {len(trade.stock_legs)}")
        print(f"     Status: {trade.status}")
        
        if trade.option_legs:
            print("     Option Leg Details:")
            for i, leg in enumerate(trade.option_legs):
                print(f"       {i+1}. {leg.symbol} | Qty: {leg.quantity} | Price: ${leg.entry_price}")
    
    # Test trade manager
    print("\n5. Testing trade manager...")
    manager = TradeManager()
    processed_trades = manager.process_transactions(transactions)
    print(f"✓ Trade manager processed {len(processed_trades)} trades")
    
    # Test export format
    print("\n6. Testing export format...")
    export_data = manager.export_for_sheets()
    
    print(f"   Trades data rows: {len(export_data.get('trades', []))}")
    print(f"   Trade legs data rows: {len(export_data.get('trade_legs', []))}")
    
    if export_data.get('trades') and len(export_data['trades']) > 1:
        print("\n   Sample trades export row:")
        headers = export_data['trades'][0]
        sample_row = export_data['trades'][1]
        for header, value in zip(headers, sample_row):
            print(f"     {header}: {value}")
    
    print("\n=== DEBUG COMPLETE ===")

if __name__ == "__main__":
    debug_transactions()