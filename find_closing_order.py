#!/usr/bin/env python3
"""
Find the closing order for the GME position
"""
import sqlite3

conn = sqlite3.connect("trade_journal.db")
cursor = conn.cursor()

print("=== Looking for GME closing orders ===\n")

# Find GME positions that should be closed
cursor.execute("""
SELECT DISTINCT p.symbol, p.underlying, p.quantity, p.opening_action, p.strike, p.expiration
FROM positions_new p
WHERE p.underlying = 'GME' 
AND p.closing_action IS NULL
AND p.status != 'CLOSED'
""")

open_positions = cursor.fetchall()
print(f"Found {len(open_positions)} open GME positions:")
for pos in open_positions:
    print(f"  {pos[0]}: {pos[2]} contracts, {pos[3]}, Strike ${pos[4]}, Exp {pos[5]}")

print("\n" + "="*60)

# Look for orders around the same time that might be closing orders
print("\nLooking for recent GME orders that might be closing orders...")
cursor.execute("""
SELECT o.order_id, o.order_date, o.status, o.order_type, o.total_quantity,
       COUNT(p.position_id) as position_count
FROM orders o
LEFT JOIN positions_new p ON o.order_id = p.order_id
WHERE o.underlying = 'GME'
AND o.order_date >= '2025-03-20'
GROUP BY o.order_id
ORDER BY o.order_date DESC
""")

recent_orders = cursor.fetchall()
print(f"Found {len(recent_orders)} recent GME orders:")
for order in recent_orders:
    print(f"  Order {order[0]}: {order[1]} - {order[2]} - {order[3]} - Qty: {order[4]} - Positions: {order[5]}")
    
    # Show positions for each order
    cursor.execute("""
    SELECT symbol, quantity, opening_action, closing_action, status
    FROM positions_new
    WHERE order_id = ?
    """, (order[0],))
    
    positions = cursor.fetchall()
    for pos in positions:
        print(f"    Position: {pos[0]} - Qty: {pos[1]} - Open: {pos[2]} - Close: {pos[3]} - Status: {pos[4]}")

print("\n" + "="*60)

# Look for transactions that might be related
print("\nLooking for GME transactions with SELL actions...")
cursor.execute("""
SELECT DISTINCT opening_action, closing_action, COUNT(*) as count
FROM positions_new
WHERE underlying = 'GME'
GROUP BY opening_action, closing_action
ORDER BY count DESC
""")

actions = cursor.fetchall()
print("GME position action types:")
for action in actions:
    print(f"  Open: {action[0]}, Close: {action[1]}, Count: {action[2]}")

conn.close()