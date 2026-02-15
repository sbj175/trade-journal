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
from src.models.order_models import OrderManager
from src.models.position_inventory import PositionInventoryManager
from src.models.order_processor import OrderProcessor
from src.models.strategy_detector import StrategyDetector
from src.models.pnl_calculator import PnLCalculator
from src.models.position_enricher import PositionEnricher
from src.models.lot_manager import LotManager
from src.utils.auth_manager import ConnectionManager

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

# System Components
position_manager = PositionInventoryManager(db)

# Lot-based position tracking
lot_manager = LotManager(db)

# Initialize processors with lot_manager
order_processor = OrderProcessor(db, position_manager, lot_manager)
strategy_detector = StrategyDetector(db)
pnl_calculator = PnLCalculator(db, position_manager, lot_manager)

# Initialize connection manager (shared app-level client)
connection_manager = ConnectionManager()


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


def enrich_and_save_positions(positions: List[Dict[str, Any]], account_number: str) -> bool:
    """Enrich positions with chain metadata and save to database.

    This runs at sync-time so chain_id and strategy_type are persisted,
    eliminating the need for runtime enrichment on every API call.
    """
    if not positions:
        return True

    # Calculate opening dates
    positions_with_dates = calculate_position_opening_dates(positions, account_number)

    # Get open chains for this account
    open_chains = []
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chain_id, underlying, account_number, strategy_type, chain_status
                FROM order_chains
                WHERE chain_status = 'OPEN' AND account_number = ?
            """, (account_number,))
            for row in cursor.fetchall():
                open_chains.append(dict(row))
    except Exception as e:
        logger.warning(f"Could not fetch chains for position enrichment: {e}")

    # Build symbol → chain lookup from order_chain_cache (the authoritative source)
    # order_positions table may be empty for newer chains; cache always has the data
    symbol_to_chain = {}
    if open_chains:
        try:
            import json as _json
            chain_ids = [c['chain_id'] for c in open_chains]
            chain_map = {c['chain_id']: c for c in open_chains}
            with db.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(chain_ids))
                cursor.execute(f"""
                    SELECT chain_id, order_data FROM order_chain_cache
                    WHERE chain_id IN ({placeholders})
                """, chain_ids)
                for row in cursor.fetchall():
                    cid = row[0]
                    try:
                        order_data = _json.loads(row[1])
                        for pos in order_data.get('positions', []):
                            sym = pos.get('symbol', '').strip()
                            if sym and sym not in symbol_to_chain:
                                chain_info = chain_map.get(cid, {})
                                symbol_to_chain[sym] = {
                                    'chain_id': cid,
                                    'strategy_type': chain_info.get('strategy_type', 'Unknown')
                                }
                    except Exception:
                        pass
                # Also add underlying-level fallback entries
                for chain in open_chains:
                    underlying = chain.get('underlying', '').strip()
                    if underlying and underlying not in symbol_to_chain:
                        symbol_to_chain[underlying] = {
                            'chain_id': chain['chain_id'],
                            'strategy_type': chain.get('strategy_type', 'Unknown')
                        }
            logger.info(f"Built symbol lookup with {len(symbol_to_chain)} entries from {len(open_chains)} open chains")
        except Exception as e:
            logger.warning(f"Could not build symbol lookup for enrichment: {e}")

    # Enrich each position with chain metadata
    enriched_count = 0
    for pos in positions_with_dates:
        symbol = pos.get('symbol', '').strip()
        underlying = pos.get('underlying_symbol', '') or pos.get('underlying', '')
        underlying = underlying.strip() if underlying else ''

        match = symbol_to_chain.get(symbol) or symbol_to_chain.get(underlying)
        if match:
            pos['chain_id'] = match['chain_id']
            pos['strategy_type'] = match['strategy_type']
            enriched_count += 1

    logger.info(f"Enriched {enriched_count}/{len(positions_with_dates)} positions with chain_id for account {account_number}")

    # One-time note key migration: move pos_* notes to chain_* keys
    try:
        all_notes = db.get_all_position_notes()
        pos_notes = {k: v for k, v in all_notes.items() if k.startswith('pos_')}
        if pos_notes:
            for pos in positions_with_dates:
                chain_id = pos.get('chain_id')
                if not chain_id:
                    continue
                chain_key = f"chain_{chain_id}"
                if chain_key in all_notes:
                    continue  # chain note already exists
                underlying = pos.get('underlying_symbol', '')
                account = account_number
                # Search for matching pos_* note
                for pk, pv in pos_notes.items():
                    if pk.startswith(f'pos_{underlying}_') and pk.endswith(f'_{account}'):
                        db.save_position_note(chain_key, pv)
                        db.save_position_note(pk, '')  # delete old key
                        logger.info(f"Migrated note '{pk}' -> '{chain_key}'")
                        break
    except Exception as e:
        logger.warning(f"Note migration error (non-fatal): {e}")

    return db.save_positions(positions_with_dates, account_number)


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


class StrategyTarget(BaseModel):
    strategy_name: str
    profit_target_pct: float
    loss_target_pct: float


class OrderCommentUpdate(BaseModel):
    comment: str


class PositionNoteUpdate(BaseModel):
    note: str


@app.on_event("startup")
async def startup_event():
    """Initialize database and connect to Tastytrade on startup"""
    logger.info("Starting OptionEdge Web App")
    db.initialize_database()

    # Auto-connect to Tastytrade using OAuth credentials from .env
    if connection_manager.is_configured():
        logger.info("OAuth credentials found, connecting to Tastytrade...")
        await connection_manager.connect()

        # Auto-sync if connected and it's been a while since last sync
        if connection_manager.connected:
            try:
                last_sync = db.get_last_sync_timestamp()
                if last_sync:
                    time_since_sync = datetime.now() - last_sync
                    hours_since_sync = time_since_sync.total_seconds() / 3600
                    if hours_since_sync > 6:
                        logger.info(f"Auto-sync triggered: {hours_since_sync:.1f} hours since last sync")
                        asyncio.create_task(background_auto_sync())
                    else:
                        logger.info(f"No auto-sync needed: {hours_since_sync:.1f} hours since last sync")
                else:
                    logger.info("No previous sync found - sync will be triggered on first manual sync")
            except Exception as e:
                logger.warning(f"Error checking auto-sync: {e}")
    else:
        logger.warning("No OAuth credentials configured - visit /settings to set up Tastytrade connection")


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

    tastytrade = connection_manager.get_client()
    if not tastytrade:
        logger.error("Auto-sync: Not connected to Tastytrade")
        return

    # Check last sync timestamp to determine date range
    last_sync = db.get_last_sync_timestamp()

    if last_sync:
        # Calculate days back from last sync + 1 day buffer
        days_back = (datetime.now() - last_sync).days + 1
        days_back = max(days_back, 1)  # Minimum 1 day
        days_back = min(days_back, 90)  # Maximum 90 days for safety
        logger.info(f"Auto-sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
    else:
        # No previous sync, fetch last 365 days for auto-sync
        days_back = 365
        logger.info(f"Auto-sync: first sync detected, fetching {days_back} days")

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

    # Fetch and save current positions for all accounts (with chain enrichment)
    logger.info("Auto-sync: Fetching current positions from all accounts...")
    all_positions = await tastytrade.get_positions()
    total_positions = 0

    for account_number, positions in all_positions.items():
        if positions:
            success = enrich_and_save_positions(positions, account_number)
            if success:
                logger.info(f"Auto-sync: Successfully saved {len(positions)} positions for account {account_number}")
                total_positions += len(positions)
            else:
                logger.error(f"Auto-sync: Failed to save positions for account {account_number}")

    # Update last sync timestamp
    db.update_last_sync_timestamp()
    logger.info(f"Auto-sync completed: {total_positions} positions updated")


def _serve_static_page(filename: str) -> HTMLResponse:
    """Helper to serve a static HTML page"""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(app_dir, "static", filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/", response_class=HTMLResponse)
@app.get("/positions", response_class=HTMLResponse)
async def root():
    """Serve the main application - Open Positions Page"""
    return _serve_static_page("positions-dense.html")


@app.get("/chains", response_class=HTMLResponse)
async def order_chains():
    """Serve the Order Chains page"""
    return _serve_static_page("chains-dense.html")


@app.get("/reports", response_class=HTMLResponse)
async def reports_page():
    """Serve the Performance Reports page"""
    return _serve_static_page("reports-dense.html")


@app.get("/risk", response_class=HTMLResponse)
async def risk_dashboard():
    """Serve the Portfolio Risk X-Ray page"""
    return _serve_static_page("risk-dashboard.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Serve the Settings page"""
    return _serve_static_page("settings.html")


