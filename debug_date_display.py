#!/usr/bin/env python3
"""
Debug how dates are being stored and displayed
"""

import sys
import os
from datetime import datetime
import pytz

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.api.tastytrade_client import TastytradeClient

def debug_date_display():
    print("=== Debugging Date Storage and Display ===")
    
    # Check raw API data
    client = TastytradeClient()
    if not client.authenticate():
        print("Failed to authenticate")
        return
    
    transactions = client.get_transactions(days_back=30)
    rivn_transactions = [tx for tx in transactions if tx.get('underlying_symbol') == 'RIVN']
    
    print("1. Raw API timestamps:")
    for tx in rivn_transactions[:2]:  # Just first 2
        executed_at = tx.get('executed_at', '')
        symbol = tx.get('symbol', '')
        print(f"   {symbol}: {executed_at}")
        
        # Parse and convert
        if executed_at:
            dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
            et_tz = pytz.timezone('US/Eastern')
            et_dt = dt.astimezone(et_tz)
            print(f"     UTC: {dt}")
            print(f"     Eastern: {et_dt}")
            print(f"     Date: {et_dt.date()}")
    
    # Check database storage
    print("\n2. Database storage:")
    db = DatabaseManager()
    rivn_trades = db.get_trades(underlying='RIVN', limit=5)
    
    for trade in rivn_trades:
        print(f"   Trade ID: {trade['trade_id']}")
        print(f"   Entry date in DB: {trade['entry_date']} (type: {type(trade['entry_date'])})")
        print(f"   Exit date in DB: {trade['exit_date']} (type: {type(trade['exit_date'])})")
    
    # Check what API returns
    print("\n3. API endpoint returns:")
    import requests
    try:
        response = requests.get('http://localhost:8000/api/trades?underlying=RIVN')
        if response.status_code == 200:
            data = response.json()
            for trade in data['trades'][:1]:
                print(f"   API Trade ID: {trade['trade_id']}")
                print(f"   API Entry date: {trade['entry_date']}")
                print(f"   API Exit date: {trade['exit_date']}")
        else:
            print(f"   API request failed: {response.status_code}")
    except Exception as e:
        print(f"   API request error: {e}")

if __name__ == "__main__":
    debug_date_display()