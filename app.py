#!/usr/bin/env python3
"""
Trade Journal Web Application
A beautiful, local web app for tracking and analyzing trades
"""

import os
from datetime import datetime, date, timedelta
from pathlib import Path
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from loguru import logger

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import DatabaseManager
from src.api.tastytrade_client import TastytradeClient
from src.models.trade_manager import TradeManager
from src.models.trade_strategy import StrategyType

def group_trades_into_chains(trades):
    """
    Group trades into chains based on underlying and roll relationships
    
    A chain represents a complete position lifecycle:
    - Opening trade (determines strategy)
    - Zero or more rolls (continuations)
    - Closing trade (optional if still open)
    
    Returns list of chain objects with trade lists and aggregate data
    """
    if not trades:
        return []
    
    # Group by underlying first
    by_underlying = {}
    for trade in trades:
        underlying = trade.get('underlying', 'UNKNOWN')
        if underlying not in by_underlying:
            by_underlying[underlying] = []
        by_underlying[underlying].append(trade)
    
    all_chains = []
    
    for underlying, underlying_trades in by_underlying.items():
        # Sort by entry date to process chronologically
        underlying_trades.sort(key=lambda t: t.get('entry_date', ''))
        
        # Detect chains within this underlying
        chains = detect_chains_for_underlying(underlying_trades)
        all_chains.extend(chains)
    
    return all_chains

def detect_chains_for_underlying(trades):
    """
    Detect chains within trades for a single underlying
    
    Chain detection logic:
    1. Look for roll indicators (includes_roll = True)
    2. Group consecutive trades that appear to be related
    3. Create chain with opening strategy + subsequent rolls
    """
    chains = []
    used_trades = set()
    
    for i, trade in enumerate(trades):
        if trade['trade_id'] in used_trades:
            continue
            
        # Start a new chain with this trade
        chain_trades = [trade]
        used_trades.add(trade['trade_id'])
        
        # Look for subsequent trades that might be rolls of this position
        for j in range(i + 1, len(trades)):
            candidate = trades[j]
            if candidate['trade_id'] in used_trades:
                continue
                
            # Check if this could be a roll continuation
            if is_roll_continuation(chain_trades[-1], candidate):
                chain_trades.append(candidate)
                used_trades.add(candidate['trade_id'])
        
        # Create chain object
        chain = create_chain_object(chain_trades)
        chains.append(chain)
    
    return chains

def is_roll_continuation(prev_trade, candidate_trade):
    """
    Determine if candidate_trade is a roll continuation of prev_trade
    
    Criteria:
    1. Same underlying (already filtered)
    2. Candidate has includes_roll = True
    3. Time proximity (within reasonable roll window)
    4. Similar strategy type or complexity
    """
    # Must be a roll
    if not candidate_trade.get('includes_roll'):
        return False
    
    # Check time proximity (within 30 days is reasonable for rolls)
    try:
        from datetime import datetime, timedelta
        prev_date = datetime.fromisoformat(prev_trade.get('entry_date', ''))
        candidate_date = datetime.fromisoformat(candidate_trade.get('entry_date', ''))
        
        # Candidate should be after previous trade but within roll window
        if candidate_date <= prev_date:
            return False
        
        time_diff = candidate_date - prev_date
        if time_diff > timedelta(days=30):
            return False
            
    except (ValueError, TypeError):
        # If date parsing fails, skip time check
        pass
    
    # Similar strategy complexity (same basic type)
    prev_strategy = prev_trade.get('strategy_type', '')
    candidate_strategy = candidate_trade.get('strategy_type', '')
    
    # Allow some flexibility in strategy matching for rolls
    strategy_families = {
        'Covered Call': ['Covered Call'],
        'Cash Secured Put': ['Cash Secured Put'],
        'Iron Condor': ['Iron Condor', 'Vertical Spread'],
        'Bull Put Spread': ['Bull Put Spread', 'Vertical Spread'],
        'Bear Call Spread': ['Bear Call Spread', 'Vertical Spread'],
    }
    
    for family, members in strategy_families.items():
        if prev_strategy in members and candidate_strategy in members:
            return True
    
    # Exact match fallback
    return prev_strategy == candidate_strategy

