#!/usr/bin/env python3

import sqlite3
import sys
import os

# Add the src directory to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.db_manager import DatabaseManager
from models.order_models import OrderManager

# Initialize database manager and order manager
db_manager = DatabaseManager('trade_journal.db')
order_manager = OrderManager(db_manager)

print('=== TESTING P&L CALCULATION METHODS ===')

chain_id = 'IBIT_OPENING_20250609_38851267'
chain_status = 'OPEN'

# Test the realized P&L calculation
print('\n--- Testing calculate_chain_realized_pnl ---')
realized_pnl = order_manager.calculate_chain_realized_pnl(chain_id, chain_status)
print(f'Calculated Realized P&L: ${realized_pnl:.2f}')

# Test the unrealized P&L calculation
print('\n--- Testing calculate_chain_unrealized_pnl ---')
unrealized_pnl = order_manager.calculate_chain_unrealized_pnl(chain_id, chain_status)
print(f'Calculated Unrealized P&L: ${unrealized_pnl:.2f}')

# Update chain P&L and see what happens
print('\n--- Testing update_chain_pnl ---')
total_pnl = order_manager.update_chain_pnl(chain_id)
print(f'Updated Total P&L: ${total_pnl:.2f}')

# Check the database after update
with db_manager.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT realized_pnl, unrealized_pnl, total_pnl FROM order_chains WHERE chain_id = ?', (chain_id,))
    result = cursor.fetchone()
    if result:
        print(f'Database - Realized: ${result[0]:.2f}, Unrealized: ${result[1]:.2f}, Total: ${result[2]:.2f}')

print('\n=== MANUAL CALCULATION FOR COMPARISON ===')

# Let's manually calculate what it should be:
print('\nPositions breakdown:')
print('Opening Order 388512672:')
print('  - BTO 8x $47 calls @ $18.37 = -$14,696 (long position, paid debit)')
print('  - STO 4x $61 calls @ $9.93 = +$3,974 (short position, received credit)')

print('\nClosing Order 397401079:')
print('  - STC 2x $47 calls @ $21.93 = +$4,386 (closing long position, received credit)')
print('  - BTC 1x $61 call @ $11.78 = -$1,178 (closing short position, paid debit)')

print('\nExpected Realized P&L:')
print('  From 2x $47 calls round trip: (-$18.37 + $21.93) * 2 * 100 = +$712')
print('  From 1x $61 call round trip: (+$9.93 - $11.78) * 1 * 100 = -$185')
print('  Total Realized P&L should be: $712 - $185 = $527')

print('\nExpected Unrealized P&L:')
print('  Remaining 6x $47 calls: 6 * $18.37 * 100 = -$11,022')
print('  Remaining 3x $61 calls: 3 * $9.93 * 100 = +$2,979')
print('  Total Unrealized P&L should be: -$11,022 + $2,979 = -$8,043')

print('\nTotal P&L should be: $527 + (-$8,043) = -$7,516')