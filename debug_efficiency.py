#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from collections import defaultdict
from datetime import datetime

db = DatabaseManager()
positions = db.get_open_positions()

# Group positions by underlying
positions_by_underlying = defaultdict(list)
for pos in positions:
    underlying = pos.get('underlying') or pos.get('symbol')
    if underlying:
        positions_by_underlying[underlying].append(pos)

# Strategy recognition logic from the frontend
def get_strategy_label(positions):
    option_positions = [p for p in positions if p.get('instrument_type') and 'OPTION' in p['instrument_type']]
    stock_positions = [p for p in positions if p.get('instrument_type') and 'EQUITY' in p['instrument_type'] and 'OPTION' not in p['instrument_type']]
    
    if len(option_positions) == 2:
        # Could be a spread
        return "Two-Leg Strategy"
    elif len(option_positions) == 3:
        return "Butterfly"
    elif len(option_positions) == 4:
        return "Four-Leg Strategy"
    else:
        return "Other"

# Check which are eligible for efficiency ratio
defined_risk_strategies = [
    'Bull Put Spread', 'Bear Call Spread', 
    'Bull Call Spread', 'Bear Put Spread',
    'Butterfly', 'Iron Butterfly', 'Iron Condor'
]

print("Analyzing position groups for efficiency ratio eligibility:\n")

for underlying, positions in positions_by_underlying.items():
    if len(positions) >= 2:  # Multi-leg positions only
        option_positions = [p for p in positions if p.get('instrument_type') and 'OPTION' in p['instrument_type']]
        
        if len(option_positions) >= 2:
            strategy = get_strategy_label(positions)
            has_dates = all(p.get('opened_at') for p in option_positions)
            
            print(f"{underlying}:")
            print(f"  Strategy: {strategy}")
            print(f"  Option legs: {len(option_positions)}")
            print(f"  All have opening dates: {has_dates}")
            
            for pos in option_positions:
                symbol = pos.get('symbol')
                opened_at = pos.get('opened_at')
                expires_at = pos.get('expires_at')
                print(f"    - {symbol}")
                print(f"      opened_at: {opened_at}")
                print(f"      expires_at: {expires_at}")
            print()