def create_chain_object(chain_trades):
    """
    Create a chain object from a list of trades
    
    Returns:
    {
        'chain_id': 'MSTR_CC_20250402',
        'underlying': 'MSTR', 
        'strategy_type': 'Covered Call',  # From opening trade
        'opening_date': '2025-04-02',
        'closing_date': '2025-04-24' or None,
        'status': 'Open'/'Closed',
        'trade_count': 4,
        'total_pnl': 614.50,
        'trades': [...] # Full trade objects
    }
    """
    if not chain_trades:
        return None
    
    # Sort chain_trades by entry_date in descending order (most recent first)
    # But keep track of opening (earliest) and closing (latest chronologically) for metadata
    chronological_trades = sorted(chain_trades, key=lambda t: t.get('entry_date', ''))
    opening_trade = chronological_trades[0]  # Earliest chronologically
    closing_trade = chronological_trades[-1]  # Latest chronologically
    
    # Sort trades for display (most recent first)
    display_trades = sorted(chain_trades, key=lambda t: t.get('entry_date', ''), reverse=True)
    
    # Calculate total P&L
    total_pnl = sum(trade.get('current_pnl', 0) for trade in chain_trades)
    
    # Determine if chain is closed (last trade is closed and not a roll)
    is_closed = (closing_trade.get('status') == 'Closed' and 
                not closing_trade.get('includes_roll', False))
    
    # Generate chain ID
    strategy_abbrev = get_strategy_abbreviation(opening_trade.get('strategy_type', ''))
    chain_id = f"{opening_trade.get('underlying', 'UNK')}_{strategy_abbrev}_{opening_trade.get('entry_date', '').replace('-', '')}"
    
    return {
        'chain_id': chain_id,
        'underlying': opening_trade.get('underlying'),
        'strategy_type': opening_trade.get('strategy_type'),  # Strategy from opening trade only
        'opening_date': opening_trade.get('entry_date'),
        'closing_date': closing_trade.get('exit_date') if is_closed else None,
        'status': 'Closed' if is_closed else 'Open',
        'trade_count': len(chain_trades),
        'total_pnl': total_pnl,
        'trades': display_trades  # Sorted most recent first for display
    }

def get_strategy_abbreviation(strategy_type):
    """Get short abbreviation for strategy type"""
    abbrevs = {
        'Covered Call': 'CC',
        'Cash Secured Put': 'CSP', 
        'Iron Condor': 'IC',
        'Bull Put Spread': 'BPS',
        'Bear Call Spread': 'BCS',
        'Bull Call Spread': 'BCS',
        'Bear Put Spread': 'BPS',
        'Vertical Spread': 'VS',
        'Long Call': 'LC',
        'Long Put': 'LP',
        'Naked Call': 'NC',
        'Naked Put': 'NP'
    }
    return abbrevs.get(strategy_type, 'UNKN')

