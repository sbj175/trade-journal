#!/usr/bin/env python3
"""
Analyze SPX expiration behavior in trade journal data
"""

import sqlite3
from datetime import datetime, timedelta
import json

def analyze_spx_expiration():
    """Analyze how SPX expirations are handled"""
    
    print("Analyzing SPX Expiration Behavior")
    print("=" * 50)
    
    conn = sqlite3.connect('trade_journal.db')
    cursor = conn.cursor()
    
    # 1. Check what SPX expiration dates we have in the data
    print("1. SPX Options by Expiration Date:")
    cursor.execute('''
        SELECT 
            ol.expiration,
            COUNT(*) as leg_count,
            COUNT(DISTINCT t.trade_id) as trade_count,
            GROUP_CONCAT(DISTINCT t.status) as statuses
        FROM option_legs ol
        JOIN trades t ON ol.trade_id = t.trade_id
        WHERE ol.underlying = 'SPX'
        GROUP BY ol.expiration
        ORDER BY ol.expiration
    ''')
    
    spx_expirations = cursor.fetchall()
    for exp_date, leg_count, trade_count, statuses in spx_expirations:
        exp_dt = datetime.fromisoformat(exp_date).date()
        is_past = exp_dt < datetime.now().date()
        status_indicator = "🔴 PROBLEM" if is_past and "Open" in statuses else "✅ OK"
        
        print(f"  {exp_date}: {trade_count} trades, {leg_count} legs, Status: {statuses} {status_indicator}")
    
    print()
    
    # 2. Focus on the problematic May 12 trade
    print("2. Detailed Analysis of SPX_20250509_4legs_959:")
    cursor.execute('''
        SELECT 
            t.trade_id,
            t.status,
            t.entry_date,
            t.exit_date,
            ol.expiration,
            ol.option_type,
            ol.strike,
            ol.quantity,
            ol.entry_price,
            ol.exit_price,
            ol.transaction_actions,
            ol.transaction_timestamps
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE t.trade_id = 'SPX_20250509_4legs_959'
        ORDER BY ol.strike, ol.option_type
    ''')
    
    legs = cursor.fetchall()
    if legs:
        trade_info = legs[0]
        print(f"  Trade ID: {trade_info[0]}")
        print(f"  Status: {trade_info[1]}")
        print(f"  Entry Date: {trade_info[2]}")
        print(f"  Exit Date: {trade_info[3] or 'None'}")
        print(f"  Expiration: {trade_info[4]} ({'EXPIRED' if datetime.fromisoformat(trade_info[4]).date() < datetime.now().date() else 'Future'})")
        print()
        
        print("  Option Legs:")
        for i, leg in enumerate(legs):
            actions = leg[10] if leg[10] else "None"
            timestamps = leg[11] if leg[11] else "None"
            exit_price = leg[9] if leg[9] else "None"
            
            print(f"    Leg {i+1}: {leg[7]:+d} {leg[5]} ${leg[6]} exp {leg[4]}")
            print(f"            Entry: ${leg[8]}, Exit: {exit_price}")
            print(f"            Actions: {actions}")
            print(f"            Timestamps: {timestamps}")
            print()
    
    # 3. Check for any SPX transactions that might be expiration-related
    print("3. SPX Raw Transactions Around May 12:")
    cursor.execute('''
        SELECT 
            executed_at,
            symbol,
            action,
            description,
            transaction_sub_type,
            price,
            quantity,
            instrument_type
        FROM raw_transactions 
        WHERE symbol LIKE 'SPX %250512%'
        OR (symbol LIKE 'SPX %' AND executed_at BETWEEN '2025-05-12' AND '2025-05-13')
        ORDER BY executed_at
    ''')
    
    expiry_txs = cursor.fetchall()
    if expiry_txs:
        print(f"  Found {len(expiry_txs)} relevant transactions:")
        for tx in expiry_txs:
            print(f"    {tx[0]}: {tx[1]} | {tx[2]} | {tx[3]}")
            print(f"                     Sub-type: {tx[4]} | Price: ${tx[5]} | Qty: {tx[6]}")
    else:
        print("  ❌ No SPX transactions found around May 12")
        
        # Check if we have ANY transactions on May 12
        cursor.execute('''
            SELECT COUNT(*), MIN(executed_at), MAX(executed_at)
            FROM raw_transactions 
            WHERE executed_at BETWEEN '2025-05-12' AND '2025-05-13'
        ''')
        
        may12_data = cursor.fetchone()
        print(f"  📊 Total transactions on May 12: {may12_data[0]}")
        if may12_data[0] > 0:
            print(f"      Time range: {may12_data[1]} to {may12_data[2]}")
    
    print()
    
    # 4. Compare with other expired options to see the pattern
    print("4. How Other Expired Options Were Handled:")
    cursor.execute('''
        SELECT 
            t.trade_id,
            ol.underlying,
            ol.expiration,
            t.status,
            ol.transaction_actions,
            COUNT(*) as leg_count
        FROM trades t
        JOIN option_legs ol ON t.trade_id = ol.trade_id
        WHERE ol.expiration < date('now', '-7 days')  -- Expired more than a week ago
        AND ol.underlying != 'SPX'  -- Non-SPX for comparison
        GROUP BY t.trade_id, ol.expiration
        ORDER BY ol.expiration DESC
        LIMIT 5
    ''')
    
    other_expired = cursor.fetchall()
    if other_expired:
        print("  Recent expired non-SPX trades for comparison:")
        for trade_id, underlying, exp_date, status, actions, leg_count in other_expired:
            print(f"    {trade_id}: {underlying} exp {exp_date} | Status: {status}")
            print(f"                     Actions: {actions}")
    else:
        print("  No other expired options found for comparison")
    
    print()
    
    # 5. Summary and recommendations
    print("5. ANALYSIS SUMMARY:")
    print("-" * 30)
    
    may12_exp = datetime(2025, 5, 12).date()
    today = datetime.now().date()
    days_since_exp = (today - may12_exp).days
    
    print(f"📅 May 12, 2025 was {days_since_exp} days ago")
    print(f"🎯 Trade SPX_20250509_4legs_959 shows as 'Open' but options expired")
    print(f"❌ No expiration transactions found in database")
    
    print("\n🔍 POSSIBLE EXPLANATIONS:")
    print("1. SPX is cash-settled - no physical delivery or traditional 'exercise'")
    print("2. Tastytrade may not record expiration events as transactions for SPX")
    print("3. Settlement might be recorded differently (account adjustment vs transaction)")
    print("4. The sync period might not have captured settlement events")
    print("5. Options might have expired worthless (no cash settlement needed)")
    
    print("\n📋 NEXT STEPS:")
    print("1. Check your Tastytrade account directly for this trade")
    print("2. Look for cash settlement entries or account adjustments on May 12")
    print("3. Verify if the position shows as closed in Tastytrade")
    print("4. If closed in TT but open here, we need to implement auto-expiration logic")
    
    conn.close()

if __name__ == "__main__":
    analyze_spx_expiration()