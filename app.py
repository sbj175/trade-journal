#!/usr/bin/env python3

"""
Trade Journal Web Application
A beautiful, local web app for tracking and analyzing trades
"""

import os
import asyncio
from datetime import datetime, date, timedelta
from pathlib import Path
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
from src.models.order_models import OrderManager
from src.models.position_inventory import PositionInventoryManager
from src.models.order_processor_v2 import OrderProcessorV2
from src.models.strategy_detector import StrategyDetector
from src.models.pnl_calculator_v2 import PnLCalculatorV2

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
order_manager = OrderManager(db)

# V2 System Components
position_manager = PositionInventoryManager(db)
order_processor_v2 = OrderProcessorV2(db, position_manager)
strategy_detector = StrategyDetector(db)
pnl_calculator_v2 = PnLCalculatorV2(db, position_manager)


def calculate_position_opening_dates(positions: List[Dict[str, Any]], account_number: str) -> List[Dict[str, Any]]:
    """Calculate opening dates for positions based on transaction history - OPTIMIZED"""
    logger.info(f"🔍 EFFICIENCY_DEBUG: Calculating opening dates for {len(positions)} positions in account {account_number}")
    
    if not positions:
        return positions
    
    # Get existing positions for this account only (more efficient query)
    existing_positions = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol, opened_at 
            FROM positions 
            WHERE account_number = ? AND opened_at IS NOT NULL
        """, (account_number,))
        existing_positions = cursor.fetchall()
    
    # Create efficient lookup map
    existing_opened_at = {pos['symbol']: pos['opened_at'] for pos in existing_positions}
    logger.info(f"🔍 EFFICIENCY_DEBUG: Found {len(existing_opened_at)} existing positions with opening dates")
    
    # Get symbols that need opening date calculation
    symbols_needing_dates = [pos['symbol'] for pos in positions if pos['symbol'] not in existing_opened_at]
    
    if not symbols_needing_dates:
        # All positions already have opening dates
        for position in positions:
            position['opened_at'] = existing_opened_at.get(position['symbol'])
        return positions
    
    logger.info(f"🔍 EFFICIENCY_DEBUG: Need to calculate opening dates for {len(symbols_needing_dates)} symbols")
    
    # Optimized query: Get opening transactions for specific symbols only
    opening_dates = {}
    if symbols_needing_dates:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Use parameterized query with IN clause for specific symbols
            placeholders = ','.join(['?' for _ in symbols_needing_dates])
            cursor.execute(f"""
                SELECT symbol, MIN(executed_at) as earliest_date
                FROM raw_transactions 
                WHERE account_number = ? 
                AND symbol IN ({placeholders})
                AND (action LIKE '%BUY_TO_OPEN%' OR action LIKE '%SELL_TO_OPEN%')
                GROUP BY symbol
            """, [account_number] + symbols_needing_dates)
            
            for row in cursor.fetchall():
                opening_dates[row['symbol']] = row['earliest_date']
    
    logger.info(f"🔍 EFFICIENCY_DEBUG: Found opening dates for {len(opening_dates)} symbols via optimized query")
    
    # Apply opening dates to positions
    for position in positions:
        symbol = position.get('symbol')
        
        # Use existing date if available
        if symbol in existing_opened_at:
            position['opened_at'] = existing_opened_at[symbol]
        # Use calculated date if available
        elif symbol in opening_dates:
            position['opened_at'] = opening_dates[symbol]
        else:
            # No opening transaction found
            position['opened_at'] = None
    
    # Log summary
    positions_with_dates = sum(1 for p in positions if p.get('opened_at'))
    logger.info(f"🔍 EFFICIENCY_DEBUG: Set opening dates for {positions_with_dates}/{len(positions)} positions")
    
    # Log some examples
    for i, pos in enumerate(positions[:3]):
        symbol = pos.get('symbol')
        opened_at = pos.get('opened_at')
        logger.info(f"🔍 EFFICIENCY_DEBUG: Position {i+1}: {symbol} -> opened_at: {opened_at}")
    
    return positions



# Create static directory if it doesn't exist
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
(static_dir / "css").mkdir(exist_ok=True)
(static_dir / "js").mkdir(exist_ok=True)
(static_dir / "images").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Pydantic models for API
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
    
    # Check if we need to automatically sync on startup
    try:
        last_sync = db.get_last_sync_timestamp()
        if last_sync:
            # Calculate time since last sync
            time_since_sync = datetime.now() - last_sync
            hours_since_sync = time_since_sync.total_seconds() / 3600
            
            # Auto-sync if it's been more than 6 hours since last sync and it's market hours
            if hours_since_sync > 6:
                logger.info(f"Auto-sync triggered: {hours_since_sync:.1f} hours since last sync")
                # Note: Auto-sync runs in background, don't await to avoid blocking startup
                asyncio.create_task(background_auto_sync())
            else:
                logger.info(f"No auto-sync needed: {hours_since_sync:.1f} hours since last sync")
        else:
            logger.info("No previous sync found - auto-sync will be triggered on first manual sync")
    except Exception as e:
        logger.warning(f"Error checking auto-sync: {e}")


async def background_auto_sync():
    """Background task for automatic sync"""
    try:
        logger.info("Starting background auto-sync...")
        # Use the sync_unified function without request context
        await sync_unified_internal()
        logger.info("Background auto-sync completed successfully")
    except Exception as e:
        logger.error(f"Background auto-sync failed: {e}")


async def sync_unified_internal():
    """Internal sync function that can be called without HTTP context"""
    from datetime import datetime, timedelta
    
    # Check last sync timestamp to determine date range
    last_sync = db.get_last_sync_timestamp()
    
    if last_sync:
        # Calculate days back from last sync + 1 day buffer
        days_back = (datetime.now() - last_sync).days + 1
        days_back = max(days_back, 1)  # Minimum 1 day
        days_back = min(days_back, 90)  # Maximum 90 days for safety
        logger.info(f"Auto-sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
    else:
        # No previous sync, fetch last 30 days for auto-sync (conservative)
        days_back = 30
        logger.info(f"Auto-sync: first sync detected, fetching {days_back} days")
    
    # Initialize clients
    tastytrade = TastytradeClient()
    
    # Authenticate
    if not tastytrade.authenticate():
        logger.error("Auto-sync: Failed to authenticate with Tastytrade")
        return
    
    # Save all accounts to database
    logger.info("Auto-sync: Saving account information...")
    accounts = tastytrade.get_all_accounts()
    for account in accounts:
        db.save_account(
            account['account_number'], 
            account['account_name'], 
            account['account_type']
        )
    logger.info(f"Auto-sync: Saved {len(accounts)} accounts")
    
    # Fetch and save current positions for all accounts
    logger.info("Auto-sync: Fetching current positions from all accounts...")
    all_positions = tastytrade.get_positions()
    total_positions = 0
    
    for account_number, positions in all_positions.items():
        if positions:
            # Calculate opening dates for positions
            positions_with_dates = calculate_position_opening_dates(positions, account_number)
            success = db.save_positions(positions_with_dates, account_number)
            if success:
                logger.info(f"Auto-sync: Successfully saved {len(positions)} positions for account {account_number}")
                total_positions += len(positions)
            else:
                logger.error(f"Auto-sync: Failed to save positions for account {account_number}")
    
    # Update last sync timestamp
    db.update_last_sync_timestamp()
    logger.info(f"Auto-sync completed: {total_positions} positions updated")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main application"""
    # Use the fixed version to avoid infinite rendering issues
    with open("static/index-fixed.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/chains-v2", response_class=HTMLResponse)
