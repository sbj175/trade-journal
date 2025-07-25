#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager

db = DatabaseManager()
positions = db.get_open_positions()

print(f'Total positions: {len(positions)}')

# Check positions with opening dates
with_dates = [p for p in positions if p.get('opened_at')]
print(f'Positions with opening dates: {len(with_dates)}')

# Check multi-leg positions
from collections import defaultdict

positions_by_underlying = defaultdict(list)
for pos in positions:
    underlying = pos.get('underlying') or pos.get('symbol')
    if underlying:
        positions_by_underlying[underlying].append(pos)

# Find multi-leg positions
multi_leg = [(u, ps) for u, ps in positions_by_underlying.items() if len(ps) >= 2]
print(f'\nMulti-leg positions: {len(multi_leg)} groups')

for underlying, positions in multi_leg[:3]:  # Show first 3
    print(f'\n{underlying}: {len(positions)} legs')
    for pos in positions:
        print(f"  - {pos.get('symbol')}: opened_at={pos.get('opened_at')}")