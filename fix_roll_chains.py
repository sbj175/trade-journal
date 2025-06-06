#!/usr/bin/env python3
"""
Fix roll chain management - properly link rolls to close previous trades
"""

from src.database.db_manager import DatabaseManager
from src.models.trade_strategy import TradeStatus
from datetime import datetime

def fix_roll_chains():
    """Fix roll chains by properly linking rolls to close previous trades"""
    print("🔄 Fixing Roll Chain Management")
    print("=" * 60)
    
    db = DatabaseManager()
    
    # Get all trades
    all_trades = db.get_trades(limit=10000)
    print(f"Total trades: {len(all_trades)}")
    
    # Group trades by account and underlying
    grouped_trades = {}
    for trade in all_trades:
        account = trade.get('account_number', 'UNKNOWN')
        underlying = trade.get('underlying', 'UNKNOWN')
        key = (account, underlying)
        
        if key not in grouped_trades:
            grouped_trades[key] = []
        grouped_trades[key].append(trade)
    
    print(f"Grouped into {len(grouped_trades)} account-underlying combinations")
    
    total_updates = 0
    
    # Process each group
    for (account, underlying), trades in grouped_trades.items():
        # Filter for trades that could be part of roll chains
        # (Covered Calls and Rolls for the same underlying)
        roll_candidates = []
        for trade in trades:
            strategy_type = trade.get('strategy_type', '')
            if strategy_type in ['Covered Call', 'Call Roll', 'Put Roll', 'Cash Secured Put']:
                roll_candidates.append(trade)
        
        if len(roll_candidates) < 2:
            continue  # Need at least 2 trades to form a chain
            
        # Sort by entry date to establish chronological order
        roll_candidates.sort(key=lambda x: x.get('entry_date', ''))
        
        account_name = "Traditional IRA" if account == "5WZ26959" else "Roth IRA" if account == "5WZ28644" else "Individual"
        print(f"\n📊 Processing {underlying} in {account} ({account_name}): {len(roll_candidates)} trades")
        
        # Identify roll chains
        chains = identify_roll_chains(roll_candidates, db)
        
        for chain in chains:
            if len(chain) > 1:
                print(f"  Roll chain found: {len(chain)} trades")
                updates = fix_chain_statuses(chain, db)
                total_updates += updates
                
                # Show the corrected chain
                for i, trade in enumerate(chain):
                    status = "Open" if i == len(chain) - 1 else "Rolled"
                    print(f"    {i+1}. {trade['trade_id']}: {trade['strategy_type']} → {status}")
    
    print(f"\n✅ Roll Chain Fix Complete")
    print(f"Total trade status updates: {total_updates}")

def identify_roll_chains(trades, db):
    """Identify chains of related trades (covered calls → rolls → rolls)"""
    chains = []
    
    # Group by option type (Call vs Put) and strike patterns
    call_trades = []
    put_trades = []
    
    for trade in trades:
        strategy_type = trade.get('strategy_type', '')
        if 'Call' in strategy_type:
            call_trades.append(trade)
        elif 'Put' in strategy_type:
            put_trades.append(trade)
    
    # Process call chains
    if call_trades:
        call_chains = build_chains(call_trades, db)
        chains.extend(call_chains)
    
    # Process put chains  
    if put_trades:
        put_chains = build_chains(put_trades, db)
        chains.extend(put_chains)
    
    return chains

def build_chains(trades, db):
    """Build chains from a list of related trades"""
    if len(trades) < 2:
        return []
    
    # Sort by entry date
    trades.sort(key=lambda x: x.get('entry_date', ''))
    
    chains = []
    current_chain = [trades[0]]
    
    for i in range(1, len(trades)):
        current_trade = trades[i]
        previous_trade = current_chain[-1]
        
        # Check if this trade could be a roll of the previous trade
        if is_roll_continuation(previous_trade, current_trade, db):
            current_chain.append(current_trade)
        else:
            # Start new chain
            if len(current_chain) > 1:
                chains.append(current_chain)
            current_chain = [current_trade]
    
    # Add the final chain
    if len(current_chain) > 1:
        chains.append(current_chain)
    
    return chains

