#!/usr/bin/env python3
"""
Fix WOLF roll chain management - handle position linking across trades
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_wolf_roll_chain():
    """Fix WOLF roll chain by properly linking closing/opening positions"""
    print("🔄 Fixing WOLF Roll Chain Management")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get WOLF trades
    wolf_trades = db.get_trades(underlying='WOLF', limit=10)
    print(f"WOLF trades found: {len(wolf_trades)}")
    
    # Sort by entry date
    wolf_trades.sort(key=lambda x: x.get('entry_date', ''))
    
    print("\nCurrent state:")
    for trade in wolf_trades:
        print(f"  {trade['trade_id']}: {trade['strategy_type']} - {trade['status']}")
        print(f"    Entry: {trade['entry_date']}, Exit: {trade.get('exit_date', 'None')}")
    
    # Analyze the roll chain
    if len(wolf_trades) >= 2:
        csp_trade = wolf_trades[0]  # Should be the original CSP
        roll_trade = wolf_trades[1]  # Should be the roll
        
        print(f"\nAnalyzing roll chain:")
        print(f"  Original: {csp_trade['trade_id']} ({csp_trade['strategy_type']})")
        print(f"  Roll: {roll_trade['trade_id']} ({roll_trade['strategy_type']})")
        
        # Get details of both trades
        csp_details = db.get_trade_details(csp_trade['trade_id'])
        roll_details = db.get_trade_details(roll_trade['trade_id'])
        
        # Check if roll closes the CSP position
        closes_csp = check_roll_closes_position(csp_details, roll_details)
        
        if closes_csp:
            print(f"  ✅ Roll does close the CSP position")
            
            # Check if roll opens new position
            opens_new = check_roll_opens_position(roll_details)
            
            if opens_new:
                print(f"  ✅ Roll opens new position")
                
                # Apply fixes
                print(f"\nApplying fixes:")
                
                # 1. Mark CSP as ROLLED
                print(f"  1. Updating {csp_trade['trade_id']}: OPEN → ROLLED")
                update_trade_status(db, csp_trade['trade_id'], 'Rolled', roll_trade['entry_date'])
                
                # 2. Mark Roll as OPEN (remove exit date if any)
                print(f"  2. Updating {roll_trade['trade_id']}: CLOSED → OPEN")
                update_trade_status(db, roll_trade['trade_id'], 'Open', None)
                
                print(f"  ✅ Fixes applied successfully")
            else:
                print(f"  ❌ Roll does not open new position")
        else:
            print(f"  ❌ Roll does not close CSP position")
    
    # Verify results
    print(f"\nVerifying results:")
    updated_trades = db.get_trades(underlying='WOLF', limit=10)
    updated_trades.sort(key=lambda x: x.get('entry_date', ''))
    
    for trade in updated_trades:
        print(f"  {trade['trade_id']}: {trade['strategy_type']} - {trade['status']}")
        print(f"    Entry: {trade['entry_date']}, Exit: {trade.get('exit_date', 'None')}")

def check_roll_closes_position(csp_details, roll_details):
    """Check if the roll closes the CSP position"""
    csp_legs = csp_details.get('option_legs', [])
    roll_legs = roll_details.get('option_legs', [])
    
    if not csp_legs or not roll_legs:
        return False
    
    # Get the position opened by CSP (should be STO)
    csp_position = None
    for leg in csp_legs:
        actions = leg.get('transaction_actions', [])
        if 'STO' in actions:
            csp_position = {
                'strike': leg.get('strike'),
                'expiration': leg.get('expiration'),
                'option_type': leg.get('option_type')
            }
            break
    
    if not csp_position:
        return False
    
    # Check if roll has BTC for the same position
    for leg in roll_legs:
        actions = leg.get('transaction_actions', [])
        if 'BTC' in actions:
            if (leg.get('strike') == csp_position['strike'] and
                leg.get('expiration') == csp_position['expiration'] and
                leg.get('option_type') == csp_position['option_type']):
                return True
    
    return False

def check_roll_opens_position(roll_details):
    """Check if the roll opens a new position"""
    roll_legs = roll_details.get('option_legs', [])
    
    for leg in roll_legs:
        actions = leg.get('transaction_actions', [])
        if 'STO' in actions:
            return True
    
    return False

def update_trade_status(db, trade_id, new_status, exit_date):
    """Update trade status in database"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trades 
                SET status = ?, exit_date = ?
                WHERE trade_id = ?
            """, (new_status, exit_date, trade_id))
            conn.commit()
            return True
    except Exception as e:
        print(f"    ❌ Error updating {trade_id}: {e}")
        return False

if __name__ == '__main__':
    fix_wolf_roll_chain()