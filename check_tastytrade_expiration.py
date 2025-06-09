#!/usr/bin/env python3
"""
Check Tastytrade data for SPX expiration events
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from datetime import datetime, timedelta
import json

def check_spx_expiration_data():
    """Check Tastytrade for SPX expiration data around May 12, 2025"""
    
    print("Checking Tastytrade for SPX expiration events...")
    print("=" * 60)
    
    # Initialize client
    client = TastytradeClient()
    
    # Authenticate
    if not client.authenticate():
        print("❌ Failed to authenticate with Tastytrade")
        return
    
    print("✅ Successfully authenticated with Tastytrade")
    print()
    
    # Get transactions for a wider period around May 12
    print("Fetching transactions from May 1-20, 2025...")
    try:
        # Fetch transactions for a 20-day period around expiration
        transactions = client.get_transactions(days_back=60)  # Go back far enough to cover May
        
        print(f"📊 Total transactions fetched: {len(transactions)}")
        print()
        
        # Filter for SPX transactions around May 12
        spx_transactions = []
        target_date = datetime(2025, 5, 12)
        
        for tx in transactions:
            # Check if it's an SPX transaction
            symbol = tx.get('symbol', '')
            if symbol.startswith('SPX '):
                executed_at = tx.get('executed_at', '')
                if executed_at:
                    try:
                        tx_date = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                        # Include transactions from May 10-14 (around expiration)
                        if datetime(2025, 5, 10) <= tx_date <= datetime(2025, 5, 14):
                            spx_transactions.append(tx)
                    except:
                        continue
        
        print(f"🎯 SPX transactions around May 12: {len(spx_transactions)}")
        print()
        
        if spx_transactions:
            print("SPX Transactions found:")
            print("-" * 80)
            
            # Group by date and show details
            by_date = {}
            for tx in spx_transactions:
                executed_at = tx.get('executed_at', '')
                if executed_at:
                    tx_date = datetime.fromisoformat(executed_at.replace('Z', '+00:00')).date()
                    if tx_date not in by_date:
                        by_date[tx_date] = []
                    by_date[tx_date].append(tx)
            
            for date in sorted(by_date.keys()):
                print(f"\n📅 {date} ({len(by_date[date])} transactions):")
                
                for tx in by_date[date]:
                    symbol = tx.get('symbol', '')
                    action = tx.get('action', '')
                    description = tx.get('description', '')
                    sub_type = tx.get('transaction_sub_type', '')
                    price = tx.get('price', 0)
                    quantity = tx.get('quantity', 0)
                    executed_at = tx.get('executed_at', '')
                    
                    print(f"  Time: {executed_at}")
                    print(f"  Symbol: {symbol}")
                    print(f"  Action: {action}")
                    print(f"  Description: {description}")
                    print(f"  Sub-type: {sub_type}")
                    print(f"  Price: ${price}, Qty: {quantity}")
                    print(f"  Raw TX: {json.dumps(tx, indent=2)}")
                    print("  " + "-" * 70)
        
        else:
            print("❌ No SPX transactions found around May 12, 2025")
            print()
            print("🔍 This could mean:")
            print("1. Expiration events are not recorded as transactions in Tastytrade")
            print("2. Cash-settled index options (SPX) don't show expiration transactions")
            print("3. The trade is still actually open (positions weren't auto-exercised)")
            print("4. Expiration events are recorded differently in the API")
            print()
            
            # Check if we have ANY SPX transactions at all
            all_spx = [tx for tx in transactions if tx.get('symbol', '').startswith('SPX ')]
            print(f"📈 Total SPX transactions in data: {len(all_spx)}")
            
            if all_spx:
                # Show date range of SPX data
                dates = []
                for tx in all_spx:
                    executed_at = tx.get('executed_at', '')
                    if executed_at:
                        try:
                            tx_date = datetime.fromisoformat(executed_at.replace('Z', '+00:00')).date()
                            dates.append(tx_date)
                        except:
                            continue
                
                if dates:
                    dates.sort()
                    print(f"📊 SPX data range: {dates[0]} to {dates[-1]}")
        
        # Now check current positions to see if these options still exist
        print("\n" + "=" * 60)
        print("Checking current positions for SPX options...")
        
        try:
            positions = client.get_positions()
            
            spx_positions = []
            for account_number, account_positions in positions.items():
                for pos in account_positions:
                    symbol = pos.get('symbol', '')
                    if symbol.startswith('SPX ') and '250512' in symbol:  # May 12 expiry
                        spx_positions.append((account_number, pos))
            
            if spx_positions:
                print(f"🚨 Found {len(spx_positions)} SPX May 12 positions still open:")
                for account, pos in spx_positions:
                    print(f"  Account: {account}")
                    print(f"  Symbol: {pos.get('symbol', '')}")
                    print(f"  Quantity: {pos.get('quantity', 0)}")
                    print(f"  Market Value: ${pos.get('market_value', 0)}")
                    print()
            else:
                print("✅ No SPX May 12 positions found in current positions")
                print("   This confirms the options have expired/been settled")
        
        except Exception as e:
            print(f"❌ Error checking positions: {e}")
    
    except Exception as e:
        print(f"❌ Error fetching transactions: {e}")
        return

if __name__ == "__main__":
    check_spx_expiration_data()