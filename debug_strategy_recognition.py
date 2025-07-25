#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from collections import defaultdict
from datetime import datetime

db = DatabaseManager()
positions = db.get_open_positions()

# Group positions by underlying and account
positions_by_underlying_account = defaultdict(list)
for pos in positions:
    underlying = pos.get('underlying') or pos.get('symbol')
    account = pos.get('account_number')
    key = f"{underlying}_{account}"
    if underlying:
        positions_by_underlying_account[key].append(pos)

# Detailed strategy recognition logic from the frontend
def get_detailed_strategy(positions):
    option_positions = [p for p in positions if p.get('instrument_type') and 'OPTION' in p['instrument_type']]
    
    if len(option_positions) == 2:
        # Get strikes and types
        strikes = []
        types = []
        for p in option_positions:
            strikes.append(p.get('strike_price'))
            types.append(p.get('option_type'))
        
        # Check if same type (vertical spread) or different (straddle/strangle)
        if types[0] == types[1]:
            if None not in strikes and strikes[0] != strikes[1]:
                if types[0] == 'C':
                    return "Call Spread (Vertical)"
                else:
                    return "Put Spread (Vertical)"
        else:
            if strikes[0] == strikes[1]:
                return "Straddle"
            else:
                return "Strangle"
                
    elif len(option_positions) == 4:
        # Check for Iron Condor pattern
        puts = [p for p in option_positions if p.get('option_type') == 'P']
        calls = [p for p in option_positions if p.get('option_type') == 'C']
        
        if len(puts) == 2 and len(calls) == 2:
            return "Iron Condor"
        elif len(puts) == 4 or len(calls) == 4:
            return "Iron Butterfly"
            
    return f"{len(option_positions)}-leg strategy"

# Check specific positions
for underlying in ['AVGO', 'GLD', 'QQQ', 'USO']:
    print(f"\n{'='*60}")
    print(f"Analyzing {underlying}:")
    print(f"{'='*60}")
    
    # Find all entries for this underlying
    for key, positions in positions_by_underlying_account.items():
        if key.startswith(f"{underlying}_"):
            account = key.split('_')[1]
            option_positions = [p for p in positions if p.get('instrument_type') and 'OPTION' in p['instrument_type']]
            
            if len(option_positions) >= 2:
                print(f"\nAccount: {account}")
                print(f"Total positions: {len(positions)} ({len(option_positions)} options)")
                print(f"Strategy Type: {get_detailed_strategy(positions)}")
                
                # Check data completeness
                all_have_opened = all(p.get('opened_at') for p in option_positions)
                all_have_expires = all(p.get('expires_at') for p in option_positions)
                
                print(f"All have opened_at: {all_have_opened}")
                print(f"All have expires_at: {all_have_expires}")
                
                print("\nPosition details:")
                for p in option_positions:
                    symbol = p.get('symbol')
                    strike = p.get('strike_price')
                    opt_type = p.get('option_type')
                    opened = p.get('opened_at')
                    expires = p.get('expires_at')
                    quantity = p.get('quantity')
                    
                    print(f"  {symbol}:")
                    print(f"    Type: {opt_type}, Strike: {strike}, Qty: {quantity}")
                    print(f"    Opened: {opened[:10] if opened else 'None'}")
                    print(f"    Expires: {expires[:10] if expires else 'None'}")