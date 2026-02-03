#!/usr/bin/env python3

"""
OptionEdge Web Application
A beautiful, local web app for tracking and analyzing options trades
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
from src.models.position_enricher import PositionEnricher
from src.models.lot_manager import LotManager
from src.utils.auth_manager import AuthManager

# Configure logging
logger.add(
    "logs/webapp_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)

# Initialize FastAPI app
app = FastAPI(
    title="OptionEdge",
    description="Personal Options Trading Analytics",
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

# V3 Lot-based position tracking
lot_manager = LotManager(db)

# Initialize V2 processors with V3 lot_manager
order_processor_v2 = OrderProcessorV2(db, position_manager, lot_manager)
strategy_detector = StrategyDetector(db)
pnl_calculator_v2 = PnLCalculatorV2(db, position_manager, lot_manager)

# Initialize authentication manager
auth_manager = AuthManager()


def calculate_position_opening_dates(positions: List[Dict[str, Any]], account_number: str) -> List[Dict[str, Any]]:
    """Calculate opening dates for positions based on transaction history - HIGHLY OPTIMIZED"""

    if not positions:
        return positions

    # Single optimized query to get all opening dates for this account's symbols
    position_symbols = [pos['symbol'] for pos in positions]
    opening_dates = {}

    if position_symbols:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Batch query for all symbols at once - much more efficient
            placeholders = ','.join(['?' for _ in position_symbols])
            cursor.execute(f"""
                SELECT symbol, MIN(executed_at) as earliest_date
                FROM raw_transactions
                WHERE account_number = ?
                AND symbol IN ({placeholders})
                AND action IN ('OrderAction.BUY_TO_OPEN', 'OrderAction.SELL_TO_OPEN')
                GROUP BY symbol
            """, [account_number] + position_symbols)

            for row in cursor.fetchall():
                opening_dates[row['symbol']] = row['earliest_date']

    # Apply opening dates to positions
    for position in positions:
        symbol = position.get('symbol')
        position['opened_at'] = opening_dates.get(symbol)

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
class LoginRequest(BaseModel):
    """Request model for user login"""
    username: str
    password: str


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
    logger.info("Starting OptionEdge Web App")
    db.initialize_database()

    # Note: Auto-sync disabled since credentials are not stored
    # Sync must be triggered manually by authenticated users via the web UI
    # If you want auto-sync, configure TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD
    # environment variables and uncomment the code below

    # # Check if we need to automatically sync on startup
    # try:
    #     last_sync = db.get_last_sync_timestamp()
    #     if last_sync:
    #         # Calculate time since last sync
    #         time_since_sync = datetime.now() - last_sync
    #         hours_since_sync = time_since_sync.total_seconds() / 3600
    #
    #         # Auto-sync if it's been more than 6 hours since last sync and it's market hours
    #         if hours_since_sync > 6:
    #             logger.info(f"Auto-sync triggered: {hours_since_sync:.1f} hours since last sync")
    #             # Note: Auto-sync runs in background, don't await to avoid blocking startup
    #             asyncio.create_task(background_auto_sync())
    #         else:
    #             logger.info(f"No auto-sync needed: {hours_since_sync:.1f} hours since last sync")
    #     else:
    #         logger.info("No previous sync found - auto-sync will be triggered on first manual sync")
    # except Exception as e:
    #     logger.warning(f"Error checking auto-sync: {e}")


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


async def require_auth(request: Request) -> str:
    """
    Verify that the request has valid authentication.

    Returns the username if authenticated.
    Raises HTTPException with 401 status if not authenticated.
    """
    session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = auth_manager.get_session_username(session_id)
    if not username:
        raise HTTPException(status_code=401, detail="Session invalid or expired")

    return username


@app.get("/", response_class=HTMLResponse)
@app.get("/positions", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application - Open Positions Page"""
    # Check authentication
    try:
        await require_auth(request)
    except HTTPException:
        # Redirect to login page if not authenticated
        return HTMLResponse(content="<script>window.location.href = '/login';</script>", status_code=401)

    # Use absolute path to work in bundled Tauri app and development
    app_dir = os.path.dirname(os.path.abspath(__file__))
    positions_file = os.path.join(app_dir, "static", "positions-dense.html")
    with open(positions_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/chains", response_class=HTMLResponse)
async def order_chains(request: Request):
    """Serve the Order Chains page"""
    # Check authentication
    try:
        await require_auth(request)
    except HTTPException:
        # Redirect to login page if not authenticated
        return HTMLResponse(content="<script>window.location.href = '/login';</script>", status_code=401)

    # Use absolute path to work in bundled Tauri app and development
    app_dir = os.path.dirname(os.path.abspath(__file__))
    chains_file = os.path.join(app_dir, "static", "chains-dense.html")
    with open(chains_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the Performance Reports page"""
    # Check authentication
    try:
        await require_auth(request)
    except HTTPException:
        # Redirect to login page if not authenticated
        return HTMLResponse(content="<script>window.location.href = '/login';</script>", status_code=401)

    # Use absolute path to work in bundled Tauri app and development
    app_dir = os.path.dirname(os.path.abspath(__file__))
    reports_file = os.path.join(app_dir, "static", "reports-dense.html")
    with open(reports_file, "r", encoding="utf-8") as f:
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
    return {"status": "ok", "service": "OptionEdge"}


# ============================================================================
# Authentication Endpoints
# ============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve the login page"""
    # Use absolute path to work in bundled Tauri app and development
    app_dir = os.path.dirname(os.path.abspath(__file__))
    login_file = os.path.join(app_dir, "static", "login.html")
    with open(login_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """
    Authenticate user with Tastytrade credentials.

    Returns session cookie on successful authentication.
    """
    success, session_id = auth_manager.authenticate(request.username, request.password)

    if success:
        # Create response with session cookie
        response = JSONResponse(
            {"message": "Login successful"},
            status_code=200
        )
        # Set session cookie (HttpOnly for security, expires on browser close)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=3600  # 1 hour
        )
        logger.info(f"User authenticated: {request.username}")
        return response
    else:
        logger.warning(f"Failed login attempt for user: {request.username}")
        raise HTTPException(status_code=401, detail="Invalid username or password")


@app.post("/api/auth/logout")
async def logout(request: Request):
    """
    Logout the current user by invalidating their session.
    """
    session_id = request.cookies.get("session_id")

    if session_id:
        auth_manager.logout(session_id)
        logger.info("User logged out")

    # Clear session cookie
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie("session_id")
    return response


@app.get("/api/auth/verify")
async def verify_auth(request: Request):
    """
    Verify if the current session is valid.

    Used by frontend to check authentication status.
    """
    session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = auth_manager.get_session_username(session_id)
    if not username:
        raise HTTPException(status_code=401, detail="Session invalid or expired")

    return {"authenticated": True, "username": username}


async def should_use_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None) -> bool:
    """Check if cached chain data exists for the requested account"""
    # TEMPORARY: Use cache when available per-account
    # The V2 path has compatibility issues with order.transactions that need refactoring
    # For now, cached path works correctly and is performant
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Check if we have cached chains for THIS account or "All Accounts"
            if account_number == '':
                # Empty string = "All Accounts" → check if we have any cached chains at all
                cursor.execute("SELECT COUNT(*) FROM order_chains LIMIT 1")
            elif account_number:
                # Specific account number → check for chains in that account
                cursor.execute("SELECT COUNT(*) FROM order_chains WHERE account_number = ? LIMIT 1", (account_number,))
            else:
                # None (no parameter passed) → check if we have any cached chains
                # This shouldn't happen in normal operation but handle it for backward compatibility
                cursor.execute("SELECT COUNT(*) FROM order_chains LIMIT 1")
            count = cursor.fetchone()[0]
            has_cache = count > 0
            if has_cache:
                account_display = account_number if account_number is not None else "unspecified"
                logger.debug(f"Using cached chains for account {account_display} (V2 primary path temporarily disabled)")
            return has_cache
    except Exception as e:
        logger.error(f"Error checking cache: {e}")
        return False


async def get_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None,
                          limit: int = 10000, offset: int = 0):
    """Get chains from cached data in order_chains table"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build query with filters
            query = """
                SELECT oc.chain_id, oc.underlying, oc.strategy_type, oc.opening_date,
                       oc.closing_date, oc.chain_status, oc.order_count, oc.total_pnl,
                       oc.realized_pnl, oc.unrealized_pnl, oc.account_number
                FROM order_chains oc
            """
            params = []
            where_conditions = []

            # Only filter by account if it's a non-empty string (specific account)
            # Empty string = "All Accounts" → no account filter
            # None = backward compatibility → no account filter
            if account_number and account_number != '':
                where_conditions.append("oc.account_number = ?")
                params.append(account_number)

            if underlying:
                where_conditions.append("oc.underlying = ?")
                params.append(underlying)
            
            if where_conditions:
                query += " WHERE " + " AND ".join(where_conditions)
            
            query += " ORDER BY oc.opening_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            chain_rows = cursor.fetchall()
            
            if not chain_rows:
                return {"chains": [], "total": 0}
            
            # Get total count for pagination
            count_query = "SELECT COUNT(*) FROM order_chains oc"
            count_params = []
            if where_conditions:
                count_query += " WHERE " + " AND ".join(where_conditions)
                count_params = params[:-2]  # Remove limit and offset
            
            cursor.execute(count_query, count_params)
            total_count = cursor.fetchone()[0]
            
            # Format cached chains for frontend with complete order data
            formatted_chains = []
            for row in chain_rows:
                chain_id, underlying, strategy_type, opening_date, closing_date, chain_status = row[:6]
                order_count, total_pnl, realized_pnl, unrealized_pnl, account_number = row[6:]
                
                # Load complete order data from cache
                cursor.execute("""
                    SELECT order_data FROM order_chain_cache 
                    WHERE chain_id = ? 
                    ORDER BY order_id
                """, (chain_id,))
                
                order_rows = cursor.fetchall()
                orders = []
                import json
                
                for order_row in order_rows:
                    try:
                        order_data = json.loads(order_row[0])
                        orders.append(order_data)
                    except (json.JSONDecodeError, IndexError) as e:
                        logger.warning(f"Failed to parse cached order data for chain {chain_id}: {e}")
                        continue
                
                # If strategy is None, convert to Unknown for display
                if strategy_type is None:
                    strategy_type = "Unknown"
                
                # Calculate cost basis, net liquidity, and fees for cached chains
                cost_basis_total = 0.0
                cost_basis_per_unit = 0.0
                opening_quantity_total = 0
                total_commission = 0.0
                total_regulatory_fees = 0.0
                total_clearing_fees = 0.0
                net_liquidity = 0.0

                # Calculate metrics from cached order data
                if orders:
                    # For multi-leg spreads, all legs have the same quantity, so use the first leg's quantity
                    for order in orders:
                        # Count opening quantities and calculate cost basis
                        if order.get('positions'):
                            for pos in order['positions']:
                                if pos.get('status') == 'OPEN' or not pos.get('closing_action'):
                                    opening_quantity_total = abs(pos.get('quantity', 0))  # Use first opening qty, don't sum
                                    break
                            if opening_quantity_total > 0:
                                break

                    # Cost basis from total credit/debit - including ALL orders in the chain
                    # This is the running cost basis across opening, rolls, and closing orders
                    total_credit = 0.0
                    total_debit = 0.0
                    for order in orders:
                        order_type = order.get('order_type', 'UNKNOWN')
                        for pos in order.get('positions', []):
                            qty = abs(pos.get('quantity', 0))

                            # For cached data, closing orders store the closing action in opening_action field
                            if order_type == 'CLOSING':
                                # This position's opening_action is actually the closing action
                                action = str(pos.get('opening_action', ''))
                                price = pos.get('opening_price', 0)  # Opening price field holds the closing price

                                if price and qty > 0:
                                    amount = price * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else price * qty
                                    # For closing: BTC (buy to close) a short = debit, STC (sell to close) a long = credit
                                    if 'BTC' in action or 'BUY_TO_CLOSE' in action:
                                        total_debit += amount
                                    elif 'STC' in action or 'SELL_TO_CLOSE' in action:
                                        total_credit += amount
                            else:
                                # For opening orders, use opening_action and opening_price
                                if pos.get('opening_price') and qty > 0:
                                    amount = pos['opening_price'] * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else pos['opening_price'] * qty
                                    action = str(pos.get('opening_action', ''))
                                    # SELL actions (STO) are credits, BUY actions (BTO) are debits
                                    if 'BUY_TO_' in action or 'BTO' in action or action == 'BUY':
                                        total_debit += amount
                                    elif 'SELL_TO_' in action or 'STO' in action or action == 'SELL':
                                        total_credit += amount

                                # Include closing transactions if they exist in opening orders
                                if pos.get('closing_price') and pos.get('closing_action') and qty > 0:
                                    amount = pos['closing_price'] * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else pos['closing_price'] * qty
                                    closing_action = str(pos.get('closing_action', ''))
                                    if 'BTC' in closing_action or 'BUY' in closing_action:
                                        total_debit += amount
                                    elif 'STC' in closing_action or 'SELL' in closing_action:
                                        total_credit += amount

                    if total_debit > 0 or total_credit > 0:
                        # Preserve sign: negative = money spent (long), positive = money received (short)
                        cost_basis_total = total_credit - total_debit
                        cost_basis_per_unit = 0.0
                        cost_basis_per_share = 0.0
                        pnl_per_share = 0.0
                        if opening_quantity_total > 0:
                            cost_basis_per_unit = cost_basis_total / opening_quantity_total
                            cost_basis_per_share = cost_basis_per_unit / 100  # Convert to per-share
                            # For closed chains, calculate P&L per share
                            pnl_per_share = realized_pnl / opening_quantity_total / 100

                # Get net liquidity for open chains
                if chain_status == 'OPEN':
                    try:
                        # Collect all unique symbols from this chain's order positions
                        chain_symbols = set()
                        for order in (orders or []):
                            for pos in order.get('positions', []):
                                if pos.get('symbol'):
                                    chain_symbols.add(pos['symbol'].strip())

                        # Get all open positions and filter by specific symbols in this chain
                        positions = db.get_open_positions()
                        if positions and chain_symbols:
                            for pos in positions:
                                pos_symbol = (pos.get('symbol') or '').strip()
                                if (pos_symbol in chain_symbols and
                                    pos.get('account_number') == account_number):
                                    net_liquidity += float(pos.get('market_value', 0))
                    except Exception as e:
                        logger.warning(f"Could not calculate net liquidity for cached chain {chain_id}: {e}")

                formatted_chain = {
                    'chain_id': chain_id,
                    'underlying': underlying,
                    'strategy_type': strategy_type,
                    'opening_date': opening_date,
                    'closing_date': closing_date,
                    'status': chain_status,
                    'order_count': order_count,
                    'cost_basis_total': cost_basis_total,
                    'cost_basis_per_unit': cost_basis_per_unit,
                    'cost_basis_per_share': cost_basis_per_share,
                    'pnl_per_share': pnl_per_share,
                    'total_pnl': total_pnl or 0.0,
                    'realized_pnl': realized_pnl or 0.0,
                    'unrealized_pnl': unrealized_pnl or 0.0,
                    'net_liquidity': net_liquidity,
                    'total_commission': total_commission,
                    'total_regulatory_fees': total_regulatory_fees,
                    'total_clearing_fees': total_clearing_fees,
                    'total_fees': total_commission + total_regulatory_fees + total_clearing_fees,
                    'account_number': account_number,
                    'orders': orders  # Now includes complete order data from cache
                }
                formatted_chains.append(formatted_chain)
            
            return {
                "chains": formatted_chains,
                "total": total_count,
                "cached": True  # Indicate this came from cache
            }
            
    except Exception as e:
        logger.error(f"Error getting cached chains: {e}")
        return None


async def update_chain_cache(chains, affected_underlyings: set = None):
    """Update the order_chains table with fresh V2 derivation results

    Args:
        chains: List of Chain objects to cache
        affected_underlyings: Optional set of underlyings to update incrementally.
                             If None, clears and rebuilds entire cache.
    """
    if affected_underlyings:
        logger.info(f"[CACHE UPDATE] Incremental update for {len(affected_underlyings)} underlyings: {affected_underlyings}")
    logger.info(f"[CACHE UPDATE] Starting update with {len(chains)} chains")
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Preserve existing working strategies before clearing cache
            cursor.execute("""
                CREATE TEMP TABLE IF NOT EXISTS preserved_strategies AS
                SELECT chain_id, strategy_type
                FROM order_chains
                WHERE strategy_type IS NOT NULL AND strategy_type != 'Unknown' AND strategy_type != 'None'
                AND chain_id LIKE '%MERGED%'
            """)

            if affected_underlyings:
                # Incremental update: only clear chains for affected underlyings
                placeholders = ','.join('?' * len(affected_underlyings))
                cursor.execute(f"""
                    DELETE FROM order_chain_cache WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE underlying IN ({placeholders})
                    )
                """, tuple(affected_underlyings))
                cursor.execute(f"""
                    DELETE FROM order_chain_members WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE underlying IN ({placeholders})
                    )
                """, tuple(affected_underlyings))
                cursor.execute(f"DELETE FROM order_chains WHERE underlying IN ({placeholders})",
                              tuple(affected_underlyings))
                logger.info(f"[CACHE UPDATE] Cleared cache for underlyings: {affected_underlyings}")
            else:
                # Full rebuild: clear entire cache
                cursor.execute("DELETE FROM order_chains")
                cursor.execute("DELETE FROM order_chain_members")
                cursor.execute("DELETE FROM order_chain_cache")
            
            current_time = datetime.now()
            
            for chain in chains:
                # Check for preserved strategy first
                cursor.execute("SELECT strategy_type FROM preserved_strategies WHERE chain_id = ?", (chain.chain_id,))
                preserved_result = cursor.fetchone()
                
                if preserved_result:
                    detected_strategy = preserved_result[0]
                    logger.info(f"Using preserved strategy for chain {chain.chain_id}: {detected_strategy}")
                else:
                    # Detect strategy for this chain
                    try:
                        # Debug the chain structure before detection
                        if chain.underlying in ["CSX", "GOOG", "USO"]:
                            logger.warning(f"[DEBUG] Processing {chain.underlying} chain {chain.chain_id}")
                            if chain.orders:
                                opening_orders = [o for o in chain.orders if o.order_type.value == 'OPENING']
                                if opening_orders:
                                    logger.warning(f"  Found {len(opening_orders)} opening orders")
                                    for tx in opening_orders[0].transactions[:2]:
                                        logger.warning(f"    TX: symbol={tx.symbol}, option_type={tx.option_type}, strike={tx.strike}, action={tx.action}")
                                else:
                                    logger.warning(f"  No opening orders found")
                            else:
                                logger.warning(f"  No orders in chain")
                        
                        detected_strategy = strategy_detector.detect_chain_strategy(chain)
                        
                        if chain.underlying in ["CSX", "GOOG", "USO"]:
                            logger.warning(f"  Detected strategy: {detected_strategy}")
                        
                        # Ensure we never store None
                        if detected_strategy is None:
                            detected_strategy = "Unknown"
                    except Exception as e:
                        logger.warning(f"Strategy detection failed for chain {chain.chain_id}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        detected_strategy = "Unknown"
                
                # Calculate P&L values
                total_pnl = 0.0
                realized_pnl = 0.0
                unrealized_pnl = 0.0
                
                for order in chain.orders:
                    # Calculate order P&L from transactions since V2 Order doesn't have total_pnl
                    order_pnl = 0.0
                    for tx in order.transactions:
                        # For cash settlements, use net_value directly (price contains strike, not premium)
                        if tx.is_cash_settlement:
                            # net_value is already signed correctly (negative for loss, positive for gain)
                            order_pnl += tx.net_value
                        elif tx.is_closing:
                            # For closing transactions, calculate P&L vs opening price
                            # This is simplified - the V2 frontend does more complex P&L calc
                            value = tx.price * abs(tx.quantity) * 100
                            if tx.is_sell:
                                order_pnl += value
                            else:
                                order_pnl -= value
                        else:
                            # For opening transactions, track as unrealized
                            value = tx.price * abs(tx.quantity) * 100
                            if tx.is_sell:
                                order_pnl += value
                            else:
                                order_pnl -= value

                    total_pnl += order_pnl
                    
                    if order.order_type.value == 'CLOSING':
                        realized_pnl += order_pnl
                    else:
                        unrealized_pnl += order_pnl
                
                # Debug: Log what we're about to insert
                if chain.underlying in ["CSX", "GOOG", "USO"]:
                    logger.warning(f"[INSERT] About to insert chain {chain.chain_id} with strategy_type = {repr(detected_strategy)}")

                # V3: Calculate lot-based chain metadata
                has_assignment = any(
                    any(tx.is_assignment for tx in order.transactions)
                    for order in chain.orders
                )

                assignment_date = None
                if has_assignment:
                    for order in chain.orders:
                        for tx in order.transactions:
                            if tx.is_assignment:
                                assignment_date = tx.executed_at.date() if tx.executed_at else None
                                break
                        if assignment_date:
                            break

                # Get leg count and quantity info from lots
                leg_count = 1
                original_quantity = None
                remaining_quantity = None

                try:
                    lots = lot_manager.get_lots_for_chain(chain.chain_id, include_derived=False)
                    if lots:
                        leg_count = max(lot.leg_index + 1 for lot in lots)
                        original_quantity = sum(lot.original_quantity for lot in lots)
                        remaining_quantity = sum(abs(lot.remaining_quantity) for lot in lots if lot.status != 'CLOSED')
                except Exception as lot_err:
                    logger.debug(f"Could not get lot metadata for chain {chain.chain_id}: {lot_err}")

                # Insert chain data with V3 columns
                cursor.execute("""
                    INSERT OR REPLACE INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id,
                        strategy_type, opening_date, closing_date, chain_status,
                        order_count, total_pnl, realized_pnl, unrealized_pnl,
                        leg_count, original_quantity, remaining_quantity,
                        has_assignment, assignment_date,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain.chain_id,
                    chain.underlying,
                    chain.account_number,
                    chain.orders[0].order_id if chain.orders else None,
                    detected_strategy,
                    chain.opening_date,
                    chain.closing_date,
                    chain.status,
                    len(chain.orders),
                    total_pnl,
                    realized_pnl,
                    unrealized_pnl,
                    leg_count,
                    original_quantity,
                    remaining_quantity,
                    has_assignment,
                    assignment_date,
                    current_time,
                    current_time
                ))
                
                # Insert chain membership links and cache complete order data
                for order in chain.orders:
                    cursor.execute("""
                        INSERT OR REPLACE INTO order_chain_members (chain_id, order_id)
                        VALUES (?, ?)
                    """, (chain.chain_id, order.order_id))

                    # Store complete order data as JSON
                    import json
                    # Calculate total P&L for this order
                    order_pnl = 0.0
                    for tx in order.transactions:
                        # For cash settlements, use net_value directly (price contains strike, not premium)
                        if tx.is_cash_settlement:
                            order_pnl += tx.net_value
                        else:
                            # Check if option by looking for strike price
                            multiplier = 100 if tx.strike is not None else 1
                            amount = tx.price * abs(tx.quantity) * multiplier
                            if tx.is_opening:
                                # Opening: sells are positive (credit), buys are negative (debit)
                                order_pnl += amount if 'SELL' in tx.action else -amount
                            else:
                                # Closing: sells are positive, buys are negative
                                order_pnl += amount if 'SELL' in tx.action else -amount
                    
                    order_data = {
                        "order_id": order.order_id,
                        "order_type": order.order_type.value,
                        "order_date": order.executed_at.date().isoformat() if order.executed_at else None,
                        "strategy_type": detected_strategy,
                        "status": "FILLED",
                        "total_pnl": order_pnl,
                        "positions": []
                    }
                    
                    # Add positions from transactions with lot data (V3)
                    for idx, tx in enumerate(order.transactions):
                        # For cash settlements, use net_value directly
                        if tx.is_cash_settlement:
                            tx_pnl = tx.net_value
                        else:
                            multiplier = 100 if tx.strike is not None else 1
                            tx_amount = tx.price * abs(tx.quantity) * multiplier
                            tx_pnl = tx_amount if 'SELL' in tx.action else -tx_amount

                        # V3: Try to find lot data for this transaction
                        lot_data = None
                        derived_positions = []

                        if tx.is_opening:
                            # Look up the lot created for this transaction
                            with db.get_connection() as lot_conn:
                                lot_cursor = lot_conn.cursor()
                                lot_cursor.execute("""
                                    SELECT id, remaining_quantity, original_quantity, status, leg_index
                                    FROM position_lots
                                    WHERE transaction_id = ?
                                """, (tx.id,))
                                lot_row = lot_cursor.fetchone()

                                if lot_row:
                                    lot_id = lot_row[0]
                                    lot_data = {
                                        "lot_id": lot_id,
                                        "leg_index": lot_row[4] or idx,
                                        "original_quantity": lot_row[2] or abs(tx.quantity),
                                        "remaining_quantity": lot_row[1] or abs(tx.quantity),
                                        "status": lot_row[3] or "OPEN"
                                    }

                                    # Check for derived positions (from assignment/exercise)
                                    lot_cursor.execute("""
                                        SELECT id, symbol, underlying, quantity, entry_price,
                                               remaining_quantity, status, derivation_type
                                        FROM position_lots
                                        WHERE derived_from_lot_id = ?
                                    """, (lot_id,))

                                    for derived_row in lot_cursor.fetchall():
                                        derived_positions.append({
                                            "lot_id": derived_row[0],
                                            "symbol": derived_row[1],
                                            "underlying": derived_row[2],
                                            "derivation_type": derived_row[7],
                                            "quantity": derived_row[3],
                                            "entry_price": derived_row[4],
                                            "remaining_quantity": derived_row[5],
                                            "status": derived_row[6]
                                        })

                        position_data = {
                            "position_id": f"{order.order_id}_{len(order_data['positions']) + 1}",
                            "symbol": tx.symbol,
                            "underlying": tx.underlying_symbol,
                            "instrument_type": "EQUITY_OPTION" if tx.strike else "EQUITY",
                            "option_type": tx.option_type,
                            "strike": tx.strike,
                            "expiration": tx.expiration.isoformat() if tx.expiration else None,
                            "quantity": tx.quantity,
                            "opening_action": tx.action,
                            "opening_price": tx.price,
                            "closing_action": None,
                            "closing_price": None,
                            "status": "OPEN" if order.order_type.value == "OPENING" else "CLOSED",
                            "opening_transaction_id": tx.id,
                            "closing_transaction_id": None,
                            "pnl": tx_pnl
                        }

                        # V3: Add lot data if available
                        if lot_data:
                            position_data["lot_id"] = lot_data["lot_id"]
                            position_data["leg_index"] = lot_data["leg_index"]
                            position_data["original_quantity"] = lot_data["original_quantity"]
                            position_data["remaining_quantity"] = lot_data["remaining_quantity"]

                            # Update status from lot
                            if lot_data["status"] == "CLOSED":
                                position_data["status"] = "CLOSED"
                            elif lot_data["status"] == "PARTIAL":
                                position_data["status"] = "PARTIAL"

                        if derived_positions:
                            position_data["derived_positions"] = derived_positions

                        order_data["positions"].append(position_data)
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO order_chain_cache (chain_id, order_id, order_data)
                        VALUES (?, ?, ?)
                    """, (chain.chain_id, order.order_id, json.dumps(order_data)))
            
            conn.commit()
            logger.info(f"[CACHE UPDATE] Successfully updated cache with {len(chains)} chains")
            
    except Exception as e:
        logger.error(f"[CACHE UPDATE] Error updating chain cache: {e}")
        import traceback
        logger.error(traceback.format_exc())


@app.get("/api/chains")
async def get_order_chains(
    account_number: Optional[str] = None,
    underlying: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0
):
    """Get order chains with intelligent caching for optimal performance"""
    import time
    start_time = time.time()
    logger.info(f"🕐 TIMING: Starting chains API request for account={account_number}, underlying={underlying}")

    try:
        # Re-enable caching now that cache has been rebuilt with order details
        use_cache = await should_use_cached_chains(account_number, underlying)
        
        if use_cache:
            # Fast path: return cached data
            cache_start = time.time()
            cached_result = await get_cached_chains(account_number, underlying, limit, offset)
            cache_time = time.time() - cache_start
            logger.info(f"🕐 TIMING: Cache lookup took {cache_time:.2f}s")
            if cached_result is not None:
                total_time = time.time() - start_time
                logger.info(f"🕐 TIMING: Total request time (cached): {total_time:.2f}s")
                return cached_result
            # If cache fails, fall through to V2 derivation
            logger.info("🕐 TIMING: Cache miss, falling through to V2 derivation")
        
        # Slow path: derive fresh data and update cache
        # Get all raw transactions
        db_start = time.time()
        raw_transactions = db.get_raw_transactions(
            account_number=account_number,
            underlying=underlying
        )
        db_time = time.time() - db_start
        logger.info(f"🕐 TIMING: Database query took {db_time:.2f}s, got {len(raw_transactions)} transactions")

        if not raw_transactions:
            total_time = time.time() - start_time
            logger.info(f"🕐 TIMING: Total request time (no data): {total_time:.2f}s")
            return {"chains": [], "total": 0}

        # Clear and rebuild position inventory and lots for accurate chain status
        inventory_start = time.time()
        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()  # V3: Also clear lots for reprocessing
        inventory_time = time.time() - inventory_start
        logger.info(f"🕐 TIMING: Position inventory and lots clear took {inventory_time:.2f}s")

        # Process through V2 system to get derived chains
        v2_start = time.time()
        chains_by_account = order_processor_v2.process_transactions(raw_transactions)
        v2_time = time.time() - v2_start
        logger.info(f"🕐 TIMING: V2 processing took {v2_time:.2f}s")

        # Flatten chains from all accounts
        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)

        # Update cache with fresh V2 data
        logger.info(f"About to update cache with {len(all_chains)} chains...")
        try:
            await update_chain_cache(all_chains)
            logger.info("Cache update completed")
        except Exception as cache_err:
            logger.warning(f"Could not update cache: {cache_err}")
            import traceback
            logger.error(f"Cache update traceback: {traceback.format_exc()}")
            # Continue without cache update - data will still be returned
        
        # Sort by opening date (newest first)
        all_chains.sort(key=lambda c: c.opening_date or date.min, reverse=True)
        
        # Apply pagination
        paginated_chains = all_chains[offset:offset + limit]
        
        # Format for frontend (similar to old system but with V2 data)
        format_start = time.time()
        logger.info(f"🕐 TIMING: Starting formatting of {len(paginated_chains)} chains")

        # Pre-fetch live position data once for all chains to improve performance
        live_positions_cache = {}
        api_fetch_start = time.time()
        try:
            client = TastytradeClient()
            if client.authenticate():
                # Get unique account numbers from chains
                unique_accounts = set()
                for chain in paginated_chains:
                    if chain.status == 'OPEN':  # Only need for open chains
                        unique_accounts.add(chain.account_number)

                # Fetch positions for all accounts in parallel for better performance
                if unique_accounts:
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    def fetch_positions_for_account(acct):
                        try:
                            data = client.get_positions(account_number=acct)
                            return acct, data.get(acct, [])
                        except Exception as e:
                            logger.warning(f"Could not fetch positions for account {acct}: {e}")
                            return acct, []

                    with ThreadPoolExecutor(max_workers=min(5, len(unique_accounts))) as executor:
                        futures = {executor.submit(fetch_positions_for_account, acct): acct
                                   for acct in unique_accounts}
                        for future in as_completed(futures):
                            acct, positions = future.result()
                            live_positions_cache[acct] = positions

                api_fetch_time = time.time() - api_fetch_start
                logger.info(f"🕐 TIMING: Pre-fetched positions for {len(unique_accounts)} accounts in parallel in {api_fetch_time:.2f}s")
            else:
                logger.warning("Could not authenticate for live position data - using cached data")
                api_fetch_time = time.time() - api_fetch_start
        except Exception as e:
            logger.warning(f"Could not pre-fetch live positions: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            api_fetch_time = time.time() - api_fetch_start

        formatted_chains = []
        for chain in paginated_chains:
            # Calculate totals - including ALL orders in the chain
            # This is the running cost basis across opening, rolls, and closing orders
            total_credit = 0.0
            total_debit = 0.0
            total_quantity = 0

            for order in chain.orders:
                for position in order.transactions:  # Using Transaction object
                    quantity = abs(position.quantity)

                    # Include all transactions (opening and closing)
                    if position.price > 0 and quantity > 0:
                        # Calculate amount (options are always 100x multiplier)
                        amount = position.price * quantity * 100

                        # Determine if transaction is a buy or sell
                        action = str(position.action)
                        if position.is_buy or 'BUY' in action:
                            total_debit += amount
                        elif position.is_sell or 'SELL' in action:
                            total_credit += amount

                    total_quantity += quantity
            
            # Calculate realized P&L from closed positions
            # Note: Transaction objects don't have separate opening/closing prices
            # The P&L will be calculated at the order level instead, which handles this correctly
            realized_pnl = 0.0
            unrealized_pnl = 0.0
            
            # Calculate cost basis per contract/share (total amount paid/received for opening transactions)
            # Sign matters: negative = money spent (long), positive = money received (short)
            # For long positions: cost_basis = -(total_debit - total_credit), i.e., negative cost
            # For short positions: cost_basis = (total_credit - total_debit), i.e., positive cost
            cost_basis_total = total_credit - total_debit  # Preserve sign: negative for long, positive for short

            # Calculate the total quantity of opening transactions for per-unit calculation
            # For multi-leg spreads, all legs have the same quantity, so use the first leg's quantity
            # (don't sum all legs, which would count each leg separately)
            opening_quantity_total = 0
            for order in chain.orders:
                for position in order.transactions:  # Using Transaction object
                    if position.is_opening:  # Is an opening transaction
                        opening_quantity_total = abs(position.quantity)  # Use first opening quantity, don't sum
                        break
                if opening_quantity_total > 0:
                    break

            # Calculate weighted average cost basis per unit (preserving sign)
            # Also calculate per-share basis (divide by 100 for options, as prices are in cents)
            cost_basis_per_unit = 0.0
            cost_basis_per_share = 0.0
            pnl_per_share = 0.0
            if opening_quantity_total > 0:
                cost_basis_per_unit = cost_basis_total / opening_quantity_total
                cost_basis_per_share = cost_basis_per_unit / 100  # Convert to per-share
                # For closed chains, also calculate P&L per share (realized_pnl is in dollars, convert to per-share)
                pnl_per_share = realized_pnl / opening_quantity_total / 100  # Divide by contracts then by 100

            # Debug logging
            logger.debug(f"Chain {chain.chain_id} ({chain.underlying}): debit={total_debit:.2f}, credit={total_credit:.2f}, cost_basis_total={cost_basis_total:.2f}, opening_qty={opening_quantity_total}, per_unit={cost_basis_per_unit:.2f}")

            # Use cached strategy from chain object (already detected in update_chain_cache)
            # Avoid duplicate strategy detection which is expensive
            detected_strategy = getattr(chain, 'strategy_type', None)
            if not detected_strategy:
                # Fallback: only detect if not cached (shouldn't happen with cache)
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
                'cost_basis_total': cost_basis_total,
                'cost_basis_per_unit': cost_basis_per_unit,
                'cost_basis_per_share': cost_basis_per_share,
                'pnl_per_share': pnl_per_share,
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
            # For open chains, the total P&L includes:
            # 1. Realized P&L from closed positions (already calculated above from transaction analysis)
            # 2. For still-open positions, we only show the premium collected/paid (credit/debit from opening orders)
            #
            # Note: We cannot reliably match live API positions to chains when multiple chains have the same underlying
            # So we use the order-based calculation which correctly reflects the premiums and any realized gains/losses
            order_pnl_total = sum(order['total_pnl'] for order in formatted_chain['orders'])

            if formatted_chain['status'] == 'CLOSED':
                # For closed chains, all P&L is realized
                formatted_chain['total_pnl'] = order_pnl_total
                formatted_chain['realized_pnl'] = order_pnl_total
                formatted_chain['unrealized_pnl'] = 0.0
            else:
                # For open chains, show the order P&L as total (which includes opening credits and any closing transactions)
                # This avoids the bug where all SPY chains would sum up all SPY positions
                formatted_chain['total_pnl'] = order_pnl_total
                # Keep the realized_pnl that was calculated from transaction analysis above

            # Calculate net liquidity for OPEN chains (current market value of open positions)
            net_liquidity = 0.0
            if formatted_chain['status'] == 'OPEN':
                try:
                    # Collect all unique symbols from this chain's transactions
                    chain_symbols = set()
                    for order in chain.orders:
                        for tx in order.transactions:
                            if tx.symbol:
                                chain_symbols.add(tx.symbol.strip())

                    # Get all open positions and filter by specific symbols in this chain
                    positions = db.get_open_positions()
                    if positions and chain_symbols:
                        for pos in positions:
                            pos_symbol = (pos.get('symbol') or '').strip()
                            if (pos_symbol in chain_symbols and
                                pos.get('account_number') == formatted_chain['account_number']):
                                net_liquidity += float(pos.get('market_value', 0))
                except Exception as e:
                    logger.warning(f"Could not calculate net liquidity for chain {formatted_chain['chain_id']}: {e}")
                    net_liquidity = 0.0

            formatted_chain['net_liquidity'] = net_liquidity

            # Calculate total commissions and fees from all transactions in the chain
            total_commission = 0.0
            total_regulatory_fees = 0.0
            total_clearing_fees = 0.0

            try:
                for order in chain.orders:
                    for tx in order.transactions:
                        total_commission += float(tx.commission) if tx.commission else 0.0
                        total_regulatory_fees += float(tx.regulatory_fees) if tx.regulatory_fees else 0.0
                        total_clearing_fees += float(tx.clearing_fees) if tx.clearing_fees else 0.0
            except Exception as e:
                logger.warning(f"Could not calculate fees for chain {formatted_chain['chain_id']}: {e}")

            formatted_chain['total_commission'] = total_commission
            formatted_chain['total_regulatory_fees'] = total_regulatory_fees
            formatted_chain['total_clearing_fees'] = total_clearing_fees
            formatted_chain['total_fees'] = total_commission + total_regulatory_fees + total_clearing_fees

            formatted_chains.append(formatted_chain)
        
        format_time = time.time() - format_start
        total_time = time.time() - start_time

        logger.info(f"🕐 TIMING: Chain formatting took {format_time:.2f}s for {len(formatted_chains)} chains")
        logger.info(f"🕐 TIMING: Total request time: {total_time:.2f}s")

        return {
            "chains": formatted_chains,
            "total": len(formatted_chains),
            "cached": False,  # Indicate this was freshly derived
            "timing": {
                "total_time": round(total_time, 2),
                "db_time": round(db_time, 2),
                "v2_time": round(v2_time, 2),
                "format_time": round(format_time, 2)
            }
        }
        
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


@app.get("/api/quotes")
async def get_market_quotes(symbols: str, refresh: bool = False, request: Request = None):
    """Get current market quotes for symbols (cached or fresh)"""
    try:
        # Parse comma-separated symbols
        symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
        logger.info(f"GET /api/quotes requested for symbols: {symbol_list}")

        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")

        # If not forcing refresh, try cached quotes first (no auth needed)
        if not refresh:
            logger.info(f"Attempting to get cached quotes for: {symbol_list}")
            cached_quotes = db.get_cached_quotes(symbol_list)
            logger.info(f"Cache lookup returned {len(cached_quotes) if cached_quotes else 0} quotes")
            if cached_quotes:
                logger.info(f"Returning {len(cached_quotes)} cached quotes for: {list(cached_quotes.keys())}")
                # Convert to camelCase for frontend compatibility
                for symbol, quote_data in cached_quotes.items():
                    if 'mark' in quote_data and quote_data['mark'] is not None:
                        quote_data['price'] = quote_data['mark']
                    if 'change_percent' in quote_data:
                        quote_data['changePercent'] = quote_data['change_percent']
                    if 'iv_percentile' in quote_data:
                        quote_data['ivPercentile'] = quote_data['iv_percentile']
                logger.info(f"Returning {len(cached_quotes)} quotes with camelCase conversion")
                return cached_quotes
            # If cache miss and no refresh requested, still try fresh quotes
            logger.info(f"Cache miss for symbols: {symbol_list}, attempting fresh quotes")

        # Get session credentials from request for fresh quotes
        session_id = None
        username = None
        password = None

        if request:
            session_id = request.cookies.get("session_id")
            if session_id:
                username, password = auth_manager.get_session_credentials(session_id)

        # Initialize Tastytrade client with session credentials if available, otherwise use env vars
        if username and password:
            client = TastytradeClient(username=username, password=password)
        else:
            client = TastytradeClient()

        # Authenticate with Tastytrade
        if not client.authenticate():
            # If we can't authenticate for fresh quotes, return cached as fallback
            cached_quotes = db.get_cached_quotes(symbol_list)
            if cached_quotes:
                logger.info(f"Auth failed, returning fallback cached quotes: {list(cached_quotes.keys())}")
                for symbol, quote_data in cached_quotes.items():
                    if 'mark' in quote_data and quote_data['mark'] is not None:
                        quote_data['price'] = quote_data['mark']
                    if 'change_percent' in quote_data:
                        quote_data['changePercent'] = quote_data['change_percent']
                    if 'iv_percentile' in quote_data:
                        quote_data['ivPercentile'] = quote_data['iv_percentile']
                return cached_quotes
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

        if account_number:
            positions = [p for p in positions if p.get('account_number') == account_number]

        # Get all open chains for enrichment matching
        open_chains = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT
                        chain_id, underlying, account_number, strategy_type, chain_status
                    FROM order_chains
                    WHERE chain_status = 'OPEN'
                """
                params = []
                if account_number:
                    query += " AND account_number = ?"
                    params.append(account_number)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    open_chains.append(dict(row))
        except Exception as e:
            logger.warning(f"Could not fetch chains for cached positions enrichment: {e}")
            open_chains = []

        # Enrich positions with chain metadata for grouping
        # Pass database connection for precise symbol-based matching
        with db.get_connection() as conn:
            enricher = PositionEnricher(db_connection=conn)
            enriched_positions, unmatched = enricher.enrich_positions(positions, open_chains)

        # Get the last sync timestamp for freshness metadata
        last_sync = db.get_last_sync_timestamp()

        # Calculate data age
        data_age_minutes = None
        if last_sync:
            data_age_minutes = (datetime.now() - last_sync).total_seconds() / 60

        # Group positions by account (matching the expected frontend format)
        positions_by_account = {}
        for position in enriched_positions:
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