def fix_covered_call_detection(trades, db):
    """
    Post-process trades to detect covered calls based on historical positions at trade time.
    
    This fixes cases where short calls were not grouped with their covering stock
    due to timing or grouping algorithm limitations.
    """
    from src.models.trade_strategy import StrategyRecognizer
    
    fixed_trades = []
    
    for trade in trades:
        # Only check naked call trades with single option legs
        if (trade.strategy_type == StrategyType.NAKED_CALL and 
            len(trade.option_legs) == 1 and 
            len(trade.stock_legs) == 0):
            
            option_leg = trade.option_legs[0]
            
            # Check if this is a short call
            if option_leg.is_short and option_leg.option_type == 'Call':
                try:
                    # Get all transactions for this account to check historical positions
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT * FROM raw_transactions 
                            WHERE account_number = ?
                            ORDER BY executed_at
                        ''', (trade.account_number,))
                        
                        columns = [description[0] for description in cursor.description]
                        rows = cursor.fetchall()
                        account_transactions = [dict(zip(columns, row)) for row in rows]
                    
                    # Check if we have transaction timestamps for the option leg
                    if option_leg.transaction_timestamps:
                        # Get the timestamp of the first option transaction (when the call was sold)
                        option_time = option_leg.transaction_timestamps[0]
                        
                        # Calculate stock position at that time for the same account
                        existing_shares = StrategyRecognizer.get_stock_positions_at_time(
                            account_transactions, option_time, trade.underlying, trade.account_number
                        )
                        
                        contracts = abs(option_leg.quantity)
                        shares_needed = contracts * 100
                        
                        # If we had enough shares to cover the calls at the time of sale
                        if existing_shares >= shares_needed:
                            logger.info(f"Converting {trade.trade_id} from Naked Call to Covered Call "
                                      f"(had {existing_shares} shares at time of sale, needed {shares_needed})")
                            trade.strategy_type = StrategyType.COVERED_CALL
                        else:
                            logger.info(f"Keeping {trade.trade_id} as Naked Call "
                                      f"(had {existing_shares} shares at time of sale, needed {shares_needed})")
                    else:
                        logger.warning(f"No transaction timestamps found for option leg in trade {trade.trade_id}")
                        
                except Exception as e:
                    logger.error(f"Error checking historical positions for trade {trade.trade_id}: {e}")
        
        fixed_trades.append(trade)
    
    return fixed_trades

# Configure logging
logger.add(
    "logs/webapp_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)

# Initialize FastAPI app
app = FastAPI(
    title="Trade Journal",
    description="Personal Trading Journal and Analytics",
    version="1.0.0"
)

# Add CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
db = DatabaseManager()

# Create static directory if it doesn't exist
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
(static_dir / "css").mkdir(exist_ok=True)
(static_dir / "js").mkdir(exist_ok=True)
(static_dir / "images").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Pydantic models for API
class TradeUpdate(BaseModel):
    trade_id: str
    status: Optional[str] = None
    current_notes: Optional[str] = None
    tags: Optional[List[str]] = None


class SyncRequest(BaseModel):
    days_back: int = 30


class TradeFilter(BaseModel):
    status: Optional[str] = None
    strategy: Optional[str] = None
    underlying: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    search_term: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    logger.info("Starting Trade Journal Web App")
    db.initialize_database()


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main application"""
    # Use the fixed version to avoid infinite rendering issues
    with open("static/index-fixed.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/trades")
async def get_trades(
    account_number: Optional[str] = None,
    status: Optional[str] = None,
    strategy: Optional[str] = None,
    underlying: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """Get trades with optional filters"""
    try:
        trades = db.get_trades(
            account_number=account_number,
            status=status,
            strategy=strategy,
            underlying=underlying,
            limit=limit,
            offset=offset
        )
        return {"trades": trades, "total": len(trades)}
    except Exception as e:
        logger.error(f"Error fetching trades: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chains")
async def get_trade_chains(
    account_number: Optional[str] = None,
    underlying: Optional[str] = None,
    limit: int = 100
):
    """Get trades grouped into chains"""
    try:
        # Get all trades for the given filters
        trades = db.get_trades(
            account_number=account_number,
            underlying=underlying,
            limit=limit * 3  # Get more trades since we'll be grouping them
        )
        
        # Enhance trades with full details (option legs, stock legs)
        enhanced_trades = []
        for trade in trades:
            trade_details = db.get_trade_details(trade['trade_id'])
            if trade_details:
                enhanced_trades.append(trade_details)
            else:
                enhanced_trades.append(trade)  # Fallback to basic trade data
        
        # Group trades into chains
        chains = group_trades_into_chains(enhanced_trades)
        
        return {"chains": chains, "total": len(chains)}
    except Exception as e:
        logger.error(f"Error fetching trade chains: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades/{trade_id}")
async def get_trade(trade_id: str):
    """Get a specific trade with all legs"""
    try:
        trade = db.get_trade_details(trade_id)
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        return trade
    except Exception as e:
        logger.error(f"Error fetching trade {trade_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/trades/{trade_id}")
async def update_trade(trade_id: str, trade_update: TradeUpdate):
    """Update trade status, notes, or tags"""
    try:
        success = db.update_trade(
            trade_id=trade_id,
            status=trade_update.status,
            current_notes=trade_update.current_notes,
            tags=trade_update.tags
        )
        if not success:
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"message": "Trade updated successfully"}
    except Exception as e:
        logger.error(f"Error updating trade {trade_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/accounts")
async def get_accounts():
    """Get all available accounts"""
    try:
        accounts = db.get_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions")
async def get_positions(account_number: Optional[str] = None):
    """Get current open positions"""
    try:
        positions = db.get_open_positions()
        return {"positions": positions}
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard")
async def get_dashboard_data(account_number: Optional[str] = None):
    """Get dashboard summary data"""
    try:
        # Get various statistics
        total_trades = db.get_trade_count(account_number=account_number)
        open_trades = db.get_trade_count(account_number=account_number, status="Open")
        closed_trades = db.get_trade_count(account_number=account_number, status="Closed")
        
        # Get P&L data
        total_pnl = db.get_total_pnl(account_number=account_number)
        today_pnl = db.get_pnl_by_date(date.today(), account_number=account_number)
        week_pnl = db.get_pnl_by_date_range(
            date.today() - timedelta(days=7),
            date.today(),
            account_number=account_number
        )
        
        # Get win rate
        win_rate = db.get_win_rate(account_number=account_number)
        
        # Get strategy breakdown
        strategy_stats = db.get_strategy_statistics()
        
        # Get recent trades
        recent_trades = db.get_trades(limit=5)
        
        return {
            "summary": {
                "total_trades": total_trades,
                "open_trades": open_trades,
                "closed_trades": closed_trades,
                "total_pnl": total_pnl,
                "today_pnl": today_pnl,
                "week_pnl": week_pnl,
                "win_rate": win_rate
            },
            "strategy_breakdown": strategy_stats,
            "recent_trades": recent_trades
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync")
async def sync_trades(sync_request: SyncRequest):
    """Sync trades from Tastytrade"""
    try:
        logger.info(f"Starting sync for last {sync_request.days_back} days")
        
        # Initialize clients
        tastytrade = TastytradeClient()
        trade_manager = TradeManager()
        
        # Authenticate
        if not tastytrade.authenticate():
            logger.error("Failed to authenticate with Tastytrade")
            raise HTTPException(status_code=401, detail="Failed to authenticate with Tastytrade")
        
        # Save all accounts to database
        logger.info("Saving account information...")
        accounts = tastytrade.get_all_accounts()
        for account in accounts:
            db.save_account(
                account['account_number'], 
                account['account_name'], 
                account['account_type']
            )
        logger.info(f"Saved {len(accounts)} accounts")
        
        # Fetch transactions from all accounts
        logger.info("Fetching transactions from all accounts...")
        transactions = tastytrade.get_transactions(days_back=sync_request.days_back)
        logger.info(f"Fetched {len(transactions)} transactions")
        
        # Save raw transactions first (for order ID support)
        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")
        
        # Process into trades using new TransactionMatcher
        logger.info("Processing transactions into trades with order-based grouping...")
        from src.models.transaction_matcher import TransactionMatcher
        from src.models.trade_strategy import StrategyRecognizer
        
        # Process each account separately to prevent cross-account grouping
        all_trades = []
        matcher = TransactionMatcher()
        
        for account in accounts:
            account_number = account['account_number']
            account_transactions = [tx for tx in transactions if tx.get('account_number') == account_number]
            
            # Filter out non-trading transactions (Money Movement, etc.)
            trading_transactions = [
                tx for tx in account_transactions 
                if tx.get('instrument_type') is not None and tx.get('symbol') is not None
            ]
            
            if not trading_transactions:
                logger.info(f"No trading transactions found for account {account_number}")
                continue
                
            logger.info(f"Processing {len(trading_transactions)} trading transactions for account {account_number} (filtered from {len(account_transactions)} total)")
            
            # Calculate stock positions for this account only
            stock_positions = StrategyRecognizer.get_stock_positions(trading_transactions)
            existing_positions = {}
            for symbol, quantity in stock_positions.items():
                existing_positions[symbol] = {'stock': quantity, 'options': {}}
            
            # Use TransactionMatcher for this account only
            try:
                strategy_matches = matcher.match_transactions_to_strategies(trading_transactions, existing_positions, account_transactions)
            except Exception as e:
                logger.error(f"Error in TransactionMatcher for account {account_number}: {str(e)}", exc_info=True)
                raise
            
            # Convert StrategyMatch objects to Trade objects
            for match in strategy_matches:
                # Create Trade object from StrategyMatch
                trade = StrategyRecognizer._create_trade_from_strategy_match(match)
                if trade:
                    all_trades.append(trade)
        
        trades = all_trades
        
        logger.info(f"Processed {len(trades)} trades using order-based grouping with historical position checking")
        
        # Get existing trades to avoid duplicates
        existing_trades = {}
        for underlying in set(trade.underlying for trade in trades):
            existing = db.get_trades(underlying=underlying, limit=1000)
            for existing_trade in existing:
                existing_trades[existing_trade['trade_id']] = existing_trade
        
        # Save to database (avoid duplicates)
        saved_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        
        # Group trades by account for processing
        trades_by_account = {}
        for trade in trades:
            # Get account number from trade object (set during trade creation)
            account_number = getattr(trade, 'account_number', 'UNKNOWN')
            
            if not account_number or account_number == 'UNKNOWN':
                logger.warning(f"Could not determine account for trade {trade.trade_id}")
                account_number = "UNKNOWN"
            
            if account_number not in trades_by_account:
                trades_by_account[account_number] = []
            trades_by_account[account_number].append((trade, account_number))

        for account_number, account_trades in trades_by_account.items():
            logger.info(f"Processing {len(account_trades)} trades for account {account_number}")
            
            for trade, trade_account in account_trades:
                try:
                    if trade.trade_id in existing_trades:
                        # Check if this trade needs updating (e.g., status changed)
                        existing = existing_trades[trade.trade_id]
                        if (existing['status'] != trade.status.value or 
                            existing['exit_date'] != (trade.exit_date.isoformat() if trade.exit_date else None)):
                            if db.save_trade(trade, trade_account):
                                updated_count += 1
                                logger.info(f"Updated existing trade {trade.trade_id} for account {trade_account}")
                            else:
                                failed_count += 1
                        else:
                            skipped_count += 1
                            logger.debug(f"Skipped unchanged trade {trade.trade_id}")
                    else:
                        # New trade
                        if db.save_trade(trade, trade_account):
                            saved_count += 1
                            logger.info(f"Saved new trade {trade.trade_id} for account {trade_account}")
                        else:
                            failed_count += 1
                            logger.warning(f"Failed to save trade {trade.trade_id}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error saving trade {trade.trade_id}: {str(e)}")
        
        logger.info(f"Sync complete: {saved_count} new, {updated_count} updated, {skipped_count} skipped, {failed_count} failed")
        
        # Also fetch and save current positions for all accounts
        logger.info("Fetching current positions from all accounts...")
        all_positions = tastytrade.get_positions()
        total_positions = 0
        
        for account_number, positions in all_positions.items():
            if positions:
                success = db.save_positions(positions, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")
        
        # Fetch and save account balance
        logger.info("Fetching account balance...")
        balance = tastytrade.get_account_balances()
        if balance:
            success = db.save_account_balance(balance)
            if success:
                logger.info("Successfully saved account balance")
            else:
                logger.error("Failed to save account balance")
        
        logger.info(f"Sync completed: {saved_count} new trades, {updated_count} updated, {skipped_count} skipped, {total_positions} positions updated")
        
        return {
            "message": f"Sync completed: {saved_count} new, {updated_count} updated, {skipped_count} unchanged",
            "trades_processed": len(trades),
            "trades_new": saved_count,
            "trades_updated": updated_count,
            "trades_skipped": skipped_count,
            "trades_failed": failed_count,
            "positions_updated": total_positions
        }
    except Exception as e:
        logger.error(f"Sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync/initial")
async def initial_sync():
    """Complete initial sync - clears database and rebuilds from scratch"""
    try:
        logger.info("Starting INITIAL SYNC - this will rebuild the entire database")
        
        # Preserve user data before clearing database
        logger.info("Preserving user comments and tags...")
        user_data = {}
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Save user comments and tags for existing trades
            cursor.execute("SELECT trade_id, current_notes, tags FROM trades WHERE current_notes IS NOT NULL OR tags IS NOT NULL")
            for row in cursor.fetchall():
                trade_id, notes, tags = row
                if notes or tags:
                    user_data[trade_id] = {
                        'current_notes': notes,
                        'tags': tags
                    }
        
        logger.info(f"Preserved user data for {len(user_data)} trades")
        
        # Clear the database
        logger.info("Clearing existing database...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM option_legs")
            cursor.execute("DELETE FROM stock_legs") 
            cursor.execute("DELETE FROM trades")
            cursor.execute("DELETE FROM positions")
            cursor.execute("DELETE FROM account_balances")
            logger.info("Database cleared successfully")
        
        # Initialize clients
        tastytrade = TastytradeClient()
        trade_manager = TradeManager()
        
        # Authenticate
        if not tastytrade.authenticate():
            logger.error("Failed to authenticate with Tastytrade")
            raise HTTPException(status_code=401, detail="Failed to authenticate with Tastytrade")
        
        # Save all accounts to database
        logger.info("Saving account information...")
        accounts = tastytrade.get_all_accounts()
        for account in accounts:
            db.save_account(
                account['account_number'], 
                account['account_name'], 
                account['account_type']
            )
        logger.info(f"Saved {len(accounts)} accounts")
        
        # Fetch ALL transactions (longer period for initial sync)
        logger.info("Fetching ALL transactions (last 365 days)...")
        transactions = tastytrade.get_transactions(days_back=365)
        logger.info(f"Fetched {len(transactions)} transactions")
        
        # Save raw transactions first (for order ID support)
        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")
        
        # Process into trades using new TransactionMatcher
        logger.info("Processing transactions into trades with order-based grouping...")
        from src.models.transaction_matcher import TransactionMatcher
        from src.models.trade_strategy import StrategyRecognizer
        
        # Process each account separately to prevent cross-account grouping
        all_trades = []
        matcher = TransactionMatcher()
        
        for account in accounts:
            account_number = account['account_number']
            account_transactions = [tx for tx in transactions if tx.get('account_number') == account_number]
            
            # Filter out non-trading transactions (Money Movement, etc.)
            trading_transactions = [
                tx for tx in account_transactions 
                if tx.get('instrument_type') is not None and tx.get('symbol') is not None
            ]
            
            if not trading_transactions:
                logger.info(f"No trading transactions found for account {account_number}")
                continue
                
            logger.info(f"Processing {len(trading_transactions)} trading transactions for account {account_number} (filtered from {len(account_transactions)} total)")
            
            # Calculate stock positions for this account only
            stock_positions = StrategyRecognizer.get_stock_positions(trading_transactions)
            existing_positions = {}
            for symbol, quantity in stock_positions.items():
                existing_positions[symbol] = {'stock': quantity, 'options': {}}
            
            # Use TransactionMatcher for this account only
            try:
                strategy_matches = matcher.match_transactions_to_strategies(trading_transactions, existing_positions, account_transactions)
            except Exception as e:
                logger.error(f"Error in TransactionMatcher for account {account_number}: {str(e)}", exc_info=True)
                raise
            
            # Convert StrategyMatch objects to Trade objects
            for match in strategy_matches:
                # Create Trade object from StrategyMatch
                trade = StrategyRecognizer._create_trade_from_strategy_match(match)
                if trade:
                    all_trades.append(trade)
        
        trades = all_trades
        
        logger.info(f"Processed {len(trades)} trades using order-based grouping")
        
        # Save all trades to database (avoid duplicates)
        saved_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        
        # Get existing trades to avoid duplicates
        existing_trades = {}
        for underlying in set(trade.underlying for trade in trades):
            existing = db.get_trades(underlying=underlying, limit=1000)
            for existing_trade in existing:
                existing_trades[existing_trade['trade_id']] = existing_trade
        
        # Group trades by account for processing
        trades_by_account = {}
        for trade in trades:
            # Get account number from trade object (set during trade creation)
            account_number = getattr(trade, 'account_number', 'UNKNOWN')
            
            if not account_number or account_number == 'UNKNOWN':
                logger.warning(f"Could not determine account for trade {trade.trade_id}")
                account_number = "UNKNOWN"
            
            if account_number not in trades_by_account:
                trades_by_account[account_number] = []
            trades_by_account[account_number].append((trade, account_number))

        for account_number, account_trades in trades_by_account.items():
            logger.info(f"Processing {len(account_trades)} trades for account {account_number}")
            
            for trade, trade_account in account_trades:
                try:
                    if trade.trade_id in existing_trades:
                        # Check if this trade needs updating (e.g., status changed)
                        existing = existing_trades[trade.trade_id]
                        if (existing['status'] != trade.status.value or 
                            existing['exit_date'] != (trade.exit_date.isoformat() if trade.exit_date else None)):
                            if db.save_trade(trade, trade_account):
                                updated_count += 1
                                logger.info(f"Updated existing trade {trade.trade_id} for account {trade_account}")
                            else:
                                failed_count += 1
                        else:
                            skipped_count += 1
                            logger.debug(f"Skipped unchanged trade {trade.trade_id}")
                    else:
                        # New trade
                        if db.save_trade(trade, trade_account):
                            saved_count += 1
                            logger.info(f"Saved new trade {trade.trade_id} for account {trade_account}")
                        else:
                            failed_count += 1
                            logger.warning(f"Failed to save trade {trade.trade_id}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error saving trade {trade.trade_id}: {str(e)}")
        
        logger.info(f"Initial sync complete: {saved_count} new, {updated_count} updated, {skipped_count} skipped, {failed_count} failed")
        
        # Restore user comments and tags
        logger.info("Restoring user comments and tags...")
        restored_count = 0
        with db.get_connection() as conn:
            cursor = conn.cursor()
            for trade_id, data in user_data.items():
                try:
                    cursor.execute("""
                        UPDATE trades 
                        SET current_notes = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE trade_id = ?
                    """, (data['current_notes'], data['tags'], trade_id))
                    if cursor.rowcount > 0:
                        restored_count += 1
                except Exception as e:
                    logger.warning(f"Failed to restore user data for trade {trade_id}: {str(e)}")
        
        logger.info(f"Restored user data for {restored_count} trades")
        
        # Fetch and save current positions for all accounts
        logger.info("Fetching current positions from all accounts...")
        all_positions = tastytrade.get_positions()
        total_positions = 0
        
        for account_number, positions in all_positions.items():
            if positions:
                success = db.save_positions(positions, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")
        
        # Fetch and save account balance
        logger.info("Fetching account balance...")
        balance = tastytrade.get_account_balances()
        if balance:
            success = db.save_account_balance(balance)
            if success:
                logger.info("Successfully saved account balance")
            else:
                logger.error("Failed to save account balance")
        
        logger.info(f"INITIAL SYNC completed: {saved_count} new trades, {updated_count} updated, {skipped_count} skipped, {total_positions} positions updated")
        
        return {
            "message": f"Initial sync completed successfully",
            "trades_processed": len(trades),
            "trades_new": saved_count,
            "trades_updated": updated_count,
            "trades_skipped": skipped_count,
            "trades_failed": failed_count,
            "positions_updated": total_positions,
            "transactions_processed": len(transactions)
        }
    except Exception as e:
        logger.error(f"Initial sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance/monthly")
async def get_monthly_performance(year: int = None):
    """Get monthly performance data"""
    try:
        if year is None:
            year = date.today().year
        
        monthly_data = db.get_monthly_performance(year)
        return {"year": year, "months": monthly_data}
    except Exception as e:
        logger.error(f"Error fetching monthly performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search")
async def search_trades(q: str, account_number: Optional[str] = None):
    """Search trades by various criteria"""
    try:
        results = db.search_trades(q, account_number=account_number)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching trades: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/strategy-config", response_class=HTMLResponse)
async def strategy_config_page():
    """Serve the strategy configuration page"""
    try:
        with open("static/strategy-config.html", "r") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving strategy config page: {str(e)}")
        return HTMLResponse(content=f"<h1>Error loading strategy config page: {str(e)}</h1>", status_code=500)


@app.get("/api/strategy-config")
async def get_strategy_configuration():
    """Get the strategy configuration"""
    try:
        # Import here to avoid circular imports
        from src.models.strategy_config import StrategyConfigLoader
        
        # Create a fresh instance
        config = StrategyConfigLoader()
        
        result = {
            "strategy_types": {},
            "categories": config.get_categories(),
            "direction_indicators": config.get_direction_indicators(),
            "recognition_priority": config.get_recognition_priority()
        }
        
        # Build strategy types dict
        for key, strategy in config.strategies.items():
            result["strategy_types"][key] = {
                "name": strategy.name,
                "code": strategy.code,
                "category": strategy.category,
                "direction": strategy.direction,
                "legs": strategy.legs,
                "description": strategy.description,
                "recognition_rules": strategy.recognition_rules
            }
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting strategy config: {str(e)}")
        logger.exception(e)  # This will log the full traceback
        # Return a more detailed error for debugging
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__}
        )


@app.post("/api/strategy-config")
async def update_strategy_config(request: Request):
    """Update the strategy configuration"""
    try:
        data = await request.json()
        config = get_strategy_config()
        
        # Update strategies if provided
        if "strategy_types" in data:
            # This would update the strategies in the config
            # For now, just reload to demonstrate
            config.reload()
        
        return {"message": "Configuration updated successfully"}
    except Exception as e:
        logger.error(f"Error updating strategy config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def create_initial_files():
    """Create initial HTML/CSS/JS files if they don't exist"""
    # This will be called to create the beautiful UI files
    pass


if __name__ == "__main__":
    # Create initial files if needed
    create_initial_files()
    
    # Start the server
    logger.info("Starting Trade Journal on http://localhost:8000")
    logger.info("From Windows, also try: http://127.0.0.1:8000")
    uvicorn.run(
        "app:app",  # Use string import to enable reload
        host="0.0.0.0",  # This ensures it binds to all interfaces
        port=8000,
        reload=True,
        log_level="info"
    )