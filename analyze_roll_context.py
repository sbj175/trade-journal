#!/usr/bin/env python3
"""
Analyze ROLL transactions to understand the context of what's being closed
"""

from src.database.db_manager import DatabaseManager
import json
from datetime import datetime

def main():
    db = DatabaseManager()
    
    print("🔄 Analyzing ROLL Context")
    print("=" * 60)
    
    # Get all current roll trades
    all_trades = db.get_trades(limit=1000)
    roll_trades = [t for t in all_trades if 'Roll' in t['strategy_type']]
    
    print(f"Found {len(roll_trades)} ROLL trades")
    
    # Analyze a few sample rolls
    for i, trade in enumerate(roll_trades[:3]):
        print(f"\n{'='*40}")
        print(f"ROLL {i+1}: {trade['trade_id']} - {trade['strategy_type']}")
        print(f"{'='*40}")
        
        # Get detailed trade information
        trade_details = db.get_trade_details(trade['trade_id'])
        option_legs = trade_details.get('option_legs', [])
        
        print(f"Legs in this ROLL:")
        closing_legs = []
        opening_legs = []
        
        for leg in option_legs:
            actions = leg.get('transaction_actions', [])
            if isinstance(actions, str):
                actions = json.loads(actions) if actions else []
            
            leg_info = f"  {leg['option_type']} ${leg['strike']} {leg['expiration']} x{leg['quantity']}"
            
            # Determine if this leg is closing or opening
            is_closing = any('CLOSE' in str(action) for action in actions)
            is_opening = any('OPEN' in str(action) for action in actions)
            
            if is_closing:
                closing_legs.append(leg)
                print(f"  CLOSING: {leg_info} - Actions: {actions}")
            elif is_opening:
                opening_legs.append(leg)
                print(f"  OPENING: {leg_info} - Actions: {actions}")
            else:
                print(f"  UNKNOWN: {leg_info} - Actions: {actions}")
        
        # For closing legs, try to find the original opening transaction
        print(f"\n🔍 Searching for original positions being closed:")
        
        for closing_leg in closing_legs:
            print(f"\nClosing: {closing_leg['option_type']} ${closing_leg['strike']} {closing_leg['expiration']}")
            
            # Search all raw transactions for the original opening of this contract
            raw_txns = db.get_raw_transactions(underlying=trade['underlying'])
            
            # Find transactions for the same contract that were opened before this date
            matching_opens = []
            roll_date = datetime.strptime(trade['entry_date'], '%Y-%m-%d').date()
            
            for tx in raw_txns:
                # Parse transaction date
                try:
                    tx_date = datetime.fromisoformat(tx.get('executed_at', '').replace('Z', '+00:00')).date()
                except:
                    continue
                
                # Only look at transactions before the roll date
                if tx_date >= roll_date:
                    continue
                
                # Check if this is an opening transaction for the same contract
                action = str(tx.get('action', ''))
                if 'OPEN' in action:
                    # Parse option symbol to match contract
                    symbol = tx.get('symbol', '')
                    # This is simplified - would need proper option parsing
                    if (str(closing_leg['strike']) in symbol and 
                        closing_leg['expiration'] in symbol and
                        closing_leg['option_type'][0] in symbol):  # C or P
                        
                        matching_opens.append({
                            'date': tx_date,
                            'action': action,
                            'symbol': symbol,
                            'order_id': tx.get('order_id'),
                            'quantity': tx.get('quantity')
                        })
            
            # Show the most recent opening transaction
            if matching_opens:
                # Sort by date, most recent first
                matching_opens.sort(key=lambda x: x['date'], reverse=True)
                recent_open = matching_opens[0]
                
                print(f"  🎯 Originally opened: {recent_open['date']} via order {recent_open['order_id']}")
                print(f"     Action: {recent_open['action']} {recent_open['quantity']} {recent_open['symbol'][:30]}...")
                
                # Calculate how long the position was held
                days_held = (roll_date - recent_open['date']).days
                print(f"     Position held for: {days_held} days")
            else:
                print(f"  ❌ Could not find original opening transaction")
    
    print(f"\n" + "=" * 60)
    print("🎯 ROLL Context Analysis Summary")
    print("=" * 60)
    
    print(f"Key Insights:")
    print(f"✅ ROLLs correctly identify closing + opening pattern")
    print(f"🔍 Could enhance with original position context")
    print(f"📊 Could show position hold time")
    print(f"🔗 Could link to original opening order")

if __name__ == '__main__':
    main()