async def background_incremental_sync():
    """
    Background task to perform incremental sync when unmatched positions are detected.
    This keeps position enrichment data fresh without blocking the user.
    """
    try:
        logger.info("Starting background incremental sync...")

        # Get last sync timestamp to determine date range
        last_sync = db.get_last_sync_timestamp()

        if last_sync:
            # Calculate days back from last sync + 1 day buffer
            days_back = (datetime.now() - last_sync).days + 1
            days_back = max(days_back, 1)  # Minimum 1 day
            days_back = min(days_back, 90)  # Maximum 90 days for safety
            logger.info(f"Background sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
        else:
            # No previous sync, fetch last 30 days
            days_back = 30
            logger.info(f"Background sync: no previous sync, fetching {days_back} days")

        # Try to get authenticated client from auth manager
        try:
            # Get first available session to use for sync
            session_credentials = auth_manager.get_any_session_credentials()
            if not session_credentials:
                logger.warning("Background sync: no authenticated sessions available, skipping sync")
                return

            username, password = session_credentials
            tastytrade = TastytradeClient(username=username, password=password)

            if not tastytrade.authenticate():
                logger.error("Background sync: failed to authenticate")
                return

        except Exception as e:
            logger.warning(f"Background sync: could not get authenticated client: {e}")
            return

        try:
            # Fetch transactions from all accounts
            transactions = tastytrade.get_transactions(days_back=days_back)
            logger.info(f"Background sync: fetched {len(transactions)} transactions")

            # Save raw transactions
            raw_saved = db.save_raw_transactions(transactions)
            logger.info(f"Background sync: saved {raw_saved} raw transactions")

            # Fetch and save current positions
            all_positions = tastytrade.get_positions()
            total_positions = 0

            for account_number, positions in all_positions.items():
                if positions:
                    positions_with_dates = calculate_position_opening_dates(positions, account_number)
                    success = db.save_positions(positions_with_dates, account_number)
                    if success:
                        total_positions += len(positions)

            logger.info(f"Background sync: saved {total_positions} positions")

            # Reprocess chains to update order processing
            raw_transactions = db.get_raw_transactions()
            chains_by_account = order_processor_v2.process_transactions(raw_transactions)

            all_chains = []
            for account, chains in chains_by_account.items():
                for chain in chains:
                    all_chains.append(chain)

            if all_chains:
                logger.info(f"Background sync: reprocessed {len(all_chains)} chains")

            # Update last sync timestamp
            db.set_last_sync_timestamp(datetime.now())
            logger.info("Background sync: completed successfully")

        except Exception as e:
            logger.error(f"Background sync: error during processing: {e}")
            return

    except Exception as e:
        logger.error(f"Background incremental sync failed: {e}")


@app.get("/api/positions")
async def get_positions(account_number: Optional[str] = None):
    """Get current open positions with chain enrichment for intelligent grouping"""
    try:
        # Get live positions from database
        live_positions = db.get_open_positions()
        logger.info(f"/api/positions: Fetched {len(live_positions)} total live positions from database")

        if account_number:
            live_positions = [p for p in live_positions if p.get('account_number') == account_number]
            logger.info(f"/api/positions: Filtered to {len(live_positions)} positions for account {account_number}")

        # Get all open chains directly from database for enrichment matching
        # This bypasses order_manager which may apply filters or caching
        import json
        open_chains = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT
                        chain_id, underlying, account_number, strategy_type, chain_status
                    FROM order_chains
                    WHERE chain_status = 'OPEN'
                """
                params = []
                if account_number:
                    query += " AND account_number = ?"
                    params.append(account_number)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    open_chains.append(dict(row))
                logger.info(f"/api/positions: Fetched {len(open_chains)} open chains for enrichment")
        except Exception as e:
            logger.warning(f"Could not fetch chains for enrichment: {e}. Continuing without enrichment.")
            open_chains = []

        # Enrich positions with chain metadata
        # Pass database connection for precise symbol-based matching
        with db.get_connection() as conn:
            enricher = PositionEnricher(db_connection=conn)
            enriched_positions, unmatched_positions = enricher.enrich_positions(live_positions, open_chains)

        # Log enrichment results
        enriched_count = sum(1 for p in enriched_positions if 'chain_id' in p)
        logger.info(
            f"/api/positions: Enrichment result: {enriched_count}/{len(enriched_positions)} positions have chain_id. "
            f"{len(unmatched_positions)} positions unmatched."
        )

        # If positions are unmatched, trigger background sync
        # NOTE: Commenting out to improve responsiveness - background sync will happen on chains page
        # if unmatched_positions:
        #     logger.info(f"Found {len(unmatched_positions)} unmatched positions: {unmatched_positions}")
        #     logger.info("Triggering background incremental sync to update chain data")
        #     asyncio.create_task(background_incremental_sync())

        # Group positions by account and add opening dates (matching the expected frontend format)
        positions_by_account = {}
        for position in enriched_positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)

        # Calculate opening dates for each account's positions
        for account, positions in positions_by_account.items():
            positions_by_account[account] = calculate_position_opening_dates(positions, account)

        logger.info(f"/api/positions: Returning positions grouped by {len(positions_by_account)} accounts")
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
        
        # Calculate realized P&L from chains (existing logic)
        chains_total_pnl = sum(c['total_pnl'] for c in processed_chains)
        chains_realized_pnl = sum(c['realized_pnl'] for c in processed_chains)

        # Get unrealized P&L from current positions
        unrealized_pnl = 0
        position_data_source = "none"
        try:
            # Try to get cached positions first (faster, includes live market values)
            positions = db.get_open_positions()
            if positions:
                # Filter by account if specified
                if account_number:
                    positions = [p for p in positions if p.get('account_number') == account_number]

                # Calculate unrealized P&L from positions
                unrealized_pnl = sum(float(p.get('unrealized_pnl', 0)) for p in positions)
                position_data_source = "database"
                logger.info(f"Dashboard: Using database positions data, unrealized P&L: ${unrealized_pnl:.2f}")
            else:
                logger.warning("Dashboard: No position data available")
        except Exception as e:
            logger.warning(f"Dashboard: Could not get position data for unrealized P&L: {e}")

        # Calculate combined totals
        total_pnl = chains_realized_pnl + unrealized_pnl
        realized_pnl = chains_realized_pnl

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
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "chains_only_pnl": chains_total_pnl,  # Original chains-only calculation for comparison
                "position_based_total": unrealized_pnl != 0,  # Flag indicating enhanced calculation
                "data_source": position_data_source,
                "win_rate": win_rate
            },
            "order_summary": order_stats,
            "strategy_breakdown": strategy_stats,
            "recent_trades": []  # Could implement this later if needed
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync-positions-only")
async def sync_positions_only(request: Request):
    """Fast sync that only updates current positions without reprocessing orders"""
    try:
        # Check authentication
        try:
            session_id = request.cookies.get("session_id")
            if not session_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            username, password = auth_manager.get_session_credentials(session_id)
            if not username or not password:
                raise HTTPException(status_code=401, detail="Session invalid or expired")
        except HTTPException:
            raise

        logger.info(f"Starting positions-only sync (fast mode) for user: {username}...")

        # Initialize client with credentials from session
        tastytrade = TastytradeClient(username=username, password=password)

        # Authenticate
        if not tastytrade.authenticate():
            logger.error(f"Failed to authenticate with Tastytrade for user: {username}")
            raise HTTPException(status_code=401, detail="Failed to authenticate with Tastytrade")
        
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
        
        # Fetch and save account balances
        logger.info("Fetching account balances...")
        balances = tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                db.save_account_balance(balance)
        
        logger.info(f"Fast sync completed: {total_positions} positions updated")
        
        return {
            "message": f"Fast sync completed: {total_positions} positions updated",
            "positions_updated": total_positions,
            "mode": "positions_only"
        }
        
    except Exception as e:
        logger.error(f"Error during fast sync: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
async def sync_unified(request: Request):
    """Unified sync endpoint with smart date range calculation"""
    try:
        from datetime import datetime, timedelta

        # Check authentication and get credentials from session
        try:
            session_id = request.cookies.get("session_id")
            if not session_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            username, password = auth_manager.get_session_credentials(session_id)
            if not username or not password:
                raise HTTPException(status_code=401, detail="Session invalid or expired")
        except HTTPException:
            raise

        logger.info(f"Sync requested by user: {username}")

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

        # Initialize client with credentials from session
        tastytrade = TastytradeClient(username=username, password=password)

        # Authenticate
        if not tastytrade.authenticate():
            logger.error(f"Failed to authenticate with Tastytrade for user: {username}")
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
        
        # Reprocess chains after sync - use incremental processing when possible
        # Skip reprocessing entirely if no new transactions were saved
        if raw_saved == 0:
            logger.info("No new transactions saved, skipping chain reprocessing")
            return {
                "message": f"Sync completed: no new transactions",
                "transactions_processed": 0,
                "positions_updated": total_positions,
                "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None
            }

        # Extract affected underlyings from the fetched transactions
        affected_underlyings = set()
        for txn in transactions:
            underlying = txn.get('underlying_symbol', '')
            if underlying:
                # Strip option suffix if present (e.g., "AAPL  240119C00150000" -> "AAPL")
                underlying = underlying.split()[0] if ' ' in underlying else underlying
                affected_underlyings.add(underlying)

        # Determine if we should do incremental or full reprocessing
        use_incremental = raw_saved < 50 and len(affected_underlyings) <= 10

        if use_incremental:
            logger.info(f"Incremental chain reprocessing for {len(affected_underlyings)} underlyings: {affected_underlyings}")
        else:
            logger.info(f"Full chain reprocessing (raw_saved={raw_saved}, underlyings={len(affected_underlyings)})")
            affected_underlyings = None  # Signal full reprocessing

        try:
            # Clear position inventory and lots (needed for V2 processing)
            position_manager.clear_all_positions()
            lot_manager.clear_all_lots()
            logger.info("Cleared position inventory and lots for reprocessing")

            if use_incremental and affected_underlyings:
                # Incremental: only process affected underlyings
                all_chains = []
                for underlying in affected_underlyings:
                    underlying_txs = db.get_raw_transactions(underlying=underlying)
                    if underlying_txs:
                        chains_by_account = order_processor_v2.process_transactions(underlying_txs)
                        for account, chains in chains_by_account.items():
                            all_chains.extend(chains)
                logger.info(f"Incremental reprocessing created {len(all_chains)} chains for affected underlyings")
            else:
                # Full reprocessing
                raw_transactions = db.get_raw_transactions()
                chains_by_account = order_processor_v2.process_transactions(raw_transactions)
                all_chains = []
                for account, chains in chains_by_account.items():
                    all_chains.extend(chains)
                logger.info(f"Full reprocessing created {len(all_chains)} chains")

            if all_chains:
                logger.info("Running strategy detection on chains...")
                try:
                    await update_chain_cache(all_chains, affected_underlyings)
                    logger.info("Strategy detection and cache update completed")
                except Exception as e:
                    logger.error(f"Error during strategy detection after sync: {str(e)}", exc_info=True)
            else:
                logger.warning("No chains created during reprocessing")
        except Exception as e:
            logger.error(f"Error during chain reprocessing: {str(e)}")
        
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
async def migrate_realized_pnl(request: Request):
    """One-time migration to populate realized_pnl for existing chains"""
    try:
        # Check authentication
        try:
            session_id = request.cookies.get("session_id")
            if not session_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            username, password = auth_manager.get_session_credentials(session_id)
            if not username or not password:
                raise HTTPException(status_code=401, detail="Session invalid or expired")
        except HTTPException:
            raise

        logger.info(f"Starting realized P&L migration for user: {username}...")
        
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
async def initial_sync(request: Request):
    """Complete initial sync - clears database and rebuilds from scratch"""
    try:
        # Check authentication and get credentials from session
        try:
            session_id = request.cookies.get("session_id")
            if not session_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            username, password = auth_manager.get_session_credentials(session_id)
            if not username or not password:
                raise HTTPException(status_code=401, detail="Session invalid or expired")
        except HTTPException:
            raise

        logger.info(f"Starting INITIAL SYNC for user: {username} - this will rebuild the entire database")

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

        # Initialize client with credentials from session
        tastytrade = TastytradeClient(username=username, password=password)

        # Authenticate
        if not tastytrade.authenticate():
            logger.error(f"Failed to authenticate with Tastytrade for user: {username}")
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
async def reprocess_chains(request: Request):
    """Reprocess orders and chains from existing raw transactions using V2 system"""
    try:
        # Check authentication
        try:
            session_id = request.cookies.get("session_id")
            if not session_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            username, password = auth_manager.get_session_credentials(session_id)
            if not username or not password:
                raise HTTPException(status_code=401, detail="Session invalid or expired")
        except HTTPException:
            raise

        logger.info(f"Starting V2 chain reprocessing from database for user: {username}")

        # Get all raw transactions from database
        raw_transactions = db.get_raw_transactions()
        logger.info(f"Loaded {len(raw_transactions)} raw transactions from database")

        # Clear existing position inventory and lots before reprocessing
        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        logger.info("Cleared position inventory and lots for reprocessing")

        # Use V2 processor to create chains
        chains_by_account = order_processor_v2.process_transactions(raw_transactions)
        
        # Flatten chains from all accounts
        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)
        
        # Update cache with fresh V2 data
        logger.info(f"About to update cache with {len(all_chains)} chains...")
        await update_chain_cache(all_chains)
        logger.info("Cache update completed")
        
        # Debug: Check what was actually inserted for CSX
        debug_info = {}
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT strategy_type FROM order_chains WHERE chain_id = 'CSX_OPENING_20250729_39786951'")
                result = cursor.fetchone()
                debug_info["csx_strategy_after_insert"] = result[0] if result else "NOT_FOUND"
        except Exception as e:
            debug_info["debug_error"] = str(e)
        
        return {
            "message": "Reprocessing completed successfully",
            "orders_processed": len(raw_transactions),
            "orders_saved": len(raw_transactions),
            "chains_created": len(all_chains),
            "chains_saved": len(all_chains),
            "debug": debug_info
        }
        
    except Exception as e:
        logger.error(f"Error during reprocessing: {str(e)}")
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


@app.get("/api/reports/strategies")
async def get_available_strategies(request: Request):
    """Get list of strategies that have been used in closed trades"""
    try:
        await require_auth(request)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT strategy_type
                FROM order_chains
                WHERE chain_status = 'CLOSED' AND strategy_type IS NOT NULL
                ORDER BY strategy_type
            """)
            strategies = [row['strategy_type'] for row in cursor.fetchall()]

        return {"strategies": strategies}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching strategies: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def calculate_max_risk_reward(cursor, chain_id: str, strategy_type: str) -> tuple:
    """
    Calculate max risk and max reward for a chain based on its opening positions.
    Returns (max_risk, max_reward) as positive numbers, or (None, None) if cannot calculate.
    """
    # Get the opening order for this chain (first order)
    cursor.execute("""
        SELECT ocm.order_id
        FROM order_chain_members ocm
        JOIN orders o ON o.order_id = ocm.order_id
        WHERE ocm.chain_id = ?
        ORDER BY o.order_date ASC
        LIMIT 1
    """, (chain_id,))
    row = cursor.fetchone()
    if not row:
        return None, None

    opening_order_id = row['order_id']

    # Get positions for the opening order
    cursor.execute("""
        SELECT symbol, instrument_type, option_type, strike, quantity,
               opening_price, opening_action
        FROM order_positions
        WHERE order_id = ?
    """, (opening_order_id,))
    positions = cursor.fetchall()

    if not positions:
        return None, None

    # Separate by instrument type
    options = [p for p in positions if 'OPTION' in (p['instrument_type'] or '').upper()]
    stocks = [p for p in positions if 'EQUITY' in (p['instrument_type'] or '').upper() and 'OPTION' not in (p['instrument_type'] or '').upper()]

    if not options and not stocks:
        return None, None

    # Calculate based on strategy type
    strategy = (strategy_type or '').lower()

    try:
        if 'bull put spread' in strategy or 'bear call spread' in strategy:
            # Credit spread: max risk = width - premium, max reward = premium
            if len(options) >= 2:
                strikes = sorted([p['strike'] for p in options])
                width = (strikes[-1] - strikes[0]) * 100
                # Sum premiums (positive for sells, negative for buys)
                premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                    (1 if 'SELL' in (p['opening_action'] or '').upper() else -1)
                    for p in options
                )
                max_risk = abs(width * abs(options[0]['quantity']) - premium)
                max_reward = abs(premium)
                return max_risk, max_reward

        elif 'bull call spread' in strategy or 'bear put spread' in strategy:
            # Debit spread: max risk = premium paid, max reward = width - premium
            if len(options) >= 2:
                strikes = sorted([p['strike'] for p in options])
                width = (strikes[-1] - strikes[0]) * 100
                # Sum premiums (negative for buys, positive for sells)
                premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                    (-1 if 'BUY' in (p['opening_action'] or '').upper() else 1)
                    for p in options
                )
                max_risk = abs(premium)
                max_reward = abs(width * abs(options[0]['quantity']) + premium)
                return max_risk, max_reward

        elif 'iron condor' in strategy:
            # Iron condor: max risk = wider wing width - total premium
            if len(options) >= 4:
                calls = [p for p in options if p['option_type'] == 'Call']
                puts = [p for p in options if p['option_type'] == 'Put']
                if len(calls) >= 2 and len(puts) >= 2:
                    call_strikes = sorted([p['strike'] for p in calls])
                    put_strikes = sorted([p['strike'] for p in puts])
                    call_width = (call_strikes[-1] - call_strikes[0]) * 100
                    put_width = (put_strikes[-1] - put_strikes[0]) * 100
                    wider_width = max(call_width, put_width)
                    premium = sum(
                        abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                        (1 if 'SELL' in (p['opening_action'] or '').upper() else -1)
                        for p in options
                    )
                    qty = abs(options[0]['quantity'])
                    max_risk = abs(wider_width * qty - premium)
                    max_reward = abs(premium)
                    return max_risk, max_reward

        elif 'covered call' in strategy:
            # Covered call: need stock cost and call premium
            if stocks and options:
                stock_cost = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) for p in stocks)
                call_premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100
                    for p in options if p['option_type'] == 'Call'
                )
                call_strike = options[0]['strike'] if options else 0
                stock_qty = abs(stocks[0]['quantity']) if stocks else 0
                max_risk = stock_cost - call_premium  # Stock goes to 0
                max_reward = (call_strike * stock_qty) - stock_cost + call_premium  # Called away at strike
                return abs(max_risk), abs(max_reward) if max_reward > 0 else 0

        elif 'cash secured put' in strategy or 'short put' in strategy or 'naked put' in strategy:
            # CSP: max risk = strike * 100 - premium, max reward = premium
            if options:
                put = next((p for p in options if p['option_type'] == 'Put'), options[0])
                premium = abs(put['opening_price'] or 0) * abs(put['quantity']) * 100
                max_risk = (put['strike'] * 100 * abs(put['quantity'])) - premium
                max_reward = premium
                return abs(max_risk), abs(max_reward)

        elif 'long call' in strategy or 'long put' in strategy:
            # Long options: max risk = premium paid
            if options:
                premium = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 for p in options)
                max_risk = premium
                max_reward = None  # Unlimited for calls, large for puts
                return max_risk, max_reward

        elif 'short call' in strategy or 'naked call' in strategy:
            # Naked call: unlimited risk
            if options:
                premium = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 for p in options)
                max_risk = None  # Unlimited
                max_reward = premium
                return max_risk, max_reward

    except Exception as e:
        logger.warning(f"Error calculating risk/reward for chain {chain_id}: {e}")
        return None, None

    return None, None