@app.get("/api/settings/targets")
async def get_strategy_targets():
    """Get all strategy P&L targets"""
    targets = db.get_strategy_targets()
    return targets


@app.post("/api/settings/targets")
async def save_strategy_targets(targets: List[StrategyTarget]):
    """Save strategy P&L targets"""
    target_dicts = [t.model_dump() for t in targets]
    success = db.save_strategy_targets(target_dicts)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save targets")
    return {"message": "Targets saved successfully"}


@app.post("/api/settings/targets/reset")
async def reset_strategy_targets():
    """Reset strategy targets to defaults"""
    success = db.reset_strategy_targets()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset targets")
    return {"message": "Targets reset to defaults"}


@app.get("/api/order-comments")
async def get_order_comments():
    """Get all order comments"""
    comments = db.get_all_order_comments()
    return {"comments": comments}


@app.put("/api/order-comments/{order_id}")
async def save_order_comment(order_id: str, body: OrderCommentUpdate):
    """Save or delete a comment for an order"""
    success = db.save_order_comment(order_id, body.comment)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save comment")
    return {"message": "Comment saved"}


@app.get("/api/position-notes")
async def get_position_notes():
    """Get all position notes"""
    notes = db.get_all_position_notes()
    return {"notes": notes}


@app.put("/api/position-notes/{note_key:path}")
async def save_position_note(note_key: str, body: PositionNoteUpdate):
    """Save or delete a note for a position"""
    success = db.save_position_note(note_key, body.note)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save note")
    return {"message": "Note saved"}


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
# Connection / Credential Endpoints
# ============================================================================

@app.get("/api/connection/status")
async def get_connection_status():
    """Get Tastytrade connection status"""
    return connection_manager.get_status()


@app.post("/api/connection/reconnect")
async def reconnect():
    """Force reconnection to Tastytrade (after .env update)"""
    from dotenv import load_dotenv
    load_dotenv(override=True)  # Reload .env to pick up new values
    success = await connection_manager.connect()
    return connection_manager.get_status()


class CredentialUpdate(BaseModel):
    provider_secret: str
    refresh_token: str


@app.get("/api/settings/credentials")
async def get_credentials_status():
    """Check if OAuth credentials are configured (never expose actual secrets)"""
    return {"configured": connection_manager.is_configured()}


@app.post("/api/settings/credentials")
async def save_credentials(creds: CredentialUpdate):
    """Save OAuth credentials to .env file"""
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

        # Read existing .env content
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()

        # Update or add credential lines
        new_lines = []
        found_secret = False
        found_token = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('TASTYTRADE_PROVIDER_SECRET'):
                new_lines.append(f'TASTYTRADE_PROVIDER_SECRET={creds.provider_secret}\n')
                found_secret = True
            elif stripped.startswith('TASTYTRADE_REFRESH_TOKEN'):
                new_lines.append(f'TASTYTRADE_REFRESH_TOKEN={creds.refresh_token}\n')
                found_token = True
            else:
                new_lines.append(line)

        if not found_secret:
            new_lines.append(f'TASTYTRADE_PROVIDER_SECRET={creds.provider_secret}\n')
        if not found_token:
            new_lines.append(f'TASTYTRADE_REFRESH_TOKEN={creds.refresh_token}\n')

        with open(env_path, 'w') as f:
            f.writelines(new_lines)

        logger.info("OAuth credentials saved to .env")
        return {"message": "Credentials saved successfully"}
    except Exception as e:
        logger.error(f"Failed to save credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def should_use_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None) -> bool:
    """Check if cached chain data exists for the requested account"""
    # TEMPORARY: Use cache when available per-account
    # The derivation path has compatibility issues with order.transactions that need refactoring
    # For now, cached path works correctly and is performant
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if account_number == '' or account_number is None:
                # "All Accounts" → verify cache covers all accounts that have transactions
                cursor.execute("SELECT COUNT(DISTINCT account_number) FROM order_chains")
                cached_accounts = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(DISTINCT account_number) FROM raw_transactions")
                total_accounts = cursor.fetchone()[0]
                has_cache = cached_accounts > 0 and cached_accounts >= total_accounts
            elif account_number:
                # Specific account number → check for chains in that account
                cursor.execute("SELECT COUNT(*) FROM order_chains WHERE account_number = ? LIMIT 1", (account_number,))
                has_cache = cursor.fetchone()[0] > 0
            else:
                has_cache = False
            if has_cache:
                account_display = account_number if account_number is not None else "unspecified"
                logger.debug(f"Using cached chains for account {account_display} (derivation path temporarily disabled)")
            return has_cache
    except Exception as e:
        logger.error(f"Error checking cache: {e}")
        return False


async def get_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None,
                          limit: int = 10000, offset: int = 0, chain_id: Optional[str] = None):
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

            if chain_id:
                where_conditions.append("oc.chain_id = ?")
                params.append(chain_id)

            # Only filter by account if it's a non-empty string (specific account)
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

                        # Clean up system-generated order IDs and types for display
                        order_id = order_data.get('order_id', '')
                        if order_id.startswith('SYSTEM_'):
                            if 'Expiration' in order_id:
                                order_data['display_type'] = 'EXPIRATION'
                                # Extract date from order_date if available
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"EXPIRATION_{date_part}"
                            elif 'Assignment' in order_id:
                                order_data['display_type'] = 'ASSIGNMENT'
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"ASSIGNMENT_{date_part}"
                            elif 'Exercise' in order_id:
                                order_data['display_type'] = 'EXERCISE'
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"EXERCISE_{date_part}"
                            else:
                                order_data['display_type'] = order_data.get('order_type', 'CLOSING')
                        else:
                            # For regular orders, display_type is the same as order_type
                            if 'display_type' not in order_data:
                                order_data['display_type'] = order_data.get('order_type', 'UNKNOWN')

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


