#!/usr/bin/env python3
"""
Debug RIVN trades to see why they're not grouping correctly
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.trade_strategy import StrategyRecognizer
import json
from datetime import datetime

def debug_rivn_trades():
    # Initialize and authenticate
    client = TastytradeClient()
    if not client.authenticate():
        print("Failed to authenticate")
        return
    
    print("Fetching transactions...")
    transactions = client.get_transactions(days_back=30)
    
    # Filter RIVN transactions
    rivn_transactions = []
    for tx in transactions:
        underlying = tx.get('underlying_symbol', '')
        if underlying == 'RIVN':
            rivn_transactions.append(tx)
    
    print(f"\nFound {len(rivn_transactions)} RIVN transactions:")
    
    # Print all RIVN transactions
    for i, tx in enumerate(rivn_transactions):
        executed_at = tx.get('executed_at', '')
        symbol = tx.get('symbol', '')
        action = tx.get('action', '')
        description = tx.get('description', '')
        quantity = tx.get('quantity', '')
        price = tx.get('price', '')
        
        print(f"\n{i+1}. Date: {executed_at}")
        print(f"   Symbol: {symbol}")
        print(f"   Action: {action}")
        print(f"   Description: {description}")
        print(f"   Quantity: {quantity}")
        print(f"   Price: {price}")
        
        # Check if it's a closing transaction
        is_closing = StrategyRecognizer._is_closing_transaction(tx)
        print(f"   Is Closing: {is_closing}")
    
    # Process into trades
    print(f"\n{'='*50}")
    print("Processing into trades...")
    
    trades = StrategyRecognizer.group_transactions_into_trades(rivn_transactions)
    
    print(f"\nCreated {len(trades)} trades:")
    for i, trade in enumerate(trades):
        print(f"\n{i+1}. Trade ID: {trade.trade_id}")
        print(f"   Strategy: {trade.strategy_type.value}")
        print(f"   Status: {trade.status.value}")
        print(f"   Entry Date: {trade.entry_date}")
        print(f"   Exit Date: {trade.exit_date}")
        print(f"   Option Legs: {len(trade.option_legs)}")
        
        for j, leg in enumerate(trade.option_legs):
            print(f"     Leg {j+1}: {leg.symbol} | Qty: {leg.quantity} | Entry: ${leg.entry_price} | Exit: ${leg.exit_price}")
    
    # Save detailed output
    with open('rivn_debug.json', 'w') as f:
        json.dump({
            'transactions': rivn_transactions,
            'trades_count': len(trades)
        }, f, indent=2, default=str)
    
    print(f"\nDetailed data saved to rivn_debug.json")

if __name__ == "__main__":
    debug_rivn_trades()