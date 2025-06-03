#!/usr/bin/env python3
from src.database.db_manager import DatabaseManager

db = DatabaseManager()
print(f'Total trades: {db.get_trade_count()}')
print(f'Open trades: {db.get_trade_count(status="Open")}')
print(f'Closed trades: {db.get_trade_count(status="Closed")}')
print(f'\nRecent trades:')
trades = db.get_trades(limit=5)
for trade in trades:
    print(f'  {trade["trade_id"]}: {trade["underlying"]} - {trade["strategy_type"]} - {trade["status"]} - P&L: ${trade["current_pnl"]}')

print(f'\nPositions:')
positions = db.get_open_positions()
print(f'Total positions: {len(positions)}')
for pos in positions[:5]:
    pnl = pos.get("unrealized_pnl", 0)
    if pnl is None:
        pnl = 0
    print(f'  {pos["symbol"]} - Qty: {pos["quantity"]} - P&L: ${pnl:.2f} - Market Value: ${pos.get("market_value", 0):.2f}')