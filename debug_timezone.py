#!/usr/bin/env python3
"""
Debug timezone handling for RIVN transactions
"""

import sys
import os
from datetime import datetime
import pytz

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient

def debug_timezone():
    client = TastytradeClient()
    if not client.authenticate():
        print("Failed to authenticate")
        return
    
    transactions = client.get_transactions(days_back=30)
    
    # Find RIVN transactions
    rivn_transactions = [tx for tx in transactions if tx.get('underlying_symbol') == 'RIVN']
    
    print("RIVN Transaction Timezone Analysis:")
    print("="*50)
    
    et_tz = pytz.timezone('US/Eastern')
    
    for i, tx in enumerate(rivn_transactions):
        executed_at = tx.get('executed_at', '')
        symbol = tx.get('symbol', '')
        
        print(f"\n{i+1}. Symbol: {symbol}")
        print(f"   Raw timestamp: {executed_at}")
        
        if executed_at:
            # Parse the original timestamp
            dt = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
            print(f"   Parsed UTC: {dt}")
            
            # Convert to Eastern time
            et_dt = dt.astimezone(et_tz)
            print(f"   Eastern time: {et_dt}")
            print(f"   Eastern date: {et_dt.date()}")
            
            # What date should this show?
            print(f"   Expected date: 2025-05-21 or 2025-05-31")

if __name__ == "__main__":
    debug_timezone()