async def chains_v2():
    """Serve the V2 order chains page"""
    with open("static/chains-v2.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/test_websocket.html", response_class=HTMLResponse)
async def test_websocket():
    """Serve the WebSocket test page"""
    try:
        with open("test_websocket.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>test_websocket.html not found</h1>", status_code=404)


@app.get("/api/health")
async def health_check():
    """Simple health check endpoint"""
    return {"status": "ok", "service": "Trade Journal"}


@app.get("/api/chains")
async def get_order_chains(
    account_number: Optional[str] = None,
    underlying: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """Get order chains with enhanced display information"""
    try:
        # Get order chains from the new model
        chains = order_manager.get_order_chains(
            account_number=account_number, 
            limit=limit, 
            offset=offset
        )
        
        # Filter by underlying if specified
        if underlying:
            chains = [chain for chain in chains if chain['underlying'] == underlying]
        
        # Transform to match frontend expectations
        formatted_chains = []
        for chain in chains:
            # Get first and last orders for chain metadata
            orders = chain.get('orders', [])
            if not orders:
                continue
            
            # Filter out chains that only contain stock positions (no options)
            has_options = False
            for order in orders:
                for position in order.get('positions', []):
                    if 'OPTION' in str(position.get('instrument_type', '')):
                        has_options = True
                        break
                if has_options:
                    break
            
            # Skip chains with no option positions
            if not has_options:
                continue
                
            opening_order = orders[0]  # First in sequence
            closing_order = orders[-1] if orders else None
            
            # Calculate chain summary
            formatted_chain = {
                'chain_id': chain['chain_id'],
                'underlying': chain['underlying'],
                'strategy_type': chain['strategy_type'],
                'opening_date': opening_order.get('order_date') if opening_order else None,
                'closing_date': None,
                'status': chain['chain_status'],
                'order_count': len(orders),
                'total_pnl': chain['total_pnl'],
                'realized_pnl': chain['realized_pnl'],
                'unrealized_pnl': chain['unrealized_pnl'],
                'orders': []
            }
            
            # Process each order in the chain
            for order in orders:
                # Create Order object to use consolidation method
                from src.models.order_models import Order, Position, OrderType, OrderStatus, PositionStatus
                
                # Convert order dictionary to Order object
                order_type = OrderType(order['order_type'])
                order_status = OrderStatus(order['status'])
                
                order_obj = Order(
                    order_id=order['order_id'],
                    account_number=order['account_number'],
                    underlying=order['underlying'],
                    order_type=order_type,
                    strategy_type=order.get('strategy_type'),
                    order_date=order['order_date'],
                    status=order_status,
                    total_quantity=order['total_quantity'],
                    total_pnl=order['total_pnl'],
                    has_assignment=order.get('has_assignment', False),
                    has_expiration=order.get('has_expiration', False),
                    has_exercise=order.get('has_exercise', False),
                    linked_order_id=order.get('linked_order_id'),
                    positions=[]
                )
                
                # Convert positions to Position objects
                for pos_dict in order.get('positions', []):
                    position_status = PositionStatus(pos_dict['status'])
                    position = Position(
                        position_id=pos_dict['position_id'],
                        order_id=pos_dict['order_id'],
                        account_number=pos_dict['account_number'],
                        symbol=pos_dict['symbol'],
                        underlying=pos_dict['underlying'],
                        instrument_type=pos_dict['instrument_type'],
                        option_type=pos_dict.get('option_type'),
                        strike=pos_dict.get('strike'),
                        expiration=pos_dict.get('expiration'),
                        quantity=pos_dict['quantity'],
                        opening_price=pos_dict['opening_price'],
                        closing_price=pos_dict.get('closing_price'),
                        opening_transaction_id=pos_dict['opening_transaction_id'],
                        closing_transaction_id=pos_dict.get('closing_transaction_id'),
                        opening_action=pos_dict['opening_action'],
                        closing_action=pos_dict.get('closing_action'),
                        status=position_status,
                        pnl=pos_dict['pnl'],
                        fill_count=pos_dict.get('fill_count', 1),
                        created_at=pos_dict.get('created_at'),
                        updated_at=pos_dict.get('updated_at')
                    )
                    order_obj.positions.append(position)
                
                # Apply consolidation
                consolidated_positions = order_obj.consolidate_positions()
                
                # Convert back to dictionaries for JSON response
                consolidated_pos_dicts = []
                for pos in consolidated_positions:
                    pos_dict = {
                        'position_id': pos.position_id,
                        'order_id': pos.order_id,
                        'account_number': pos.account_number,
                        'symbol': pos.symbol,
                        'underlying': pos.underlying,
                        'instrument_type': pos.instrument_type,
                        'option_type': pos.option_type,
                        'strike': pos.strike,
                        'expiration': pos.expiration,
                        'quantity': pos.quantity,
                        'opening_price': pos.opening_price,
                        'closing_price': pos.closing_price,
                        'opening_transaction_id': pos.opening_transaction_id,
                        'closing_transaction_id': pos.closing_transaction_id,
                        'opening_action': pos.opening_action,
                        'closing_action': pos.closing_action,
                        'status': pos.status.value,
                        'pnl': pos.pnl,
                        'fill_count': pos.fill_count,
                        'created_at': pos.created_at,
                        'updated_at': pos.updated_at
                    }
                    consolidated_pos_dicts.append(pos_dict)
                
                order_info = {
                    'order_id': order['order_id'],
                    'order_type': order['order_type'],
                    'order_date': order['order_date'],
                    'strategy_type': order.get('strategy_type'),
                    'status': order['status'],
                    'total_pnl': order['total_pnl'],
                    'positions': consolidated_pos_dicts,
                    'emblems': []
                }
                
                # Add emblems based on order characteristics
                if order.get('has_assignment'):
                    order_info['emblems'].append('A')
                if order.get('has_expiration'):
                    order_info['emblems'].append('E')
                if order.get('has_exercise'):
                    order_info['emblems'].append('X')
                
                formatted_chain['orders'].append(order_info)
            
            # Set closing date if last order is closed
            if closing_order and closing_order['status'] == 'CLOSED':
                formatted_chain['closing_date'] = closing_order.get('order_date')
            
            formatted_chains.append(formatted_chain)
        
        return {"chains": formatted_chains, "total": len(formatted_chains)}
    except Exception as e:
        logger.error(f"Error fetching order chains: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chains-v2")
async def get_order_chains_v2(
    account_number: Optional[str] = None,
    underlying: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """Get order chains using the new V2 derivation system"""
    try:
        # Get all raw transactions
        raw_transactions = db.get_raw_transactions(
            account_number=account_number,
            underlying=underlying
        )
        
        if not raw_transactions:
            return {"chains": [], "total": 0}
        
        # Clear and rebuild position inventory for accurate chain status
        position_manager.clear_all_positions()
        
        # Process through V2 system to get derived chains  
        chains_by_account = order_processor_v2.process_transactions(raw_transactions)
        
        # Flatten chains from all accounts
        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)
        
        # Sort by opening date (newest first)
        all_chains.sort(key=lambda c: c.opening_date or date.min, reverse=True)
        
        # Apply pagination
        paginated_chains = all_chains[offset:offset + limit]
        
        # Format for frontend (similar to old system but with V2 data)
        formatted_chains = []
        for chain in paginated_chains:
            # Calculate totals
            total_credit = 0.0
            total_debit = 0.0
            total_quantity = 0
            
            for order in chain.orders:
                for tx in order.transactions:
                    amount = tx.price * abs(tx.quantity) * 100  # *100 for options
                    if tx.is_opening:
                        if tx.is_sell:
                            total_credit += amount
                        else:
                            total_debit += amount
                    total_quantity += abs(tx.quantity)
            
            # Calculate realized P&L from closed positions
            realized_pnl = 0.0
            unrealized_pnl = 0.0
            
            for order in chain.orders:
                for tx in order.transactions:
                    if tx.is_closing:
                        if tx.is_assignment or tx.is_exercise or tx.is_expiration:
                            # For assignment/exercise/expiration, calculate based on strike price
                            quantity = abs(tx.quantity)
                            if tx.is_assignment and tx.strike:
                                # Assignment: net impact is +strike*100
                                realized_pnl += tx.strike * 100 * quantity
                            elif tx.is_exercise and tx.strike:
                                # Exercise: net impact is -strike*100
                                realized_pnl -= tx.strike * 100 * quantity
                            # For expiration, P&L is 0 (options expire worthless)
                        elif tx.price > 0:  # Regular closing transactions
                            # Find the opening transaction for this symbol
                            opening_tx = None
                            for search_order in chain.orders:
                                for search_tx in search_order.transactions:
                                    if (search_tx.symbol == tx.symbol and 
                                        search_tx.is_opening and 
                                        search_tx.executed_at <= tx.executed_at):
                                        opening_tx = search_tx
                                        break
                                if opening_tx:
                                    break
                            
                            if opening_tx:
                                # Calculate P&L for this closing transaction
                                quantity = abs(tx.quantity)
                                if opening_tx.is_sell:  # Short position (STO -> BTC)
                                    pnl = (opening_tx.price - tx.price) * quantity * 100
                                else:  # Long position (BTO -> STC)
                                    pnl = (tx.price - opening_tx.price) * quantity * 100
                                realized_pnl += pnl
            
            # Detect strategy for this chain
            detected_strategy = strategy_detector.detect_chain_strategy(chain)
            
            formatted_chain = {
                'chain_id': chain.chain_id,
                'underlying': chain.underlying,
                'strategy_type': detected_strategy,
                'opening_date': chain.opening_date.isoformat() if chain.opening_date else None,
                'closing_date': chain.closing_date.isoformat() if chain.closing_date else None,
                'status': chain.status,
                'order_count': len(chain.orders),
                'total_quantity': total_quantity,
                'total_credit': total_credit,
                'total_debit': total_debit,
                'net_premium': total_credit - total_debit,
                'realized_pnl': realized_pnl,
                'unrealized_pnl': unrealized_pnl,
                'total_pnl': 0,  # Will be calculated after orders are processed
                'account_number': chain.account_number,
                'orders': []
            }
            
            # Format orders
            for order in chain.orders:
                # Clean up system-generated order IDs for display
                display_order_id = order.order_id
                if order.order_id.startswith('SYSTEM_'):
                    if 'Expiration' in order.order_id:
                        display_order_id = f"EXPIRATION_{order.executed_at.strftime('%Y%m%d')}"
                    elif 'Assignment' in order.order_id:
                        display_order_id = f"ASSIGNMENT_{order.executed_at.strftime('%Y%m%d')}"
                    elif 'Exercise' in order.order_id:
                        display_order_id = f"EXERCISE_{order.executed_at.strftime('%Y%m%d')}"
                    else:
                        display_order_id = f"SYSTEM_{order.executed_at.strftime('%Y%m%d')}"
                
                order_info = {
                    'order_id': display_order_id,
                    'order_type': order.order_type.value,
                    'order_date': order.executed_at.date().isoformat(),
                    'strategy_type': None,
                    'status': 'CLOSED' if order.order_type.value == 'CLOSING' else 'FILLED',
                    'positions': [],
                    'emblems': []
                }
                
                # Create positions from all transactions in the order
                position_id_counter = 1
                processed_symbols = set()  # Track which symbols we've already processed
                
                for tx in order.transactions:
                    # For closing transactions (assignment/exercise/expiration), don't create separate positions
                    # Instead, they should update the original opening positions
                    if tx.is_closing and (tx.is_assignment or tx.is_exercise or tx.is_expiration):
                        continue  # Skip creating separate positions for these
                    
                    position_info = {
                        'position_id': f"{order.order_id}_{position_id_counter}",
                        'symbol': tx.symbol,
                        'underlying': tx.underlying_symbol,
                        'instrument_type': 'EQUITY_OPTION' if tx.option_type else 'EQUITY',
                        'option_type': tx.option_type,
                        'strike': tx.strike,
                        'expiration': tx.expiration.isoformat() if tx.expiration else None,
                        'quantity': tx.quantity if tx.is_buy else -abs(tx.quantity),  # Show negative for short positions
                        'opening_action': str(tx.action).replace('OrderAction.', ''),
                        'opening_price': tx.price,
                        'closing_action': None,
                        'closing_price': None,
                        'status': 'OPEN',
                        'opening_transaction_id': tx.id,
                        'closing_transaction_id': None,
                        'pnl': 0.0
                    }
                    
                    # Set transaction amount (not P&L, just the credit/debit amount)
                    quantity = abs(tx.quantity)
                    amount = tx.price * 100 * quantity
                    if tx.is_sell:  # Sell transactions are credits (positive)
                        position_info['pnl'] = amount
                    else:  # Buy transactions are debits (negative)  
                        position_info['pnl'] = -amount
                    
                    # Check if this position was closed by assignment/exercise/expiration in a later order
                    for check_order in chain.orders:
                        if check_order.executed_at > order.executed_at:  # Only check later orders
                            for closing_tx in check_order.transactions:
                                if (closing_tx.symbol == tx.symbol and 
                                    (closing_tx.is_assignment or closing_tx.is_exercise or closing_tx.is_expiration)):
                                    # This position was closed by assignment/exercise/expiration
                                    position_info['status'] = 'CLOSED'
                                    if closing_tx.is_assignment:
                                        position_info['closing_action'] = 'ASSIGNED'
                                    elif closing_tx.is_exercise:
                                        position_info['closing_action'] = 'EXERCISED'
                                    elif closing_tx.is_expiration:
                                        position_info['closing_action'] = 'EXPIRED'
                                    position_info['closing_price'] = closing_tx.price or 0.0
                                    position_info['closing_transaction_id'] = closing_tx.id
                                    
                                    # For positions closed by assignment/exercise, show the original transaction amount
                                    # The assignment/exercise impact will show at the order level for those orders
                                    quantity = abs(tx.quantity)
                                    amount = tx.price * 100 * quantity
                                    if tx.is_sell:  # Sell transactions are credits (positive)
                                        position_info['pnl'] = amount
                                    else:  # Buy transactions are debits (negative)
                                        position_info['pnl'] = -amount
                                    break
                    
                    # For regular closing transactions, try to find the matching opening transaction
                    if tx.is_closing and not (tx.is_assignment or tx.is_exercise or tx.is_expiration):
                        # Find matching opening transaction in the same order or previous orders in chain
                        opening_tx = None
                        for search_order in chain.orders:
                            for search_tx in search_order.transactions:
                                if (search_tx.symbol == tx.symbol and 
                                    search_tx.is_opening and 
                                    search_tx.executed_at <= tx.executed_at):
                                    opening_tx = search_tx
                                    break
                            if opening_tx:
                                break
                        
                        if opening_tx:
                            # Just show the transaction amount for closing transactions
                            quantity = abs(tx.quantity)
                            amount = tx.price * 100 * quantity
                            if tx.is_sell:  # Sell to close is a credit
                                position_info['pnl'] = amount
                            else:  # Buy to close is a debit
                                position_info['pnl'] = -amount
                            position_info['closing_action'] = str(tx.action).replace('OrderAction.', '')
                            position_info['closing_price'] = tx.price
                            position_info['status'] = 'CLOSED'
                    
                    order_info['positions'].append(position_info)
                    position_id_counter += 1
                
                # Calculate order-level P&L
                if order.order_type.value == 'OPENING':
                    # For opening orders, P&L is the net premium (credits - debits)
                    order_credit = 0.0
                    order_debit = 0.0
                    for tx in order.transactions:
                        amount = tx.price * abs(tx.quantity) * 100
                        if tx.is_sell:
                            order_credit += amount
                        else:
                            order_debit += amount
                    order_pnl = order_credit - order_debit
                elif order.order_type.value == 'ROLLING':
                    # For rolling orders, P&L is net of all credits and debits
                    order_credit = 0.0
                    order_debit = 0.0
                    for tx in order.transactions:
                        amount = tx.price * abs(tx.quantity) * 100
                        if tx.is_sell:
                            order_credit += amount
                        else:
                            order_debit += amount
                    order_pnl = order_credit - order_debit
                elif any(tx.is_assignment or tx.is_exercise or tx.is_expiration 
                        for tx in order.transactions):
                    # For assignment/exercise/expiration orders, P&L is the strike impact
                    order_pnl = 0.0
                    for tx in order.transactions:
                        quantity = abs(tx.quantity)
                        if tx.is_assignment and tx.strike:
                            order_pnl += tx.strike * 100 * quantity  # Assignment: +strike*100
                        elif tx.is_exercise and tx.strike:
                            order_pnl -= tx.strike * 100 * quantity  # Exercise: -strike*100
                else:
                    # For regular closing orders (BTC/STC only), P&L is the debit/credit
                    order_credit = 0.0
                    order_debit = 0.0
                    for tx in order.transactions:
                        amount = tx.price * abs(tx.quantity) * 100
                        if tx.is_sell:
                            order_credit += amount
                        else:
                            order_debit += amount
                    order_pnl = order_credit - order_debit
                
                order_info['total_pnl'] = order_pnl
                
                # Add emblems for special transaction types
                if any(tx.is_expiration for tx in order.transactions):
                    order_info['emblems'].append('E')
                
                formatted_chain['orders'].append(order_info)
            
            # Calculate chain P&L as sum of all order P&Ls
            formatted_chain['total_pnl'] = sum(order['total_pnl'] for order in formatted_chain['orders'])
            
            formatted_chains.append(formatted_chain)
        
        return {"chains": formatted_chains, "total": len(formatted_chains)}
        
    except Exception as e:
        logger.error(f"Error fetching V2 order chains: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/orders/{order_id}")
async def get_order(order_id: str):
    """Get a specific order with all positions"""
    try:
        order = order_manager.get_order_by_id(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions")
async def get_current_positions(account_number: Optional[str] = None):
    """Get current positions from Tastytrade API with health scores"""
    try:
        # Initialize Tastytrade client
        client = TastytradeClient()
        
        # Authenticate with Tastytrade
        if not client.authenticate():
            raise HTTPException(status_code=401, detail="Failed to authenticate with Tastytrade")
        
        # Get positions from Tastytrade API
        positions = client.get_positions(account_number=account_number)
        
        if not positions:
            logger.warning("No positions returned from Tastytrade API")
            return {}
        
        # Get current quotes for health calculations
        all_symbols = []
        for account_positions in positions.values():
            for position in account_positions:
                underlying = position.get('underlying_symbol', position.get('symbol'))
                if underlying and underlying not in all_symbols:
                    all_symbols.append(underlying)
        
        quotes = {}
        if all_symbols:
            try:
                quotes = client.get_quotes(all_symbols)
            except Exception as e:
                logger.warning(f"Failed to get quotes for health calculations: {e}")
        
        # Store quotes for frontend strategy health calculations
        for account_positions in positions.values():
            for position in account_positions:
                underlying = position.get('underlying_symbol', position.get('symbol'))
                position['underlying_quote'] = quotes.get(underlying, {}) if underlying else {}
        
        logger.info(f"Successfully fetched positions from Tastytrade: {sum(len(pos_list) for pos_list in positions.values())} total positions")
        return positions
        
    except Exception as e:
        logger.error(f"Error fetching positions from Tastytrade: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {str(e)}")


@app.get("/api/quotes")
async def get_market_quotes(symbols: str, refresh: bool = False):
    """Get current market quotes for symbols"""
    try:
        # Parse comma-separated symbols
        symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
        
        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        
        # Initialize Tastytrade client
        client = TastytradeClient()
        
        # Authenticate with Tastytrade
        if not client.authenticate():
            raise HTTPException(status_code=401, detail="Failed to authenticate with Tastytrade")
        
        # Clear cache if refresh requested
        if refresh:
            client.clear_quote_cache()
            logger.info("Cache cleared due to refresh parameter")
        
        # Get quotes from Tastytrade API
        quotes = client.get_quotes(symbol_list)
        
        logger.info(f"API endpoint returning quotes for {len(quotes)} symbols")
        
        # Check if we got all requested quotes
        if len(quotes) < len(symbol_list):
            missing = [s for s in symbol_list if s not in quotes]
            logger.warning(f"Could not retrieve quotes for: {missing}")
        
        if not quotes:
            logger.warning("No quotes available - streaming data unavailable")
        
        return quotes
        
    except Exception as e:
        logger.error(f"Error fetching quotes from Tastytrade: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch quotes: {str(e)}")




@app.get("/api/accounts")
async def get_accounts():
    """Get all available accounts"""
    try:
        accounts = db.get_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/account-balances")
async def get_account_balances(account_number: Optional[str] = None):
    """Get account balances for specified account or all accounts"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            if account_number:
                query = """
                    SELECT * FROM account_balances 
                    WHERE account_number = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """
                cursor.execute(query, (account_number,))
            else:
                query = """
                    SELECT * FROM account_balances
                    WHERE timestamp = (
                        SELECT MAX(timestamp) 
                        FROM account_balances ab2 
                        WHERE ab2.account_number = account_balances.account_number
                    )
                    ORDER BY account_number
                """
                cursor.execute(query)
            
            columns = [desc[0] for desc in cursor.description]
            balances = []
            for row in cursor.fetchall():
                balance = dict(zip(columns, row))
                balances.append(balance)
            
            return {"balances": balances}
    except Exception as e:
        logger.error(f"Error getting account balances: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions/cached")
async def get_cached_positions(account_number: Optional[str] = None):
    """Get cached positions immediately without sync - for fast loading"""
    try:
        positions = db.get_open_positions()
        
        # Get the last sync timestamp for freshness metadata
        last_sync = db.get_last_sync_timestamp()
        
        # Calculate data age
        data_age_minutes = None
        if last_sync:
            data_age_minutes = (datetime.now() - last_sync).total_seconds() / 60
            
        # Group positions by account (matching the expected frontend format)
        positions_by_account = {}
        for position in positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)
        
        # Get cached quotes for immediate display
        cached_quotes = db.get_cached_quotes()
        
        return {
            "positions": positions_by_account,
            "quotes": cached_quotes,
            "cache_info": {
                "last_sync": last_sync.isoformat() if last_sync else None,
                "data_age_minutes": data_age_minutes,
                "is_fresh": data_age_minutes < 60 if data_age_minutes else False,
                "cached": True,
                "quotes_count": len(cached_quotes)
            }
        }
    except Exception as e:
        logger.error(f"Error fetching cached positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions")
async def get_positions(account_number: Optional[str] = None):
    """Get current open positions - this endpoint returns cached data but formatted for current frontend"""
    try:
        positions = db.get_open_positions()
        
        # Group positions by account (matching the expected frontend format)
        positions_by_account = {}
        for position in positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)
        
        return positions_by_account
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard")
async def get_dashboard_data(account_number: Optional[str] = None):
    """Get dashboard summary data using the new order-based system"""
    try:
        # Use the same logic as the chains endpoint
        chains = order_manager.get_order_chains(account_number=account_number)
        
        # Process chains with the same logic as the chains endpoint
        processed_chains = []
        for chain in chains:
            # Get orders for this chain
            orders = []
            try:
                # Get orders from the chain
                chain_orders = chain.get('orders', [])
                
                # Filter out stock-only chains (same logic as chains endpoint)
                has_options = False
                for order in chain_orders:
                    positions = order.get('positions', [])
                    if any(pos['instrument_type'] == 'InstrumentType.EQUITY_OPTION' for pos in positions):
                        has_options = True
                        break
                
                if has_options:
                    processed_chains.append(chain)
                    
            except Exception as e:
                logger.warning(f"Error processing chain {chain.get('chain_id', 'unknown')}: {e}")
                continue
        
        # Calculate statistics from chains data
        open_chains = [c for c in processed_chains if c['chain_status'] == 'OPEN']
        closed_chains = [c for c in processed_chains if c['chain_status'] == 'CLOSED']
        
        total_pnl = sum(c['total_pnl'] for c in processed_chains)
        realized_pnl = sum(c['realized_pnl'] for c in processed_chains)
        
        # Calculate win rate from closed chains
        profitable_closed = [c for c in closed_chains if c['total_pnl'] > 0]
        win_rate = len(profitable_closed) / len(closed_chains) * 100 if closed_chains else 0
        
        # Get order statistics
        try:
            order_stats = order_manager.get_order_statistics(account_number=account_number)
        except Exception as e:
            logger.warning(f"Could not get order statistics: {e}")
            order_stats = {}
        
        # Get strategy breakdown from chains
        strategy_breakdown = {}
        for chain in processed_chains:
            strategy = chain.get('strategy_type', 'Unknown')
            if strategy not in strategy_breakdown:
                strategy_breakdown[strategy] = {
                    'count': 0,
                    'total_pnl': 0,
                    'closed_count': 0,
                    'wins': 0
                }
            
            strategy_breakdown[strategy]['count'] += 1
            strategy_breakdown[strategy]['total_pnl'] += chain['total_pnl']
            
            if chain['chain_status'] == 'CLOSED':
                strategy_breakdown[strategy]['closed_count'] += 1
                if chain['total_pnl'] > 0:
                    strategy_breakdown[strategy]['wins'] += 1
        
        # Format strategy breakdown for frontend
        strategy_stats = []
        for strategy, stats in strategy_breakdown.items():
            strategy_stats.append({
                'strategy_type': strategy,
                'count': stats['count'],
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / stats['count'] if stats['count'] > 0 else 0,
                'wins': stats['wins'],
                'closed_count': stats['closed_count'],
                'win_rate': stats['wins'] / stats['closed_count'] * 100 if stats['closed_count'] > 0 else 0
            })
        
        return {
            "summary": {
                "total_trades": len(processed_chains),
                "open_trades": len(open_chains),
                "closed_trades": len(closed_chains),
                "total_pnl": total_pnl,
                "win_rate": win_rate
            },
            "order_summary": order_stats,
            "strategy_breakdown": strategy_stats,
            "recent_trades": []  # Could implement this later if needed
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync")
async def sync_unified():
    """Unified sync endpoint with smart date range calculation"""
    try:
        from datetime import datetime, timedelta
        
        # Check last sync timestamp to determine date range
        last_sync = db.get_last_sync_timestamp()
        
        if last_sync:
            # Calculate days back from last sync + 1 day buffer
            days_back = (datetime.now() - last_sync).days + 1
            days_back = max(days_back, 1)  # Minimum 1 day
            days_back = min(days_back, 90)  # Maximum 90 days for safety
            logger.info(f"Incremental sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
        else:
            # No previous sync, fetch last 90 days
            days_back = 90
            logger.info(f"First sync detected, fetching {days_back} days")
        
        # Initialize clients
        tastytrade = TastytradeClient()
        
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
        transactions = tastytrade.get_transactions(days_back=days_back)
        logger.info(f"Fetched {len(transactions)} transactions")
        
        # Save raw transactions first (for order ID support)
        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")
        
        # Transaction data has been saved to raw_transactions table
        # Skip legacy trade processing - OrderManager will handle this later
        saved_count = len(transactions)
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        
        # Also fetch and save current positions for all accounts
        logger.info("Fetching current positions from all accounts...")
        all_positions = tastytrade.get_positions()
        total_positions = 0
        
        for account_number, positions in all_positions.items():
            if positions:
                # Calculate opening dates for positions
                positions_with_dates = calculate_position_opening_dates(positions, account_number)
                success = db.save_positions(positions_with_dates, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")
        
        # Fetch and save account balances for all accounts
        logger.info("Fetching account balances...")
        balances = tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")
        
        logger.info(f"Sync completed: {saved_count} transactions processed, {total_positions} positions updated")
        
        # Update last sync timestamp
        db.update_last_sync_timestamp()
        logger.info("Updated last sync timestamp")
        
        # Automatically reprocess chains after syncing new orders
        logger.info("Auto-reprocessing chains after sync...")
        try:
            chain_result = order_manager.reprocess_orders_and_chains_from_database()
            if 'error' in chain_result:
                logger.error(f"Chain reprocessing error: {chain_result['error']}")
            else:
                logger.info(f"Chain reprocessing completed: {chain_result['orders_saved']} orders, {chain_result['chains_saved']} chains")
        except Exception as e:
            logger.error(f"Error during auto chain reprocessing: {str(e)}")
        
        return {
            "message": f"Sync completed: {saved_count} new transactions processed",
            "transactions_processed": saved_count,
            "positions_updated": total_positions,
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
        }
    except Exception as e:
        logger.error(f"Sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sync/status")
async def get_sync_status():
    """Get sync status including last sync timestamp"""
    try:
        last_sync = db.get_last_sync_timestamp()
        return {
            "last_sync": last_sync.isoformat() if last_sync else None,
            "has_synced": db.is_initial_sync_completed()
        }
    except Exception as e:
        logger.error(f"Error getting sync status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/migrate-realized-pnl")
async def migrate_realized_pnl():
    """One-time migration to populate realized_pnl for existing chains"""
    try:
        logger.info("Starting realized P&L migration...")
        
        # Get all chains for complete recalculation
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chain_id FROM order_chains")
            chain_ids = [row[0] for row in cursor.fetchall()]
        
        updated_count = 0
        for chain_id in chain_ids:
            try:
                order_manager.update_chain_pnl(chain_id)
                updated_count += 1
            except Exception as e:
                logger.error(f"Error updating chain {chain_id}: {e}")
        
        logger.info(f"Realized P&L migration completed: {updated_count} chains updated")
        
        return {
            "message": f"Migration completed successfully",
            "chains_updated": updated_count,
            "total_chains": len(chain_ids)
        }
    except Exception as e:
        logger.error(f"Error during realized P&L migration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debug/chains")
async def debug_chains():
    """Debug endpoint to check realized_pnl values"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chain_id, underlying, chain_status, total_pnl, realized_pnl, unrealized_pnl 
                FROM order_chains 
                ORDER BY created_at DESC 
                LIMIT 10
            """)
            chains = [dict(row) for row in cursor.fetchall()]
        
        return {"chains": chains}
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync/initial")
async def initial_sync():
    """Complete initial sync - clears database and rebuilds from scratch"""
    try:
        logger.info("Starting INITIAL SYNC - this will rebuild the entire database")
        
        # Reset sync metadata
        logger.info("Resetting sync metadata...")
        db.reset_sync_metadata()
        
        # Note: User data preservation removed since we're moving away from trades model
        logger.info("Skipping user data preservation (moving to order-based system)")
        
        # Clear and recreate database tables with latest schema
        logger.info("Clearing existing database and recreating tables...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Drop order-related tables to ensure clean schema
            cursor.execute("DROP TABLE IF EXISTS order_chain_members")
            cursor.execute("DROP TABLE IF EXISTS order_chains") 
            cursor.execute("DROP TABLE IF EXISTS positions_new")
            cursor.execute("DROP TABLE IF EXISTS orders")
            
            # Clear data tables but keep structure
            cursor.execute("DELETE FROM positions")  # Keep for current positions
            cursor.execute("DELETE FROM account_balances")
            cursor.execute("DELETE FROM raw_transactions")  # Clear raw transactions too
            
            logger.info("Database cleared successfully")
        
        # Reinitialize database to create tables with latest schema
        logger.info("Recreating database tables with latest schema...")
        db.initialize_database()
        
        # Initialize clients
        tastytrade = TastytradeClient()
        
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
        
        # Process transactions into orders and chains using OrderManager
        logger.info("Processing transactions into orders and chains...")
        
        # Filter out non-trading transactions 
        trading_transactions = [
            tx for tx in transactions 
            if tx.get('instrument_type') is not None and tx.get('symbol') is not None
        ]
        
        logger.info(f"Processing {len(trading_transactions)} trading transactions (filtered from {len(transactions)} total)")
        
        # Use OrderManager to process transactions
        result = order_manager.process_transactions_to_orders_and_chains(trading_transactions)
        
        logger.info(f"Processed {result['orders_processed']} orders, saved {result['orders_saved']}, created {result['chains_created']} chains, saved {result['chains_saved']}")
        
        # Fetch and save current positions for all accounts
        logger.info("Fetching current positions from all accounts...")
        all_positions = tastytrade.get_positions()
        total_positions = 0
        
        for account_number, positions in all_positions.items():
            if positions:
                # Calculate opening dates for positions
                positions_with_dates = calculate_position_opening_dates(positions, account_number)
                success = db.save_positions(positions_with_dates, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")
        
        # Fetch and save account balances for all accounts
        logger.info("Fetching account balances...")
        balances = tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")
        
        logger.info(f"INITIAL SYNC completed: {result['orders_saved']} orders saved, {result['chains_saved']} chains created, {total_positions} positions updated")
        
        # Update last sync timestamp and mark initial sync completed
        db.update_last_sync_timestamp()
        db.mark_initial_sync_completed()
        logger.info("Updated last sync timestamp and marked initial sync completed")
        
        # Automatically reprocess chains after initial sync
        logger.info("Auto-reprocessing chains after initial sync...")
        try:
            chain_result = order_manager.reprocess_orders_and_chains_from_database()
            if 'error' in chain_result:
                logger.error(f"Chain reprocessing error: {chain_result['error']}")
            else:
                logger.info(f"Chain reprocessing completed: {chain_result['orders_saved']} orders, {chain_result['chains_saved']} chains")
        except Exception as e:
            logger.error(f"Error during auto chain reprocessing: {str(e)}")
        
        return {
            "message": f"Initial sync completed successfully",
            "orders_processed": result['orders_processed'],
            "orders_saved": result['orders_saved'],
            "chains_created": result['chains_created'],
            "chains_saved": result['chains_saved'],
            "positions_updated": total_positions,
            "transactions_processed": len(transactions),
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
        }
    except Exception as e:
        logger.error(f"Initial sync error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reprocess-chains")
async def reprocess_chains():
    """Reprocess orders and chains from existing raw transactions"""
    try:
        logger.info("Starting chain reprocessing from database")
        
        # Use OrderManager to reprocess from database
        result = order_manager.reprocess_orders_and_chains_from_database()
        
        if 'error' in result:
            logger.error(f"Reprocessing error: {result['error']}")
            raise HTTPException(status_code=500, detail=result['error'])
        
        logger.info(f"Reprocessing completed: {result['orders_saved']} orders, {result['chains_saved']} chains")
        
        return {
            "message": f"Reprocessing completed successfully",
            "orders_processed": result['orders_processed'],
            "orders_saved": result['orders_saved'],
            "chains_created": result['chains_created'],
            "chains_saved": result['chains_saved']
        }
        
    except Exception as e:
        logger.error(f"Reprocessing error: {str(e)}", exc_info=True)
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


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.websocket("/ws/quotes")
async def websocket_quotes(websocket: WebSocket):
    """WebSocket endpoint for streaming live quotes"""
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    
    client = None
    subscribed_symbols = []
    
    try:
        # Send a connection confirmation
        await websocket.send_json({"type": "connected", "message": "WebSocket connected"})
        
        # Initialize Tastytrade client
        client = TastytradeClient()
        
        # Authenticate with Tastytrade
        if not client.authenticate():
            logger.error("Tastytrade authentication failed for WebSocket")
            await websocket.send_json({"error": "Failed to authenticate with Tastytrade"})
            await websocket.close()
            return
        
        logger.info("WebSocket client connected and Tastytrade authenticated")
        
        # Create tasks for receiving messages and sending updates
        async def receive_messages():
            nonlocal subscribed_symbols
            try:
                while True:
                    data = await websocket.receive_json()
                    
                    if "subscribe" in data:
                        symbols = data["subscribe"]
                        if isinstance(symbols, list):
                            subscribed_symbols = symbols
                            logger.info(f"WebSocket subscribing to quotes for: {symbols}")
                            
                            # Send initial quotes
                            if subscribed_symbols:
                                quotes = client.get_quotes(subscribed_symbols)
                                await websocket.send_json({
                                    "type": "quotes",
                                    "data": quotes
                                })
                    
                    elif "unsubscribe" in data:
                        subscribed_symbols = []
                        logger.info("WebSocket unsubscribed from all quotes")
                    
                    elif "ping" in data:
                        # Keep-alive ping
                        await websocket.send_json({"pong": True})
                        
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected")
                raise
                
        async def send_updates():
            try:
                while True:
                    # Wait before sending next update
                    await asyncio.sleep(5)  # Update every 5 seconds
                    
                    # Check if WebSocket is still open before sending
                    if websocket.client_state.value != 1:  # 1 = OPEN
                        logger.info("WebSocket closed, stopping quote updates")
                        break
                    
                    if subscribed_symbols:
                        # Clear cache to get fresh quotes
                        client.clear_quote_cache()
                        quotes = client.get_quotes(subscribed_symbols)
                        
                        # Cache quotes in database for persistence
                        for symbol, quote_data in quotes.items():
                            if quote_data:  # Only cache if we have valid data
                                db.cache_quote(symbol, quote_data)
                        
                        try:
                            await websocket.send_json({
                                "type": "quotes",
                                "data": quotes,
                                "timestamp": datetime.now().isoformat()
                            })
                            logger.debug(f"Sent quote update for {len(quotes)} symbols, cached to database")
                        except Exception as send_error:
                            logger.info(f"WebSocket send failed (connection likely closed): {send_error}")
                            break
                        
            except asyncio.CancelledError:
                logger.info("Quote update task cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in send_updates: {str(e)}")
                raise
        
        # Run both tasks concurrently
        try:
            await asyncio.gather(
                receive_messages(),
                send_updates(),
                return_exceptions=True  # Don't fail if one task has an exception
            )
        except Exception as e:
            logger.info(f"WebSocket tasks completed with: {e}")
        
    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
    finally:
        logger.info("WebSocket connection closed")








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