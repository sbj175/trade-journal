#!/usr/bin/env python3

import sqlite3
from collections import defaultdict

# Connect to database
conn = sqlite3.connect('trade_journal.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('=== MANUAL P&L CALCULATION TEST ===')

chain_id = 'IBIT_OPENING_20250609_38851267'
chain_status = 'OPEN'

# Get all positions for this chain (same query as in calculate_chain_realized_pnl)
cursor.execute("""
    SELECT p.symbol, p.opening_action, p.status, p.pnl, p.strike, p.expiration
    FROM positions_new p
    JOIN order_chain_members ocm ON p.order_id = ocm.order_id
    WHERE ocm.chain_id = ?
    ORDER BY p.strike, p.expiration
""", (chain_id,))

positions = cursor.fetchall()

print(f'Found {len(positions)} positions:')
for pos in positions:
    print(f'  {pos["symbol"]}: {pos["opening_action"]}, Status: {pos["status"]}, P&L: ${pos["pnl"]:.2f}')

# Group positions by strike and expiration to find completed round trips
position_groups = defaultdict(list)

for pos in positions:
    symbol, action, status, pnl, strike, expiration = pos
    key = (symbol, strike, expiration)
    position_groups[key].append({
        'action': action,
        'status': status,
        'pnl': pnl
    })

print(f'\nGrouped into {len(position_groups)} position groups:')

realized_pnl = 0.0
unrealized_pnl = 0.0

# Calculate realized and unrealized P&L using the same logic as in order_models.py
for key, group_positions in position_groups.items():
    symbol, strike, expiration = key
    print(f'\nGroup: {symbol} @ ${strike} exp {expiration}')
    
    opening_pnl = 0.0
    closing_pnl = 0.0
    has_opening = False
    has_closing = False
    
    for pos in group_positions:
        print(f'  Action: {pos["action"]}, P&L: ${pos["pnl"]:.2f}')
        if 'TO_OPEN' in pos['action']:
            opening_pnl += pos['pnl']
            has_opening = True
            print(f'    -> Opening P&L: ${pos["pnl"]:.2f}')
        elif 'TO_CLOSE' in pos['action']:
            closing_pnl += pos['pnl']
            has_closing = True
            print(f'    -> Closing P&L: ${pos["pnl"]:.2f}')
    
    print(f'  Has opening: {has_opening}, Has closing: {has_closing}')
    print(f'  Opening P&L: ${opening_pnl:.2f}, Closing P&L: ${closing_pnl:.2f}')
    
    # Realized P&L: positions with both opening and closing
    if has_opening and has_closing:
        group_realized = opening_pnl + closing_pnl
        realized_pnl += group_realized
        print(f'  -> REALIZED P&L: ${group_realized:.2f} (round trip complete)')
    
    # Unrealized P&L: positions with only opening (no matching closing)
    if has_opening and not has_closing:
        unrealized_pnl += opening_pnl
        print(f'  -> UNREALIZED P&L: ${opening_pnl:.2f} (open position)')

print(f'\n=== FINAL RESULTS ===')
print(f'Calculated Realized P&L: ${realized_pnl:.2f}')
print(f'Calculated Unrealized P&L: ${unrealized_pnl:.2f}')
print(f'Total P&L: ${realized_pnl + unrealized_pnl:.2f}')

# Compare with current database values
cursor.execute('SELECT realized_pnl, unrealized_pnl, total_pnl FROM order_chains WHERE chain_id = ?', (chain_id,))
result = cursor.fetchone()
if result:
    print(f'\nCurrent Database Values:')
    print(f'Realized P&L: ${result[0]:.2f}')
    print(f'Unrealized P&L: ${result[1]:.2f}')
    print(f'Total P&L: ${result[2]:.2f}')

conn.close()