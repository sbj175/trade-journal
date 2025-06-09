#!/usr/bin/env python3
"""
Test script to verify the covered call detection fix
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyType

def fix_covered_call_detection(trades, db):
    """
    Post-process trades to detect covered calls based on current positions.
    
    This fixes cases where short calls were not grouped with their covering stock
    due to timing or grouping algorithm limitations.
    """
    fixed_trades = []
    
    for trade in trades:
        # Only check naked call trades with single option legs
        if (trade.strategy_type == StrategyType.NAKED_CALL and 
            len(trade.option_legs) == 1 and 
            len(trade.stock_legs) == 0):
            
            option_leg = trade.option_legs[0]
            
            # Check if this is a short call
            if option_leg.is_short and option_leg.option_type == 'Call':
                # Get current positions for this underlying and account
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT quantity, quantity_direction
                            FROM positions 
                            WHERE underlying = ? 
                            AND account_number = ?
                            AND instrument_type LIKE '%EQUITY%'
                            AND instrument_type NOT LIKE '%OPTION%'
                        ''', (trade.underlying, trade.account_number))
                        
                        position = cursor.fetchone()
                        
                        if position:
                            shares = position[0] if position[0] else 0
                            direction = position[1] if position[1] else ''
                            
                            # Check if this is a long stock position
                            if shares > 0 and 'LONG' in direction.upper():
                                contracts = abs(option_leg.quantity)
                                shares_needed = contracts * 100
                                
                                # If we have enough shares to cover the calls
                                if shares >= shares_needed:
                                    print(f"Converting {trade.trade_id} from Naked Call to Covered Call "
                                          f"(has {shares} shares, needs {shares_needed})")
                                    trade.strategy_type = StrategyType.COVERED_CALL
                                else:
                                    print(f"Keeping {trade.trade_id} as Naked Call "
                                          f"(has {shares} shares, needs {shares_needed})")
                        
                except Exception as e:
                    print(f"Error checking positions for trade {trade.trade_id}: {e}")
        
        fixed_trades.append(trade)
    
    return fixed_trades

def test_fix():
    """Test the covered call fix on the MSTR trade"""
    
    # Initialize database
    db = DatabaseManager()
    
    # Get the specific MSTR trade with full details
    trade_data = db.get_trade_details('MSTR_20250327_1legs_644')
    
    if not trade_data:
        print("MSTR trade not found!")
        return
    print(f"Found trade: {trade_data['trade_id']}")
    print(f"Current strategy: {trade_data['strategy_type']}")
    print(f"Account: {trade_data['account_number']}")
    print(f"Trade data keys: {list(trade_data.keys())}")
    
    # Convert to Trade object for testing
    from src.models.trade_strategy import Trade, OptionLeg, StrategyType, TradeStatus
    from datetime import date
    
    trade = Trade(
        trade_id=trade_data['trade_id'],
        underlying=trade_data['underlying'],
        strategy_type=StrategyType(trade_data['strategy_type']),
        entry_date=date.fromisoformat(trade_data['entry_date']),
        account_number=trade_data['account_number'],
        status=TradeStatus(trade_data['status'])
    )
    
    # Get option legs from trade data (they should be included)
    if 'option_legs' in trade_data:
        for leg_data in trade_data['option_legs']:
            leg = OptionLeg(
                symbol=leg_data['symbol'],
                underlying=leg_data['underlying'],
                option_type=leg_data['option_type'],
                strike=leg_data['strike'],
                expiration=date.fromisoformat(leg_data['expiration']),
                quantity=leg_data['quantity'],
                entry_price=leg_data['entry_price'],
                exit_price=leg_data['exit_price']
            )
            trade.option_legs.append(leg)
    else:
        print("No option_legs found in trade_data")
    
    print(f"\nTrade object created with {len(trade.option_legs)} option legs")
    print(f"Option leg: {trade.option_legs[0].option_type} {trade.option_legs[0].strike} "
          f"qty={trade.option_legs[0].quantity} (short={trade.option_legs[0].is_short})")
    
    # Apply the fix
    print("\nApplying fix...")
    fixed_trades = fix_covered_call_detection([trade], db)
    
    fixed_trade = fixed_trades[0]
    print(f"Result: {fixed_trade.strategy_type}")
    
    # Update in database if changed
    if fixed_trade.strategy_type != StrategyType(trade_data['strategy_type']):
        print(f"\nUpdating database: {trade_data['strategy_type']} -> {fixed_trade.strategy_type.value}")
        success = db.save_trade(fixed_trade, fixed_trade.account_number)
        if success:
            print("✅ Database updated successfully!")
        else:
            print("❌ Failed to update database")
    else:
        print("\nNo change needed")

if __name__ == "__main__":
    test_fix()