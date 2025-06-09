#!/usr/bin/env python3
"""
Fix closing transaction matching - properly link closing transactions to their opening trades
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import StrategyRecognizer
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_closing_transaction_matching():
    """Fix trades where closing transactions created separate trades instead of closing existing ones"""
    print("🔧 Fixing Closing Transaction Matching")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get all trades
    all_trades = db.get_trades(limit=10000)
    print(f"Total trades to analyze: {len(all_trades)}")
    
    # Find potential orphaned closing trades
    orphaned_closings = []
    open_trades = []
    
    for trade in all_trades:
        # Check if this looks like an orphaned closing trade
        # (trades that are closed on the same day they were opened and have only closing actions)
        if (trade.get('status') == 'Closed' and 
            trade.get('entry_date') == trade.get('exit_date')):
            
            # Check if all legs have closing actions
            details = db.get_trade_details(trade['trade_id'])
            option_legs = details.get('option_legs', [])
            
            all_closing = True
            for leg in option_legs:
                actions = leg.get('transaction_actions', [])
                if not any(action in ['BTC', 'STC'] for action in actions):
                    all_closing = False
                    break
            
            if all_closing and option_legs:
                orphaned_closings.append((trade, details))
        
        # Collect open trades that might need closing
        elif trade.get('status') == 'Open':
            open_trades.append(trade)
    
    print(f"\nFound {len(orphaned_closings)} potential orphaned closing trades")
    print(f"Found {len(open_trades)} open trades that might need closing")
    
    # Match orphaned closings to open trades
    matches = []
    
    for closing_trade, closing_details in orphaned_closings:
        closing_legs = closing_details.get('option_legs', [])
        
        print(f"\n🔍 Analyzing {closing_trade['trade_id']}:")
        print(f"   Underlying: {closing_trade['underlying']}")
        print(f"   Date: {closing_trade['entry_date']}")
        
        # Find matching open trade
        best_match = None
        best_score = 0
        
        for open_trade in open_trades:
            if open_trade['underlying'] != closing_trade['underlying']:
                continue
            
            # Must be opened before the closing date
            if open_trade['entry_date'] >= closing_trade['entry_date']:
                continue
            
            # Get open trade details
            open_details = db.get_trade_details(open_trade['trade_id'])
            open_legs = open_details.get('option_legs', [])
            
            # Calculate match score
            score = calculate_match_score(open_legs, closing_legs)
            
            if score > best_score:
                best_score = score
                best_match = (open_trade, open_details)
        
        if best_match and best_score >= 0.9:  # 90% confidence threshold
            matches.append({
                'orphaned_closing': (closing_trade, closing_details),
                'matching_open': best_match,
                'score': best_score
            })
            print(f"   ✅ Found match: {best_match[0]['trade_id']} (score: {best_score:.2f})")
        else:
            print(f"   ❌ No confident match found (best score: {best_score:.2f})")
    
    print(f"\n📊 Match Summary:")
    print(f"Confident matches found: {len(matches)}")
    
    # Apply fixes
    if matches:
        print(f"\n🔧 Applying Fixes...")
        fixes_applied = apply_fixes(matches, db)
        print(f"Successfully applied {fixes_applied} fixes")
    else:
        print("\nNo fixes to apply")
    
    return matches

def calculate_match_score(open_legs, closing_legs):
    """Calculate how well closing legs match opening legs"""
    if len(open_legs) != len(closing_legs):
        return 0
    
    matches = 0
    total = len(open_legs)
    
    # Sort legs by strike for comparison
    open_sorted = sorted(open_legs, key=lambda x: (x.get('strike', 0), x.get('option_type', '')))
    closing_sorted = sorted(closing_legs, key=lambda x: (x.get('strike', 0), x.get('option_type', '')))
    
    for i in range(total):
        open_leg = open_sorted[i]
        closing_leg = closing_sorted[i]
        
        # Check if contracts match
        if (open_leg.get('strike') == closing_leg.get('strike') and
            open_leg.get('expiration') == closing_leg.get('expiration') and
            open_leg.get('option_type') == closing_leg.get('option_type')):
            
            # Check if quantities match (opposite signs for closing)
            open_qty = open_leg.get('quantity', 0)
            closing_qty = closing_leg.get('quantity', 0)
            
            if abs(open_qty) == abs(closing_qty) and (open_qty * closing_qty) < 0:
                matches += 1
    
    return matches / total if total > 0 else 0

def apply_fixes(matches, db):
    """Apply the fixes by merging orphaned closing trades into their matching open trades"""
    fixes_applied = 0
    
    for match in matches:
        orphaned_trade, orphaned_details = match['orphaned_closing']
        open_trade, open_details = match['matching_open']
        
        print(f"\n🔄 Fixing: {open_trade['trade_id']} ← {orphaned_trade['trade_id']}")
        
        try:
            # Get the closing transaction IDs from the orphaned trade
            closing_tx_ids = []
            for leg in orphaned_details.get('option_legs', []):
                closing_tx_ids.extend(leg.get('transaction_ids', []))
            
            # Update the open trade's legs with exit prices and closing transactions
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Update each matching leg
                for open_leg in open_details.get('option_legs', []):
                    # Find matching closing leg
                    for closing_leg in orphaned_details.get('option_legs', []):
                        if (open_leg.get('strike') == closing_leg.get('strike') and
                            open_leg.get('expiration') == closing_leg.get('expiration') and
                            open_leg.get('option_type') == closing_leg.get('option_type')):
                            
                            # Update the open leg with closing info
                            leg_id = open_leg.get('id')
                            exit_price = closing_leg.get('entry_price')  # Entry price of closing is exit price
                            
                            # Get closing transaction IDs and actions
                            closing_actions = closing_leg.get('transaction_actions', [])
                            closing_ids = closing_leg.get('transaction_ids', [])
                            
                            if leg_id and exit_price is not None:
                                # Update exit price
                                cursor.execute("""
                                    UPDATE option_legs 
                                    SET exit_price = ?
                                    WHERE id = ?
                                """, (exit_price, leg_id))
                                
                                # Append transaction IDs and actions
                                for tx_id in closing_ids:
                                    cursor.execute("""
                                        UPDATE option_legs
                                        SET transaction_ids = transaction_ids || ?
                                        WHERE id = ?
                                    """, (',' + tx_id, leg_id))
                                
                                for action in closing_actions:
                                    cursor.execute("""
                                        UPDATE option_legs
                                        SET transaction_actions = transaction_actions || ?
                                        WHERE id = ?
                                    """, (',' + action, leg_id))
                
                # Update the trade status and exit date
                cursor.execute("""
                    UPDATE trades
                    SET status = 'Closed', exit_date = ?
                    WHERE trade_id = ?
                """, (orphaned_trade['entry_date'], open_trade['trade_id']))
                
                # Delete the orphaned trade
                cursor.execute("DELETE FROM option_legs WHERE trade_id = ?", (orphaned_trade['trade_id'],))
                cursor.execute("DELETE FROM trades WHERE trade_id = ?", (orphaned_trade['trade_id'],))
                
                conn.commit()
                fixes_applied += 1
                print(f"   ✅ Successfully merged trades")
                
        except Exception as e:
            print(f"   ❌ Error applying fix: {e}")
            logger.error(f"Failed to fix {open_trade['trade_id']}: {e}")
    
    return fixes_applied

def analyze_specific_case(underlying, account_number):
    """Analyze a specific case in detail"""
    print(f"\n📋 Detailed Analysis: {underlying} in account {account_number}")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get trades
    trades = db.get_trades(underlying=underlying, limit=50)
    account_trades = [t for t in trades if t.get('account_number') == account_number]
    
    print(f"Found {len(account_trades)} {underlying} trades in account")
    
    for trade in account_trades:
        print(f"\n{trade['trade_id']}:")
        print(f"  Strategy: {trade['strategy_type']}")
        print(f"  Status: {trade['status']}")
        print(f"  Entry: {trade['entry_date']}")
        print(f"  Exit: {trade.get('exit_date', 'None')}")
        
        details = db.get_trade_details(trade['trade_id'])
        print(f"  Legs:")
        for leg in details.get('option_legs', []):
            print(f"    {leg.get('option_type')} ${leg.get('strike')} - Actions: {leg.get('transaction_actions', [])}")

if __name__ == '__main__':
    # First analyze the specific AFRM case
    analyze_specific_case('AFRM', '5WZ28644')
    
    # Then run the general fix
    print("\n" + "=" * 60)
    matches = fix_closing_transaction_matching()
    
    # Re-analyze AFRM to see if it was fixed
    if matches:
        print("\n" + "=" * 60)
        print("🔄 Re-analyzing AFRM after fixes:")
        analyze_specific_case('AFRM', '5WZ28644')