def is_roll_continuation(previous_trade, current_trade, db):
    """Check if current_trade is a roll continuation of previous_trade"""
    
    # Must be close in time (within reasonable rolling window)
    prev_date = previous_trade.get('entry_date')
    curr_date = current_trade.get('entry_date')
    
    if not prev_date or not curr_date:
        return False
    
    # Convert to datetime for comparison
    if isinstance(prev_date, str):
        prev_date = datetime.strptime(prev_date, '%Y-%m-%d').date()
    if isinstance(curr_date, str):
        curr_date = datetime.strptime(curr_date, '%Y-%m-%d').date()
    
    # Must be within reasonable rolling timeframe (90 days)
    time_diff = (curr_date - prev_date).days
    if time_diff < 0 or time_diff > 90:
        return False
    
    # Current trade must be a roll
    current_strategy = current_trade.get('strategy_type', '')
    if 'Roll' not in current_strategy:
        return False
    
    # Check if the current roll closes the position opened by the previous trade
    prev_details = db.get_trade_details(previous_trade['trade_id'])
    curr_details = db.get_trade_details(current_trade['trade_id'])
    
    prev_legs = prev_details.get('option_legs', [])
    curr_legs = curr_details.get('option_legs', [])
    
    if not prev_legs or not curr_legs:
        return False
    
    # Get the option position opened by the previous trade
    prev_opened_positions = get_opened_positions(previous_trade, prev_legs)
    
    # Get the option positions closed by the current trade
    curr_closed_positions = get_closed_positions(current_trade, curr_legs)
    
    # Check if current trade closes any position opened by previous trade
    for prev_pos in prev_opened_positions:
        for curr_pos in curr_closed_positions:
            if positions_match(prev_pos, curr_pos):
                return True
    
    return False

def get_opened_positions(trade, legs):
    """Get positions opened by this trade"""
    opened = []
    strategy_type = trade.get('strategy_type', '')
    
    for leg in legs:
        actions = leg.get('transaction_actions', [])
        quantity = leg.get('quantity', 0)
        
        # For negative quantities (short positions) with STO actions
        if quantity < 0 and any('STO' in action for action in actions):
            opened.append({
                'strike': leg.get('strike'),
                'expiration': leg.get('expiration'),
                'option_type': leg.get('option_type'),
                'quantity': abs(quantity)
            })
        # For positive quantities (long positions) with BTO actions  
        elif quantity > 0 and any('BTO' in action for action in actions):
            opened.append({
                'strike': leg.get('strike'),
                'expiration': leg.get('expiration'),
                'option_type': leg.get('option_type'),
                'quantity': quantity
            })
    
    return opened

def get_closed_positions(trade, legs):
    """Get positions closed by this trade"""
    closed = []
    
    for leg in legs:
        actions = leg.get('transaction_actions', [])
        quantity = leg.get('quantity', 0)
        
        # For positive quantities (closing short) with BTC actions
        if quantity > 0 and any('BTC' in action for action in actions):
            closed.append({
                'strike': leg.get('strike'),
                'expiration': leg.get('expiration'),
                'option_type': leg.get('option_type'),
                'quantity': quantity
            })
        # For negative quantities (closing long) with STC actions
        elif quantity < 0 and any('STC' in action for action in actions):
            closed.append({
                'strike': leg.get('strike'),
                'expiration': leg.get('expiration'),
                'option_type': leg.get('option_type'),
                'quantity': abs(quantity)
            })
    
    return closed

def positions_match(pos1, pos2):
    """Check if two positions match (same strike, expiration, type)"""
    return (pos1['strike'] == pos2['strike'] and
            pos1['expiration'] == pos2['expiration'] and  
            pos1['option_type'] == pos2['option_type'])

def get_effective_position_size(trade, legs):
    """Calculate the effective position size for a trade"""
    strategy_type = trade.get('strategy_type', '')
    
    if 'Roll' in strategy_type:
        # For rolls, the effective position is the opening leg size
        # Find opening transactions (they have larger absolute quantities usually)
        opening_legs = []
        closing_legs = []
        
        for leg in legs:
            actions = leg.get('transaction_actions', [])
            if any('STO' in action or 'BTO' in action for action in actions):
                if any('STO' in action for action in actions):
                    opening_legs.append(leg)
                else:
                    closing_legs.append(leg)
        
        # If we can distinguish, use opening legs; otherwise use half total
        if opening_legs:
            return sum(abs(leg.get('quantity', 0)) for leg in opening_legs)
        else:
            # Fall back to half of total (assumption: half closing, half opening)
            total_qty = sum(abs(leg.get('quantity', 0)) for leg in legs)
            return total_qty // 2
    else:
        # For non-rolls, use total position size
        return sum(abs(leg.get('quantity', 0)) for leg in legs)

def fix_chain_statuses(chain, db):
    """Fix the status of trades in a roll chain"""
    updates = 0
    
    for i, trade in enumerate(chain):
        trade_id = trade['trade_id']
        
        if i == len(chain) - 1:
            # Last trade in chain should be Open
            target_status = "Open"
        else:
            # All previous trades should be Rolled
            target_status = "Rolled"
        
        current_status = trade.get('status', 'Unknown')
        
        if current_status != target_status:
            # Update the trade status
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE trades 
                        SET status = ?, exit_date = ?
                        WHERE trade_id = ?
                    """, (
                        target_status,
                        trade.get('entry_date') if target_status == "Rolled" else None,
                        trade_id
                    ))
                    conn.commit()
                    updates += 1
                    print(f"    Updated {trade_id}: {current_status} → {target_status}")
            except Exception as e:
                print(f"    Error updating {trade_id}: {e}")
    
    return updates

if __name__ == '__main__':
    fix_roll_chains()