async def update_chain_cache(chains, affected_underlyings: set = None, affected_account: str = None):
    """Update the order_chains table with fresh derivation results

    Args:
        chains: List of Chain objects to cache
        affected_underlyings: Optional set of underlyings to update incrementally.
                             If None and no affected_account, clears and rebuilds entire cache.
        affected_account: Optional account number to scope the cache update.
                         Only clears/rebuilds chains for this account.
    """
    if affected_underlyings:
        logger.info(f"[CACHE UPDATE] Incremental update for {len(affected_underlyings)} underlyings: {affected_underlyings}")
    if affected_account:
        logger.info(f"[CACHE UPDATE] Account-scoped update for account: {affected_account}")
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
            elif affected_account:
                # Account-scoped update: only clear chains for this account
                cursor.execute("""
                    DELETE FROM order_chain_cache WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE account_number = ?
                    )
                """, (affected_account,))
                cursor.execute("""
                    DELETE FROM order_chain_members WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE account_number = ?
                    )
                """, (affected_account,))
                cursor.execute("DELETE FROM order_chains WHERE account_number = ?",
                              (affected_account,))
                logger.info(f"[CACHE UPDATE] Cleared cache for account: {affected_account}")
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
                has_rolls = False

                for order in chain.orders:
                    # Calculate order P&L from transactions since Order doesn't have total_pnl
                    order_pnl = 0.0
                    for tx in order.transactions:
                        # For cash settlements, use value directly (price contains strike, not premium)
                        if tx.is_cash_settlement:
                            order_pnl += tx.value
                        else:
                            value = tx.price * abs(tx.quantity) * 100
                            if tx.is_sell:
                                order_pnl += value
                            else:
                                order_pnl -= value

                    total_pnl += order_pnl

                    if order.order_type.value == 'CLOSING':
                        realized_pnl += order_pnl
                    elif order.order_type.value == 'ROLLING':
                        has_rolls = True
                    else:
                        unrealized_pnl += order_pnl

                # For chains with rolls, the total net premiums represent
                # the realized cash flow from the chain
                if has_rolls:
                    realized_pnl = total_pnl
                    unrealized_pnl = 0.0
                
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
                        # For cash settlements, use value directly (price contains strike, not premium)
                        if tx.is_cash_settlement:
                            order_pnl += tx.value
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
                        "order_date": order.executed_at.isoformat() if order.executed_at else None,
                        "strategy_type": detected_strategy,
                        "status": "FILLED",
                        "total_pnl": order_pnl,
                        "positions": []
                    }
                    
                    # Add positions from transactions with lot data (V3)
                    for idx, tx in enumerate(order.transactions):
                        # For cash settlements, use value directly
                        if tx.is_cash_settlement:
                            tx_pnl = tx.value
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
    chain_id: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0
):
    """Get order chains with intelligent caching for optimal performance"""
    import time
    start_time = time.time()
    logger.info(f"🕐 TIMING: Starting chains API request for account={account_number}, underlying={underlying}, chain_id={chain_id}")

    try:
        # Re-enable caching now that cache has been rebuilt with order details
        use_cache = await should_use_cached_chains(account_number, underlying)

        if use_cache:
            # Fast path: return cached data
            cache_start = time.time()
            cached_result = await get_cached_chains(account_number, underlying, limit, offset, chain_id=chain_id)
            cache_time = time.time() - cache_start
            logger.info(f"🕐 TIMING: Cache lookup took {cache_time:.2f}s")
            if cached_result is not None:
                total_time = time.time() - start_time
                logger.info(f"🕐 TIMING: Total request time (cached): {total_time:.2f}s")
                return cached_result
            # If cache fails, fall through to fresh derivation
            logger.info("🕐 TIMING: Cache miss, falling through to fresh derivation")
        
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

        # Process transactions to get derived chains
        processor_start = time.time()
        chains_by_account = order_processor.process_transactions(raw_transactions)
        processor_time = time.time() - processor_start
        logger.info(f"🕐 TIMING: Chain processing took {processor_time:.2f}s")

        # Flatten chains from all accounts
        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)

        # Update cache with fresh data
        # Scope cache update to the requested account so other accounts' cached data is preserved
        cache_account = account_number if account_number and account_number != '' else None
        logger.info(f"About to update cache with {len(all_chains)} chains (account scope: {cache_account or 'all'})...")
        try:
            await update_chain_cache(all_chains, affected_account=cache_account)
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
        
        # Format for frontend
        format_start = time.time()
        logger.info(f"🕐 TIMING: Starting formatting of {len(paginated_chains)} chains")

        # Pre-fetch live position data once for all chains to improve performance
        live_positions_cache = {}
        api_fetch_start = time.time()
        try:
            client = connection_manager.get_client()
            if client:
                # Get unique account numbers from chains
                unique_accounts = set()
                for chain in paginated_chains:
                    if chain.status == 'OPEN':  # Only need for open chains
                        unique_accounts.add(chain.account_number)

                # Fetch positions for all accounts
                if unique_accounts:
                    for acct in unique_accounts:
                        try:
                            data = await client.get_positions(account_number=acct)
                            live_positions_cache[acct] = data.get(acct, [])
                        except Exception as e:
                            logger.warning(f"Could not fetch positions for account {acct}: {e}")
                            live_positions_cache[acct] = []

                api_fetch_time = time.time() - api_fetch_start
                logger.info(f"🕐 TIMING: Pre-fetched positions for {len(unique_accounts)} accounts in {api_fetch_time:.2f}s")
            else:
                logger.warning("Not connected to Tastytrade - using cached data")
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
                
                # Determine display type (EXPIRATION, ASSIGNMENT, etc. for system orders)
                display_type = order.order_type.value
                if order.order_id.startswith('SYSTEM_'):
                    if 'Expiration' in order.order_id:
                        display_type = 'EXPIRATION'
                    elif 'Assignment' in order.order_id:
                        display_type = 'ASSIGNMENT'
                    elif 'Exercise' in order.order_id:
                        display_type = 'EXERCISE'

                order_info = {
                    'order_id': display_order_id,
                    'order_type': order.order_type.value,
                    'display_type': display_type,
                    'order_date': order.executed_at.isoformat(),
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
                "processor_time": round(processor_time, 2),
                "format_time": round(format_time, 2)
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching order chains: {str(e)}")
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

        # Use shared client
        client = connection_manager.get_client()
        if not client:
            # If not connected, return cached as fallback
            cached_quotes = db.get_cached_quotes(symbol_list)
            if cached_quotes:
                logger.info(f"Not connected, returning fallback cached quotes: {list(cached_quotes.keys())}")
                for symbol, quote_data in cached_quotes.items():
                    if 'mark' in quote_data and quote_data['mark'] is not None:
                        quote_data['price'] = quote_data['mark']
                    if 'change_percent' in quote_data:
                        quote_data['changePercent'] = quote_data['change_percent']
                    if 'iv_percentile' in quote_data:
                        quote_data['ivPercentile'] = quote_data['iv_percentile']
                return cached_quotes
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        # Clear cache if refresh requested
        if refresh:
            client.clear_quote_cache()
            logger.info("Cache cleared due to refresh parameter")

        # Get quotes from Tastytrade API
        quotes = await client.get_quotes(symbol_list)
        
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


@app.get("/api/debug/balances")
async def debug_balances():
    """Debug endpoint to see all balance fields from Tastytrade API"""
    try:
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        all_balances = []
        for account in tastytrade.accounts:
            balance = await account.get_balances(tastytrade.session)

            # Get all numeric fields
            balance_data = {
                'account_number': account.account_number,
            }
            for field in dir(balance):
                if not field.startswith('_'):
                    try:
                        value = getattr(balance, field)
                        if not callable(value) and value is not None:
                            # Convert Decimal to float for JSON
                            if hasattr(value, '__float__'):
                                balance_data[field] = float(value)
                            else:
                                balance_data[field] = str(value)
                    except:
                        pass
            all_balances.append(balance_data)

        return {"balances": all_balances}
    except Exception as e:
        logger.error(f"Debug balance error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions/cached")
async def get_cached_positions(account_number: Optional[str] = None):
    """Get cached positions immediately without sync - chain_id already persisted"""
    try:
        positions = db.get_open_positions()

        if account_number:
            positions = [p for p in positions if p.get('account_number') == account_number]

        # Get the last sync timestamp for freshness metadata
        last_sync = db.get_last_sync_timestamp()
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
            # No previous sync, fetch last 365 days
            days_back = 365
            logger.info(f"Background sync: no previous sync, fetching {days_back} days")

        # Use shared client
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            logger.warning("Background sync: not connected to Tastytrade, skipping")
            return

        try:
            # Fetch transactions from all accounts
            transactions = await tastytrade.get_transactions(days_back=days_back)
            logger.info(f"Background sync: fetched {len(transactions)} transactions")

            # Save raw transactions
            raw_saved = db.save_raw_transactions(transactions)
            logger.info(f"Background sync: saved {raw_saved} raw transactions")

            # Fetch and save current positions (with chain enrichment)
            all_positions = await tastytrade.get_positions()
            total_positions = 0

            for account_number, positions in all_positions.items():
                if positions:
                    success = enrich_and_save_positions(positions, account_number)
                    if success:
                        total_positions += len(positions)

            logger.info(f"Background sync: saved {total_positions} positions")

            # Reprocess chains to update order processing
            raw_transactions = db.get_raw_transactions()
            chains_by_account = order_processor.process_transactions(raw_transactions)

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
    """Get current open positions - chain_id/strategy_type already persisted at sync time"""
    try:
        positions = db.get_open_positions()

        if account_number:
            positions = [p for p in positions if p.get('account_number') == account_number]

        # Group positions by account (matching the expected frontend format)
        positions_by_account = {}
        for position in positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)

        logger.info(f"/api/positions: Returning {len(positions)} positions grouped by {len(positions_by_account)} accounts")
        return positions_by_account
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/open-chains")
async def get_open_chains(account_number: Optional[str] = None):
    """Get open chains formatted for the Positions page — chain-as-source-of-truth.

    Returns chains grouped by account_number with:
    - Each chain's realized_pnl, cost_basis_total, roll_count
    - open_legs: currently open option legs (derived by netting across all orders)
    - shares: equity positions separated out per underlying
    """
    import json as _json

    try:
        chain_summaries = db.get_open_chain_summaries(account_number)
        if not chain_summaries:
            return {}

        result = {}  # account_number -> { chains: [...], shares: {...} }

        for chain_summary in chain_summaries:
            chain_id = chain_summary['chain_id']
            acct = chain_summary['account_number']

            if acct not in result:
                result[acct] = {"chains": [], "shares": {}}

            # Load cached order data for this chain
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT order_data FROM order_chain_cache
                    WHERE chain_id = ? ORDER BY order_id
                """, (chain_id,))
                order_rows = cursor.fetchall()

            orders = []
            for row in order_rows:
                try:
                    orders.append(_json.loads(row[0]))
                except (_json.JSONDecodeError, IndexError):
                    continue

            # --- Derive open legs by netting positions across all orders ---
            # Track net signed quantity per option symbol: positive = long, negative = short
            # Also track the metadata (strike, exp, price, etc.) for the most recent opening
            option_net = {}   # symbol -> { signed_qty, metadata }
            cost_basis_total = 0.0
            roll_count = 0

            for order in orders:
                order_type = order.get('order_type', '')
                if order_type == 'ROLLING':
                    roll_count += 1

                for pos in order.get('positions', []):
                    qty = pos.get('quantity', 0)
                    price = pos.get('opening_price', 0) or 0
                    instrument = pos.get('instrument_type', '')
                    action = str(pos.get('opening_action', ''))
                    symbol = (pos.get('symbol') or '').strip()
                    multiplier = 100 if instrument == 'EQUITY_OPTION' else 1

                    # Accumulate cost basis across all orders
                    if price and qty:
                        amount = price * abs(qty) * multiplier
                        if order_type == 'CLOSING':
                            if 'BTC' in action or 'BUY_TO_CLOSE' in action or 'BUY' in action:
                                cost_basis_total -= amount
                            elif 'STC' in action or 'SELL_TO_CLOSE' in action or 'SELL' in action:
                                cost_basis_total += amount
                        else:
                            if 'SELL_TO_' in action or 'STO' in action or action == 'SELL':
                                cost_basis_total += amount
                            elif 'BUY_TO_' in action or 'BTO' in action or action == 'BUY':
                                cost_basis_total -= amount

                    # Handle closing legs within opening/rolling orders
                    closing_price = pos.get('closing_price')
                    closing_action = str(pos.get('closing_action', ''))
                    if closing_price and closing_action and qty:
                        c_amount = closing_price * abs(qty) * multiplier
                        if 'BTC' in closing_action or 'BUY' in closing_action:
                            cost_basis_total -= c_amount
                        elif 'STC' in closing_action or 'SELL' in closing_action:
                            cost_basis_total += c_amount

                    # Net option positions by symbol
                    if instrument == 'EQUITY_OPTION' and symbol:
                        is_sell = 'SELL' in action or 'STO' in action
                        is_buy = 'BUY' in action or 'BTO' in action
                        is_close = 'CLOSE' in action or order_type == 'CLOSING'

                        if is_sell and is_close:
                            # Sell to close: reduces long position
                            signed_delta = -abs(qty)
                        elif is_buy and is_close:
                            # Buy to close: reduces short position
                            signed_delta = abs(qty)
                        elif is_sell:
                            # Sell to open: creates short
                            signed_delta = -abs(qty)
                        elif is_buy:
                            # Buy to open: creates long
                            signed_delta = abs(qty)
                        else:
                            # Expiration/assignment closings with no action
                            if order_type in ('CLOSING',) and not action:
                                # System-generated closing — zero out this symbol
                                if symbol in option_net:
                                    option_net[symbol]['signed_qty'] = 0
                                continue
                            else:
                                continue

                        if symbol not in option_net:
                            option_net[symbol] = {'signed_qty': 0, 'metadata': {}}

                        option_net[symbol]['signed_qty'] += signed_delta

                        # Update metadata for opening positions (latest wins)
                        if not is_close:
                            option_net[symbol]['metadata'] = {
                                'symbol': symbol,
                                'underlying': pos.get('underlying', chain_summary['underlying']),
                                'instrument_type': instrument,
                                'option_type': pos.get('option_type'),
                                'strike': pos.get('strike'),
                                'expiration': pos.get('expiration'),
                                'opening_price': price,
                                'lot_id': pos.get('lot_id'),
                            }

                    # (Equity positions are sourced from TT API positions table below)

            # Convert net option positions to open_legs list
            open_option_legs = []
            for symbol, net_data in option_net.items():
                net_qty = net_data['signed_qty']
                if net_qty == 0:
                    continue  # fully closed
                meta = net_data['metadata']
                if not meta:
                    continue  # no opening data available

                qty_direction = 'Short' if net_qty < 0 else 'Long'
                abs_qty = abs(net_qty)
                price = meta.get('opening_price', 0)
                leg_amount = price * abs_qty * 100 if price else 0
                leg_cost = leg_amount if qty_direction == 'Short' else -leg_amount

                open_option_legs.append({
                    "symbol": meta['symbol'],
                    "underlying": meta.get('underlying', chain_summary['underlying']),
                    "instrument_type": meta['instrument_type'],
                    "option_type": meta.get('option_type'),
                    "strike": meta.get('strike'),
                    "expiration": meta.get('expiration'),
                    "quantity": abs_qty,
                    "quantity_direction": qty_direction,
                    "opening_price": price,
                    "cost_basis": leg_cost,
                    "lot_id": meta.get('lot_id'),
                })

            # Build chain object for frontend
            chain_obj = {
                "chain_id": chain_id,
                "underlying": chain_summary['underlying'],
                "account_number": acct,
                "strategy_type": chain_summary['strategy_type'] or 'Unknown',
                "opening_date": chain_summary['opening_date'],
                "chain_status": chain_summary['chain_status'],
                "realized_pnl": chain_summary['realized_pnl'] or 0.0,
                "cost_basis_total": cost_basis_total,
                "roll_count": roll_count,
                "order_count": chain_summary['order_count'] or 0,
                "has_assignment": bool(chain_summary.get('has_assignment')),
                "open_legs": open_option_legs,
            }
            # Only include chains that have open option legs
            # Stock-only chains (like STRC) have no option legs — equity is shown via TT positions
            if open_option_legs:
                result[acct]["chains"].append(chain_obj)

        # Source equity positions from TT API positions table (reliable for shares)
        tt_positions = db.get_open_positions()
        for pos in tt_positions:
            instrument = pos.get('instrument_type', '')
            # Match both enum-style and plain strings
            if 'OPTION' in instrument.upper():
                continue  # skip options, already handled by chains
            if 'EQUITY' not in instrument.upper():
                continue  # skip anything else

            acct = pos.get('account_number', '')
            if account_number and account_number != '' and acct != account_number:
                continue

            if acct not in result:
                result[acct] = {"chains": [], "shares": {}}

            sym = pos.get('underlying') or pos.get('symbol', '')
            qty = pos.get('quantity', 0)
            direction = pos.get('quantity_direction', 'Long')
            signed_qty = qty if direction == 'Long' else -qty
            avg_price = abs(pos.get('average_open_price', 0) or 0)
            # TT stores equity cost_basis as negative for Long (cash outflow convention)
            # Normalize to positive = amount invested
            raw_cost = pos.get('cost_basis', 0) or 0
            cost_basis = abs(raw_cost) if raw_cost else (avg_price * qty)

            shares_map = result[acct]["shares"]
            if sym not in shares_map:
                shares_map[sym] = {
                    "symbol": sym,
                    "underlying": sym,
                    "instrument_type": "EQUITY",
                    "quantity": 0,
                    "total_cost": 0.0,
                    "average_open_price": 0.0,
                    "positions": [],
                }
            shares_map[sym]["quantity"] += signed_qty
            shares_map[sym]["total_cost"] += cost_basis
            shares_map[sym]["positions"].append({
                "symbol": pos.get('symbol', sym),
                "underlying": sym,
                "instrument_type": "EQUITY",
                "quantity": signed_qty,
                "quantity_direction": direction,
                "average_open_price": avg_price,
                "cost_basis": cost_basis,
                "account_number": acct,
            })

        # Compute weighted average price for each share group
        for acct_data in result.values():
            for sym, share_data in acct_data["shares"].items():
                if share_data["quantity"] != 0:
                    share_data["average_open_price"] = share_data["total_cost"] / abs(share_data["quantity"])
                share_data["cost_basis"] = share_data["total_cost"]

        logger.info(f"/api/open-chains: Returning {sum(len(a['chains']) for a in result.values())} chains, {sum(len(a['shares']) for a in result.values())} equity groups across {len(result)} accounts")
        return result

    except Exception as e:
        logger.error(f"Error in /api/open-chains: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def reconcile_positions_vs_chains():
    """Compare TT API positions against chain-derived open legs.

    Returns a summary with categories:
    - MATCHED: symbol+account+quantity agree
    - QUANTITY_MISMATCH: same symbol but different quantity
    - UNLINKED: TT has position, chains don't
    - STALE: chain says open but TT doesn't have it (auto-expires past-expiry options)
    """
    import json as _json
    from datetime import date as _date

    try:
        # 1. Get TT API positions (from positions table)
        tt_positions = db.get_open_positions()
        # Build lookup: (account, symbol) -> position
        tt_by_key = {}
        for pos in tt_positions:
            key = (pos.get('account_number', ''), (pos.get('symbol') or '').strip())
            tt_by_key[key] = pos

        # 2. Get chain-derived open option legs (equity is sourced from TT directly, not reconciled)
        chain_summaries = db.get_open_chain_summaries()
        chain_legs_by_key = {}  # (account, symbol) -> { quantity, chain_id, ... }

        for chain_summary in chain_summaries:
            chain_id = chain_summary['chain_id']
            acct = chain_summary['account_number']

            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT order_data FROM order_chain_cache WHERE chain_id = ? ORDER BY order_id", (chain_id,))
                order_rows = cursor.fetchall()

            orders = []
            for row in order_rows:
                try:
                    orders.append(_json.loads(row[0]))
                except:
                    continue

            # Net option positions by symbol (same logic as /api/open-chains)
            option_net = {}
            for order in orders:
                order_type = order.get('order_type', '')
                for pos in order.get('positions', []):
                    qty = pos.get('quantity', 0)
                    instrument = pos.get('instrument_type', '')
                    action = str(pos.get('opening_action', ''))
                    symbol = (pos.get('symbol') or '').strip()

                    if instrument == 'EQUITY_OPTION' and symbol:
                        is_sell = 'SELL' in action or 'STO' in action
                        is_buy = 'BUY' in action or 'BTO' in action
                        is_close = 'CLOSE' in action or order_type == 'CLOSING'

                        if is_sell and is_close:
                            signed_delta = -abs(qty)
                        elif is_buy and is_close:
                            signed_delta = abs(qty)
                        elif is_sell:
                            signed_delta = -abs(qty)
                        elif is_buy:
                            signed_delta = abs(qty)
                        else:
                            if order_type == 'CLOSING' and not action:
                                if symbol in option_net:
                                    option_net[symbol] = 0
                                continue
                            else:
                                continue

                        option_net[symbol] = option_net.get(symbol, 0) + signed_delta

            for symbol, net_qty in option_net.items():
                if net_qty != 0:
                    key = (acct, symbol)
                    chain_legs_by_key[key] = {
                        'quantity': net_qty,
                        'chain_id': chain_id,
                        'underlying': chain_summary['underlying'],
                        'expiration': None,  # would need to track per-symbol
                    }

        # 3. Reconcile
        matched = 0
        quantity_mismatch = []
        unlinked = []
        stale = []
        today = _date.today()

        all_chain_keys = set(chain_legs_by_key.keys())
        all_tt_keys = set(tt_by_key.keys())

        # Check TT positions against chains (options only — equity is sourced directly from TT)
        for key in all_tt_keys:
            acct, symbol = key
            tt_pos = tt_by_key[key]
            instrument = tt_pos.get('instrument_type', '').upper()
            is_option = 'OPTION' in instrument

            # Skip equity — it's always shown from TT positions directly, no chain reconciliation needed
            if not is_option:
                continue

            tt_qty = tt_pos.get('quantity', 0)
            if tt_pos.get('quantity_direction') == 'Short':
                tt_signed = -abs(tt_qty)
            else:
                tt_signed = abs(tt_qty)

            if key in chain_legs_by_key:
                chain_data = chain_legs_by_key[key]
                if chain_data['quantity'] == tt_signed:
                    matched += 1
                else:
                    quantity_mismatch.append({
                        'symbol': symbol,
                        'account': acct,
                        'tt_quantity': tt_signed,
                        'chain_quantity': chain_data['quantity'],
                        'chain_id': chain_data['chain_id'],
                    })
            else:
                unlinked.append({
                    'symbol': symbol,
                    'account': acct,
                    'quantity': tt_signed,
                    'instrument_type': tt_pos.get('instrument_type', ''),
                    'underlying': tt_pos.get('underlying', ''),
                })

        # Check chain legs that TT doesn't have (stale)
        for key in all_chain_keys - all_tt_keys:
            acct, symbol = key
            chain_data = chain_legs_by_key.get(key, {})
            stale.append({
                'symbol': symbol,
                'account': acct,
                'chain_quantity': chain_data.get('quantity', 0),
                'chain_id': chain_data.get('chain_id', ''),
            })

        # Auto-close stale chains in two passes:
        # Pass 1: Chains with stale option legs and no matched legs
        # Pass 2: "Ghost" chains — zero net option legs AND no TT positions for that underlying+account
        auto_closed = []

        # Collect chain_ids that have at least one matched option leg in TT
        matched_chain_ids = set()
        for key in all_chain_keys & all_tt_keys:
            cd = chain_legs_by_key.get(key, {})
            if cd.get('chain_id'):
                matched_chain_ids.add(cd['chain_id'])

        # Also collect chain_ids that appear in chain_legs_by_key (have any option footprint)
        chains_with_option_legs = set(cd['chain_id'] for cd in chain_legs_by_key.values())

        # Pass 1: Chains with stale legs and no matched legs
        if stale:
            stale_chain_ids = set(s['chain_id'] for s in stale if s.get('chain_id'))
            for chain_id in stale_chain_ids - matched_chain_ids:
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE order_chains SET chain_status = 'CLOSED', closing_date = ? WHERE chain_id = ? AND chain_status IN ('OPEN', 'ASSIGNED')",
                            (today.isoformat(), chain_id)
                        )
                        if cursor.rowcount > 0:
                            auto_closed.append(chain_id)
                            logger.info(f"Auto-closed stale chain {chain_id} — TT has no matching positions")
                        conn.commit()
                except Exception as e:
                    logger.error(f"Failed to auto-close chain {chain_id}: {e}")

        # Pass 2: Ghost chains — OPEN/ASSIGNED with zero net option legs and no TT positions
        # These are chains where all options were closed/assigned/expired (netting = 0)
        # but chain_status was never updated. Check if TT has ANY position for that underlying+account.
        tt_underlyings_by_acct = {}
        for pos in tt_positions:
            acct = pos.get('account_number', '')
            und = (pos.get('underlying') or pos.get('symbol', '')).strip()
            tt_underlyings_by_acct.setdefault(acct, set()).add(und)

        for chain_summary in chain_summaries:
            chain_id = chain_summary['chain_id']
            if chain_id in set(auto_closed):
                continue  # already handled in pass 1
            if chain_id in chains_with_option_legs:
                continue  # has open option legs, not a ghost
            if chain_id in matched_chain_ids:
                continue  # has matched legs

            # This chain has zero net option legs — check if TT has any position for this underlying
            acct = chain_summary['account_number']
            underlying = chain_summary['underlying']
            tt_has_underlying = underlying in tt_underlyings_by_acct.get(acct, set())

            if not tt_has_underlying:
                # TT has nothing for this underlying+account — auto-close
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE order_chains SET chain_status = 'CLOSED', closing_date = ? WHERE chain_id = ? AND chain_status IN ('OPEN', 'ASSIGNED')",
                            (today.isoformat(), chain_id)
                        )
                        if cursor.rowcount > 0:
                            auto_closed.append(chain_id)
                            logger.info(f"Auto-closed ghost chain {chain_id} ({underlying}/{acct}) — no option legs and no TT positions")
                        conn.commit()
                except Exception as e:
                    logger.error(f"Failed to auto-close ghost chain {chain_id}: {e}")

        # Remove auto-closed entries from stale list (they've been resolved)
        if auto_closed:
            stale = [s for s in stale if s.get('chain_id') not in auto_closed]

        total = matched + len(quantity_mismatch) + len(unlinked) + len(stale)
        summary = {
            'total': total,
            'matched': matched,
            'quantity_mismatch': quantity_mismatch,
            'unlinked': unlinked,
            'stale': stale,
            'auto_closed': auto_closed,
        }
        logger.info(f"Reconciliation: {matched}/{total} matched, {len(quantity_mismatch)} qty mismatch, {len(unlinked)} unlinked, {len(stale)} stale, {len(auto_closed)} auto-closed")
        return summary

    except Exception as e:
        logger.error(f"Reconciliation error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'total': 0, 'matched': 0, 'quantity_mismatch': [], 'unlinked': [], 'stale': [], 'error': str(e)}


@app.get("/api/reconcile")
async def get_reconciliation():
    """Run position reconciliation and return results"""
    return await reconcile_positions_vs_chains()


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
async def sync_positions_only():
    """Fast sync that only updates current positions without reprocessing orders"""
    try:
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        logger.info("Starting positions-only sync (fast mode)...")

        # Fetch and save current positions for all accounts (with chain enrichment)
        logger.info("Fetching current positions from all accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if positions:
                success = enrich_and_save_positions(positions, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        # Fetch and save account balances
        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                db.save_account_balance(balance)

        logger.info(f"Fast sync completed: {total_positions} positions updated")

        # Run reconciliation after sync
        reconciliation = await reconcile_positions_vs_chains()

        return {
            "message": f"Fast sync completed: {total_positions} positions updated",
            "positions_updated": total_positions,
            "mode": "positions_only",
            "reconciliation": reconciliation
        }

    except Exception as e:
        logger.error(f"Error during fast sync: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
async def sync_unified():
    """Unified sync endpoint with smart date range calculation"""
    try:
        from datetime import datetime, timedelta

        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        logger.info("Sync requested")

        # Check last sync timestamp to determine date range
        last_sync = db.get_last_sync_timestamp()

        if last_sync:
            # Calculate days back from last sync + 1 day buffer
            days_back = (datetime.now() - last_sync).days + 1
            days_back = max(days_back, 1)  # Minimum 1 day
            days_back = min(days_back, 90)  # Maximum 90 days for safety
            logger.info(f"Incremental sync: last sync {last_sync.strftime('%Y-%m-%d %H:%M')}, fetching {days_back} days")
        else:
            # No previous sync, fetch last 365 days
            days_back = 365
            logger.info(f"First sync detected, fetching {days_back} days")

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
        transactions = await tastytrade.get_transactions(days_back=days_back)
        logger.info(f"Fetched {len(transactions)} transactions")
        
        # Save raw transactions first (for order ID support)
        logger.info("Saving raw transactions...")
        raw_saved = db.save_raw_transactions(transactions)
        logger.info(f"Saved {raw_saved} raw transactions")
        
        saved_count = len(transactions)

        # Fetch account balances for all accounts
        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
        if balances:
            for balance in balances:
                success = db.save_account_balance(balance)
                if success:
                    logger.info(f"Successfully saved balance for account {balance.get('account_number')}")
                else:
                    logger.error(f"Failed to save balance for account {balance.get('account_number')}")

        # Update last sync timestamp
        db.update_last_sync_timestamp()
        logger.info("Updated last sync timestamp")

        # Reprocess chains BEFORE saving positions (chains must exist for enrichment)
        if raw_saved > 0:
            # Extract affected underlyings from the fetched transactions
            affected_underlyings = set()
            for txn in transactions:
                underlying = txn.get('underlying_symbol', '')
                if underlying:
                    underlying = underlying.split()[0] if ' ' in underlying else underlying
                    affected_underlyings.add(underlying)

            use_incremental = raw_saved < 50 and len(affected_underlyings) <= 10

            if use_incremental:
                logger.info(f"Incremental chain reprocessing for {len(affected_underlyings)} underlyings: {affected_underlyings}")
            else:
                logger.info(f"Full chain reprocessing (raw_saved={raw_saved}, underlyings={len(affected_underlyings)})")
                affected_underlyings = None

            try:
                position_manager.clear_all_positions()
                lot_manager.clear_all_lots()
                logger.info("Cleared position inventory and lots for reprocessing")

                if use_incremental and affected_underlyings:
                    all_chains = []
                    for underlying in affected_underlyings:
                        underlying_txs = db.get_raw_transactions(underlying=underlying)
                        if underlying_txs:
                            chains_by_account = order_processor.process_transactions(underlying_txs)
                            for account, chains in chains_by_account.items():
                                all_chains.extend(chains)
                    logger.info(f"Incremental reprocessing created {len(all_chains)} chains for affected underlyings")
                else:
                    raw_transactions = db.get_raw_transactions()
                    chains_by_account = order_processor.process_transactions(raw_transactions)
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

        # Fetch and save positions AFTER chain reprocessing (so enrichment can find chains)
        logger.info("Fetching current positions from all accounts...")
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if positions:
                success = enrich_and_save_positions(positions, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        logger.info(f"Sync completed: {saved_count} transactions processed, {total_positions} positions updated")

        # Run reconciliation after sync
        reconciliation = await reconcile_positions_vs_chains()

        return {
            "message": f"Sync completed: {saved_count} new transactions processed",
            "transactions_processed": saved_count,
            "positions_updated": total_positions,
            "last_sync": db.get_last_sync_timestamp().isoformat() if db.get_last_sync_timestamp() else None,
            "reconciliation": reconciliation
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
        tastytrade = connection_manager.get_client()
        if not tastytrade:
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        logger.info("Starting INITIAL SYNC - this will rebuild the entire database")

        # Reset sync metadata
        logger.info("Resetting sync metadata...")
        db.reset_sync_metadata()

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
            cursor.execute("DELETE FROM positions")
            cursor.execute("DELETE FROM account_balances")
            cursor.execute("DELETE FROM raw_transactions")

            logger.info("Database cleared successfully")

        # Reinitialize database to create tables with latest schema
        logger.info("Recreating database tables with latest schema...")
        db.initialize_database()

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
        logger.info("Fetching ALL transactions (last 730 days)...")
        transactions = await tastytrade.get_transactions(days_back=730)
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
        all_positions = await tastytrade.get_positions()
        total_positions = 0

        for account_number, positions in all_positions.items():
            if positions:
                positions_with_dates = calculate_position_opening_dates(positions, account_number)
                success = db.save_positions(positions_with_dates, account_number)
                if success:
                    logger.info(f"Successfully saved {len(positions)} positions for account {account_number}")
                    total_positions += len(positions)
                else:
                    logger.error(f"Failed to save positions for account {account_number}")

        # Fetch and save account balances for all accounts
        logger.info("Fetching account balances...")
        balances = await tastytrade.get_account_balances()
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
        
        # Reprocess chains using the OrderProcessor pipeline (strategy detection + cache)
        logger.info("Reprocessing chains with strategy detection after initial sync...")
        try:
            raw_transactions = db.get_raw_transactions()
            position_manager.clear_all_positions()
            lot_manager.clear_all_lots()
            chains_by_account = order_processor.process_transactions(raw_transactions)
            all_chains = []
            for account, chains in chains_by_account.items():
                all_chains.extend(chains)
            await update_chain_cache(all_chains)
            logger.info(f"Chain reprocessing completed: {len(all_chains)} chains with strategy detection")
        except Exception as e:
            logger.error(f"Error during chain reprocessing: {str(e)}", exc_info=True)
        
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

        # Get all raw transactions from database
        raw_transactions = db.get_raw_transactions()
        logger.info(f"Loaded {len(raw_transactions)} raw transactions from database")

        # Clear existing position inventory and lots before reprocessing
        position_manager.clear_all_positions()
        lot_manager.clear_all_lots()
        logger.info("Cleared position inventory and lots for reprocessing")

        # Use processor to create chains
        chains_by_account = order_processor.process_transactions(raw_transactions)
        
        # Flatten chains from all accounts
        all_chains = []
        for account, chains in chains_by_account.items():
            for chain in chains:
                all_chains.append(chain)
        
        # Update cache with fresh data
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
async def get_available_strategies():
    """Get list of strategies that have been used in closed trades"""
    try:
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
    account_number: Optional[str] = None,
    days: str = "90",
    strategies: str = ""
):
    """Get performance report data for closed trades"""
    try:
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
    # Get the chain from processor (same as cache update process)
    raw_transactions = db.get_raw_transactions()
    chains_by_account = order_processor.process_transactions(raw_transactions)
    
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
        "debug_path": "fresh_processing"
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
    chains_by_account = order_processor.process_transactions(raw_transactions)
    
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
        chains_by_account = order_processor.process_transactions(raw_transactions)
        
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

    subscribed_symbols = []

    try:
        # Send a connection confirmation
        await websocket.send_json({"type": "connected", "message": "WebSocket connected"})

        # Use shared client
        client = connection_manager.get_client()
        if not client:
            logger.error("WebSocket connection rejected: Not connected to Tastytrade")
            await websocket.send_json({"error": "Not connected to Tastytrade - check settings"})
            await websocket.close()
            return

        logger.info("WebSocket client connected using shared Tastytrade session")
        
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
                                quotes = await client.get_quotes(subscribed_symbols)
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
                        quotes = await client.get_quotes(subscribed_symbols)
                        
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