@app.get("/api/reports/performance")
async def get_performance_report(
    request: Request,
    account_number: Optional[str] = None,
    days: str = "90",
    strategies: str = ""
):
    """Get performance report data for closed trades"""
    try:
        await require_auth(request)

        # Parse parameters
        strategy_list = [s.strip() for s in strategies.split(',') if s.strip()] if strategies else []

        # Build query for closed chains
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Base query for closed chains with closing date
            query = """
                SELECT
                    chain_id,
                    strategy_type,
                    total_pnl,
                    account_number,
                    closing_date
                FROM order_chains
                WHERE chain_status = 'CLOSED'
            """
            params = []

            # Account filter
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)

            # Time period filter (based on closing date)
            if days != 'all':
                try:
                    days_int = int(days)
                    cutoff_date = (datetime.now() - timedelta(days=days_int)).strftime('%Y-%m-%d')
                    query += " AND closing_date >= ?"
                    params.append(cutoff_date)
                except ValueError:
                    pass

            cursor.execute(query, params)
            chains = cursor.fetchall()

            # Calculate max risk/reward for each chain
            chain_risk_reward = {}
            for chain in chains:
                max_risk, max_reward = calculate_max_risk_reward(
                    cursor, chain['chain_id'], chain['strategy_type']
                )
                chain_risk_reward[chain['chain_id']] = (max_risk, max_reward)

        # Filter by strategies if specified
        if strategy_list:
            chains = [c for c in chains if c['strategy_type'] in strategy_list]

        # Calculate summary metrics
        total_pnl = 0.0
        wins = 0
        losses = 0
        win_pnls = []
        loss_pnls = []
        max_risks = []
        max_rewards = []

        # Strategy breakdown
        strategy_stats = {}

        for chain in chains:
            pnl = chain['total_pnl'] or 0.0
            strategy = chain['strategy_type'] or 'Unknown'
            chain_id = chain['chain_id']

            # Get pre-calculated risk/reward
            max_risk, max_reward = chain_risk_reward.get(chain_id, (None, None))

            total_pnl += pnl

            if max_risk is not None:
                max_risks.append(max_risk)
            if max_reward is not None:
                max_rewards.append(max_reward)

            if pnl >= 0:
                wins += 1
                win_pnls.append(pnl)
            else:
                losses += 1
                loss_pnls.append(pnl)

            # Initialize strategy stats
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {
                    'strategy': strategy,
                    'totalPnl': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'winPnls': [],
                    'lossPnls': [],
                    'maxRisks': [],
                    'maxRewards': []
                }

            strategy_stats[strategy]['totalPnl'] += pnl
            if max_risk is not None:
                strategy_stats[strategy]['maxRisks'].append(max_risk)
            if max_reward is not None:
                strategy_stats[strategy]['maxRewards'].append(max_reward)

            if pnl >= 0:
                strategy_stats[strategy]['wins'] += 1
                strategy_stats[strategy]['winPnls'].append(pnl)
            else:
                strategy_stats[strategy]['losses'] += 1
                strategy_stats[strategy]['lossPnls'].append(pnl)

        total_trades = len(chains)

        # Build summary
        summary = {
            'totalPnl': total_pnl,
            'totalTrades': total_trades,
            'wins': wins,
            'losses': losses,
            'winRate': (wins / total_trades * 100) if total_trades > 0 else 0,
            'avgPnl': (total_pnl / total_trades) if total_trades > 0 else 0,
            'avgWin': (sum(win_pnls) / len(win_pnls)) if win_pnls else 0,
            'avgLoss': (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0,
            'largestWin': max(win_pnls) if win_pnls else 0,
            'largestLoss': min(loss_pnls) if loss_pnls else 0,
            'avgMaxRisk': (sum(max_risks) / len(max_risks)) if max_risks else 0,
            'avgMaxReward': (sum(max_rewards) / len(max_rewards)) if max_rewards else 0
        }

        # Build strategy breakdown
        breakdown = []
        for strategy, stats in strategy_stats.items():
            total = stats['wins'] + stats['losses']
            breakdown.append({
                'strategy': strategy,
                'totalTrades': total,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'winRate': (stats['wins'] / total * 100) if total > 0 else 0,
                'totalPnl': stats['totalPnl'],
                'avgPnl': (stats['totalPnl'] / total) if total > 0 else 0,
                'avgWin': (sum(stats['winPnls']) / len(stats['winPnls'])) if stats['winPnls'] else 0,
                'avgLoss': (sum(stats['lossPnls']) / len(stats['lossPnls'])) if stats['lossPnls'] else 0,
                'largestWin': max(stats['winPnls']) if stats['winPnls'] else 0,
                'largestLoss': min(stats['lossPnls']) if stats['lossPnls'] else 0,
                'avgMaxRisk': (sum(stats['maxRisks']) / len(stats['maxRisks'])) if stats['maxRisks'] else 0,
                'avgMaxReward': (sum(stats['maxRewards']) / len(stats['maxRewards'])) if stats['maxRewards'] else 0
            })

        return {
            'summary': summary,
            'breakdown': breakdown
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating performance report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/debug/strategy/{chain_id}")
async def debug_strategy(chain_id: str):
    """Debug strategy detection for a specific chain"""
    # Get the chain from V2 processor (same as cache update process)
    raw_transactions = db.get_raw_transactions()
    chains_by_account = order_processor_v2.process_transactions(raw_transactions)
    
    # Find the specific chain
    target_chain = None
    for account_chains in chains_by_account.values():
        for chain in account_chains:
            if chain.chain_id == chain_id:
                target_chain = chain
                break
    
    if not target_chain:
        return {"error": f"Chain {chain_id} not found"}
    
    # Debug info
    debug_info = {
        "chain_id": chain_id,
        "underlying": target_chain.underlying,
        "orders": len(target_chain.orders),
        "opening_orders": [],
        "debug_path": "fresh_v2_processing"
    }
    
    for order in target_chain.orders:
        if order.order_type.value == 'OPENING':
            order_info = {
                "order_id": order.order_id,
                "transactions": []
            }
            for tx in order.transactions:
                tx_info = {
                    "symbol": tx.symbol,
                    "action": tx.action,
                    "quantity": tx.quantity,
                    "option_type": tx.option_type,
                    "strike": tx.strike,
                    "has_option_type": tx.option_type is not None,
                    "underlying_symbol": tx.underlying_symbol
                }
                order_info["transactions"].append(tx_info)
            debug_info["opening_orders"].append(order_info)
    
    # Try strategy detection
    try:
        detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
        debug_info["detected_strategy"] = detected_strategy
    except Exception as e:
        debug_info["strategy_error"] = str(e)
    
    return debug_info


@app.get("/api/debug/cache-path/{chain_id}")
async def debug_cache_path(chain_id: str):
    """Debug strategy detection using the EXACT same code path as cache update"""
    # This mimics the exact code path used in cache updates
    raw_transactions = db.get_raw_transactions()
    chains_by_account = order_processor_v2.process_transactions(raw_transactions)
    
    # Flatten chains from all accounts (same as cache update)
    all_chains = []
    for account, chains in chains_by_account.items():
        for chain in chains:
            all_chains.append(chain)
    
    # Find the target chain
    target_chain = None
    for chain in all_chains:
        if chain.chain_id == chain_id:
            target_chain = chain
            break
    
    if not target_chain:
        return {"error": f"Chain {chain_id} not found"}
    
    # Now run the EXACT same strategy detection logic as in update_chain_cache
    try:
        # This is the exact code from update_chain_cache
        detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
        if detected_strategy is None:
            detected_strategy = "Unknown"
    except Exception as e:
        detected_strategy = "Unknown"
        
    return {
        "chain_id": chain_id,
        "underlying": target_chain.underlying,
        "strategy_from_cache_path": detected_strategy,
        "opening_orders": len([o for o in target_chain.orders if o.order_type.value == 'OPENING']),
        "total_orders": len(target_chain.orders)
    }


@app.get("/api/debug/cache-update/{chain_id}")
async def debug_cache_update(chain_id: str):
    """Debug the full cache update process for a specific chain"""
    try:
        # Step 1: Get raw transactions
        raw_transactions = db.get_raw_transactions()
        
        # Step 2: Process transactions
        chains_by_account = order_processor_v2.process_transactions(raw_transactions)
        
        # Step 3: Find target chain
        target_chain = None
        for account_chains in chains_by_account.values():
            for chain in account_chains:
                if chain.chain_id == chain_id:
                    target_chain = chain
                    break
        
        if not target_chain:
            return {"error": f"Chain {chain_id} not found"}
        
        # Step 4: Strategy detection (exact same logic as cache update)
        try:
            detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
            if detected_strategy is None:
                detected_strategy = "Unknown"
        except Exception as e:
            detected_strategy = "Unknown"
            
        # Step 5: Simulate database insert without actually inserting
        insert_params = {
            "chain_id": target_chain.chain_id,
            "underlying": target_chain.underlying,
            "account_number": target_chain.account_number,
            "opening_order_id": target_chain.orders[0].order_id if target_chain.orders else None,
            "strategy_type": detected_strategy,
            "opening_date": target_chain.opening_date,
            "closing_date": target_chain.closing_date,
            "chain_status": target_chain.status,
            "order_count": len(target_chain.orders)
        }
        
        # Step 6: Check what's currently in database
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT strategy_type FROM order_chains WHERE chain_id = ?", (chain_id,))
            current_db_result = cursor.fetchone()
            current_db_strategy = current_db_result[0] if current_db_result else "NOT_FOUND"
        
        return {
            "chain_id": chain_id,
            "detected_strategy": detected_strategy,
            "would_insert": insert_params,
            "current_in_db": current_db_strategy,
            "opening_order_transactions": len(target_chain.orders[0].transactions) if target_chain.orders else 0
        }
        
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


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

        # Get session credentials from cookies
        session_id = websocket.cookies.get("session_id")
        if not session_id:
            logger.error("WebSocket connection rejected: No session")
            await websocket.send_json({"error": "Not authenticated - please login first"})
            await websocket.close()
            return

        username, password = auth_manager.get_session_credentials(session_id)
        if not username or not password:
            logger.error("WebSocket connection rejected: Invalid session")
            await websocket.send_json({"error": "Session invalid or expired"})
            await websocket.close()
            return

        # Initialize Tastytrade client with session credentials
        client = TastytradeClient(username=username, password=password)

        # Authenticate with Tastytrade
        if not client.authenticate():
            logger.error(f"Tastytrade authentication failed for WebSocket user: {username}")
            await websocket.send_json({"error": "Failed to authenticate with Tastytrade"})
            await websocket.close()
            return

        logger.info(f"WebSocket client connected and Tastytrade authenticated for user: {username}")
        
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
                            
                            # Send initial quotes (force fresh to populate cache)
                            if subscribed_symbols:
                                client.clear_quote_cache()  # Clear on first subscription to get fresh data
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
                        # Don't clear cache - let the 30-second TTL work naturally
                        # This ensures we use cached quotes when available and only fetch fresh data when cache expires
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
    logger.info("Starting OptionEdge on http://localhost:8000")
    logger.info("From Windows, also try: http://127.0.0.1:8000")
    uvicorn.run(
        "app:app",  # Use string import to enable reload
        host="0.0.0.0",  # This ensures it binds to all interfaces
        port=8000,
        reload=True,
        log_level="info"
    )