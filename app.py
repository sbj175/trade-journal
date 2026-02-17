#!/usr/bin/env python3

"""
OptionLedger Web Application
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
from fastapi.templating import Jinja2Templates
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
    title="OptionLedger",
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

# Jinja2 templates for server-side rendering (nav bar partial, etc.)
templates = Jinja2Templates(directory="static")

# Nav links - single source of truth for all pages
NAV_LINKS = [
    {"href": "/positions", "label": "Positions"},
    {"href": "/ledger", "label": "Ledger"},
    {"href": "/reports", "label": "Reports"},
    {"href": "/risk", "label": "Risk"},
]


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



class LedgerGroupUpdate(BaseModel):
    strategy_label: Optional[str] = None


class LedgerMoveLots(BaseModel):
    transaction_ids: List[str]
    target_group_id: str


class LedgerCreateGroup(BaseModel):
    account_number: str
    underlying: str
    strategy_label: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    """Initialize database and connect to Tastytrade on startup"""
    logger.info("Starting OptionLedger Web App")
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


def _nav_context(request: Request, active_path: str, variant: str = "standard") -> dict:
    """Build template context with nav bar variables"""
    return {
        "request": request,
        "nav_links": NAV_LINKS,
        "active_path": active_path,
        "nav_variant": variant,
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/positions", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application - Open Positions Page"""
    return templates.TemplateResponse("positions-dense.html", _nav_context(request, "/positions"))


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the Performance Reports page"""
    return templates.TemplateResponse("reports-dense.html", _nav_context(request, "/reports"))


@app.get("/risk", response_class=HTMLResponse)
async def risk_dashboard(request: Request):
    """Serve the Portfolio Risk X-Ray page"""
    return templates.TemplateResponse("risk-dashboard.html", _nav_context(request, "/risk"))


@app.get("/ledger", response_class=HTMLResponse)
async def ledger_page(request: Request):
    """Serve the Position Ledger page"""
    return templates.TemplateResponse("ledger-dense.html", _nav_context(request, "/ledger"))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the Settings page"""
    return templates.TemplateResponse("settings.html", _nav_context(request, "/settings", "settings"))


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


# ============================================================================
# Ledger (Position Groups) Endpoints
# ============================================================================

def seed_position_groups():
    """Seed position_groups from existing chains. Idempotent — skips chains already seeded."""
    import uuid as _uuid
    groups_created = 0

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Get all distinct chain_ids from position_lots
        cursor.execute("""
            SELECT DISTINCT chain_id, account_number, underlying
            FROM position_lots
            WHERE chain_id IS NOT NULL
        """)
        chain_rows = cursor.fetchall()

        for row in chain_rows:
            chain_id, account_number, underlying = row
            if not chain_id:
                continue

            # Check if group already exists for this chain
            cursor.execute(
                "SELECT group_id FROM position_groups WHERE source_chain_id = ?",
                (chain_id,)
            )
            if cursor.fetchone():
                continue

            # Get chain metadata
            cursor.execute(
                "SELECT strategy_type, opening_date, closing_date, chain_status FROM order_chains WHERE chain_id = ?",
                (chain_id,)
            )
            chain_info = cursor.fetchone()
            strategy_label = chain_info[0] if chain_info else None
            opening_date = chain_info[1] if chain_info else None
            closing_date = chain_info[2] if chain_info else None
            chain_status = chain_info[3] if chain_info else 'OPEN'

            # Check actual lot statuses to determine group status
            cursor.execute("""
                SELECT COUNT(*) FROM position_lots
                WHERE chain_id = ? AND remaining_quantity != 0 AND status != 'CLOSED'
            """, (chain_id,))
            open_count = cursor.fetchone()[0]
            status = 'OPEN' if open_count > 0 else 'CLOSED'

            # Compute opening/closing dates from lots if not available
            if not opening_date:
                cursor.execute(
                    "SELECT MIN(entry_date) FROM position_lots WHERE chain_id = ?",
                    (chain_id,)
                )
                r = cursor.fetchone()
                opening_date = r[0] if r else None

            if status == 'CLOSED' and not closing_date:
                cursor.execute("""
                    SELECT MAX(lc.closing_date) FROM lot_closings lc
                    JOIN position_lots pl ON lc.lot_id = pl.id
                    WHERE pl.chain_id = ?
                """, (chain_id,))
                r = cursor.fetchone()
                closing_date = r[0] if r else None

            group_id = str(_uuid.uuid4())
            cursor.execute("""
                INSERT INTO position_groups
                    (group_id, account_number, underlying, strategy_label, status,
                     source_chain_id, opening_date, closing_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (group_id, account_number, underlying or '', strategy_label,
                  status, chain_id, opening_date, closing_date))

            # Link lots to group via transaction_id
            cursor.execute(
                "SELECT transaction_id FROM position_lots WHERE chain_id = ?",
                (chain_id,)
            )
            txn_ids = [r[0] for r in cursor.fetchall()]
            for txn_id in txn_ids:
                cursor.execute("""
                    INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                    VALUES (?, ?)
                """, (group_id, txn_id))

            groups_created += 1

        # Handle lots with no chain_id — create "Ungrouped" groups per underlying/account
        cursor.execute("""
            SELECT pl.transaction_id, pl.account_number, pl.underlying
            FROM position_lots pl
            LEFT JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
            WHERE pgl.transaction_id IS NULL AND pl.chain_id IS NULL
        """)
        ungrouped = cursor.fetchall()

        if ungrouped:
            # Group by account+underlying
            buckets: Dict[str, list] = {}
            for txn_id, acct, und in ungrouped:
                key = f"{acct}|{und or ''}"
                buckets.setdefault(key, []).append(txn_id)

            for key, txn_ids in buckets.items():
                acct, und = key.split('|', 1)
                group_id = str(_uuid.uuid4())
                cursor.execute("""
                    INSERT INTO position_groups
                        (group_id, account_number, underlying, strategy_label, status,
                         source_chain_id, opening_date, closing_date)
                    VALUES (?, ?, ?, 'Ungrouped', 'OPEN', NULL, NULL, NULL)
                """, (group_id, acct, und))
                for txn_id in txn_ids:
                    cursor.execute("""
                        INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                        VALUES (?, ?)
                    """, (group_id, txn_id))
                groups_created += 1

        conn.commit()

    logger.info(f"Seeded {groups_created} position groups")
    return groups_created


def seed_new_lots_into_groups():
    """After reprocessing, assign new lots (not in any group) to their chain's group or create new groups."""
    import uuid as _uuid
    assigned = 0

    unassigned = lot_manager.get_unassigned_lots()
    if not unassigned:
        # Still refresh group statuses even if no new lots to assign
        with db.get_connection() as conn:
            cursor = conn.cursor()
            _refresh_all_group_statuses(cursor)
            conn.commit()
        return 0

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Check if position_groups table has any rows — if empty, do full seed instead
        cursor.execute("SELECT COUNT(*) FROM position_groups")
        if cursor.fetchone()[0] == 0:
            return seed_position_groups()

        # Group unassigned lots by chain_id
        chain_lots: Dict[Optional[str], list] = {}
        for lot in unassigned:
            chain_lots.setdefault(lot.chain_id, []).append(lot)

        for chain_id, lots in chain_lots.items():
            if chain_id:
                # Check if a group exists for this chain
                cursor.execute(
                    "SELECT group_id FROM position_groups WHERE source_chain_id = ?",
                    (chain_id,)
                )
                row = cursor.fetchone()
                if row:
                    group_id = row[0]
                else:
                    # Create new group for this chain
                    cursor.execute(
                        "SELECT strategy_type, opening_date, closing_date FROM order_chains WHERE chain_id = ?",
                        (chain_id,)
                    )
                    chain_info = cursor.fetchone()
                    group_id = str(_uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO position_groups
                            (group_id, account_number, underlying, strategy_label, status,
                             source_chain_id, opening_date, closing_date)
                        VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?)
                    """, (group_id, lots[0].account_number, lots[0].underlying,
                          chain_info[0] if chain_info else None,
                          chain_id,
                          chain_info[1] if chain_info else None,
                          chain_info[2] if chain_info else None))

                for lot in lots:
                    cursor.execute("""
                        INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                        VALUES (?, ?)
                    """, (group_id, lot.transaction_id))
                    assigned += 1
            else:
                # No chain_id — add to ungrouped bucket per underlying/account
                buckets: Dict[str, list] = {}
                for lot in lots:
                    key = f"{lot.account_number}|{lot.underlying}"
                    buckets.setdefault(key, []).append(lot)

                for key, blots in buckets.items():
                    acct, und = key.split('|', 1)
                    # Find or create ungrouped group
                    cursor.execute("""
                        SELECT group_id FROM position_groups
                        WHERE account_number = ? AND underlying = ? AND source_chain_id IS NULL
                        AND strategy_label = 'Ungrouped'
                    """, (acct, und))
                    row = cursor.fetchone()
                    if row:
                        group_id = row[0]
                    else:
                        group_id = str(_uuid.uuid4())
                        cursor.execute("""
                            INSERT INTO position_groups
                                (group_id, account_number, underlying, strategy_label, status,
                                 source_chain_id, opening_date, closing_date)
                            VALUES (?, ?, ?, 'Ungrouped', 'OPEN', NULL, NULL, NULL)
                        """, (group_id, acct, und))

                    for lot in blots:
                        cursor.execute("""
                            INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                            VALUES (?, ?)
                        """, (group_id, lot.transaction_id))
                        assigned += 1

        # Update group statuses/dates for affected groups
        _refresh_all_group_statuses(cursor)
        conn.commit()

    logger.info(f"Seeded {assigned} new lots into position groups")
    return assigned


def _reconcile_stale_groups():
    """Update position_groups whose source_chain_id no longer exists in order_chains.

    For groups with lots from multiple chains (e.g. user moved lots on Ledger),
    set source_chain_id to the earliest lot's chain_id as a best-effort match
    for future seeding.
    """
    reconciled = 0
    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Fix stale source_chain_id references
        cursor.execute("""
            SELECT pg.group_id, pg.source_chain_id
            FROM position_groups pg
            LEFT JOIN order_chains oc ON pg.source_chain_id = oc.chain_id
            WHERE pg.source_chain_id IS NOT NULL AND oc.chain_id IS NULL
        """)
        stale_groups = cursor.fetchall()
        for stale_row in stale_groups:
            stale_gid = stale_row[0]
            # Find the actual chain_id(s) from the group's lots
            cursor.execute("""
                SELECT DISTINCT pl.chain_id
                FROM position_group_lots pgl
                JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
                WHERE pgl.group_id = ? AND pl.chain_id IS NOT NULL
                ORDER BY pl.entry_date ASC
            """, (stale_gid,))
            chain_rows = cursor.fetchall()
            if chain_rows:
                # Use the earliest lot's chain_id (best-effort for future seeding)
                new_chain_id = chain_rows[0][0]
                cursor.execute("""
                    SELECT underlying, strategy_type, opening_date, closing_date, chain_status
                    FROM order_chains WHERE chain_id = ?
                """, (new_chain_id,))
                chain_info = cursor.fetchone()
                if chain_info:
                    cursor.execute("""
                        UPDATE position_groups
                        SET source_chain_id = ?, underlying = ?, strategy_label = ?,
                            opening_date = ?, closing_date = ?, status = ?
                        WHERE group_id = ?
                    """, (new_chain_id, chain_info[0], chain_info[1],
                          chain_info[2], chain_info[3], chain_info[4], stale_gid))
                    reconciled += 1
                    logger.info(f"Reconciled stale group {stale_gid}: "
                                f"{stale_row[1]} -> {new_chain_id} ({chain_info[0]})")

        conn.commit()
    if reconciled:
        logger.info(f"Reconciled {reconciled} stale position groups")
    return reconciled


def _refresh_group_status(cursor, group_id: str):
    """Recalculate status, opening_date, closing_date for a single group."""
    cursor.execute("""
        SELECT COUNT(*) FROM position_group_lots pgl
        JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
        WHERE pgl.group_id = ? AND pl.remaining_quantity != 0 AND pl.status != 'CLOSED'
    """, (group_id,))
    open_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM position_group_lots WHERE group_id = ?
    """, (group_id,))
    total_count = cursor.fetchone()[0]

    if total_count == 0:
        # Empty group — delete it
        cursor.execute("DELETE FROM position_groups WHERE group_id = ?", (group_id,))
        return

    status = 'OPEN' if open_count > 0 else 'CLOSED'

    cursor.execute("""
        SELECT MIN(pl.entry_date) FROM position_group_lots pgl
        JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
        WHERE pgl.group_id = ?
    """, (group_id,))
    opening_date = cursor.fetchone()[0]

    closing_date = None
    if status == 'CLOSED':
        cursor.execute("""
            SELECT MAX(lc.closing_date) FROM lot_closings lc
            JOIN position_lots pl ON lc.lot_id = pl.id
            JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
            WHERE pgl.group_id = ?
        """, (group_id,))
        r = cursor.fetchone()
        closing_date = r[0] if r else None

    cursor.execute("""
        UPDATE position_groups
        SET status = ?, opening_date = ?, closing_date = ?, updated_at = CURRENT_TIMESTAMP
        WHERE group_id = ?
    """, (status, opening_date, closing_date, group_id))


def _refresh_all_group_statuses(cursor):
    """Recalculate status for all groups."""
    cursor.execute("SELECT group_id FROM position_groups")
    for row in cursor.fetchall():
        _refresh_group_status(cursor, row[0])


@app.get("/api/ledger")
async def get_ledger(account_number: str = '', underlying: str = ''):
    """Main Ledger data endpoint — returns position groups with lots and derived orders."""
    import json as _json

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Auto-seed if position_groups is empty
        cursor.execute("SELECT COUNT(*) FROM position_groups")
        if cursor.fetchone()[0] == 0:
            # Check if there are any lots to seed from
            cursor.execute("SELECT COUNT(*) FROM position_lots")
            if cursor.fetchone()[0] > 0:
                seed_position_groups()

    # Query groups with filters
    query = "SELECT * FROM position_groups WHERE 1=1"
    params = []
    if account_number:
        query += " AND account_number = ?"
        params.append(account_number)
    if underlying:
        query += " AND underlying = ?"
        params.append(underlying)
    query += " ORDER BY underlying ASC, opening_date DESC"

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        groups_raw = [dict(row) for row in cursor.fetchall()]

    if not groups_raw:
        return []

    group_ids = [g['group_id'] for g in groups_raw]

    # Batch-load lots
    lots_by_group = lot_manager.get_lots_for_groups_batch(group_ids)

    # Collect all lot IDs for batch closing load
    all_lot_ids = []
    for lots in lots_by_group.values():
        for lot in lots:
            all_lot_ids.append(lot.id)

    closings_by_lot = lot_manager.get_lot_closings_batch(all_lot_ids) if all_lot_ids else {}

    # Collect all order_ids to derive orders per group
    # and fetch order_data from order_chain_cache
    all_order_ids = set()
    group_order_ids: Dict[str, set] = {gid: set() for gid in group_ids}

    for gid, lots in lots_by_group.items():
        for lot in lots:
            if lot.opening_order_id:
                all_order_ids.add(lot.opening_order_id)
                group_order_ids[gid].add(lot.opening_order_id)
            # Also collect closing order_ids
            for closing in closings_by_lot.get(lot.id, []):
                if closing.closing_order_id:
                    all_order_ids.add(closing.closing_order_id)
                    group_order_ids[gid].add(closing.closing_order_id)

    # Fetch order data from cache
    order_cache: Dict[str, Dict] = {}
    if all_order_ids:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            oid_list = list(all_order_ids)
            placeholders = ','.join(['?' for _ in oid_list])
            cursor.execute(f"""
                SELECT order_id, order_data FROM order_chain_cache
                WHERE order_id IN ({placeholders})
            """, oid_list)
            for row in cursor.fetchall():
                try:
                    order_cache[row[0]] = _json.loads(row[1])
                except:
                    pass

    # Build response
    result = []
    for g in groups_raw:
        gid = g['group_id']
        lots = lots_by_group.get(gid, [])

        # Build lots response with closings
        lots_data = []
        total_realized = 0.0
        open_lot_count = 0

        for lot in lots:
            lot_closings = closings_by_lot.get(lot.id, [])
            lot_realized = sum(c.realized_pnl for c in lot_closings)
            total_realized += lot_realized

            multiplier = 100 if lot.option_type else 1
            cost_basis = abs(lot.entry_price * lot.original_quantity * multiplier)

            is_open = lot.remaining_quantity != 0 and lot.status != 'CLOSED'
            if is_open:
                open_lot_count += 1

            closings_data = []
            for c in lot_closings:
                closings_data.append({
                    'closing_id': c.closing_id,
                    'quantity_closed': c.quantity_closed,
                    'closing_price': c.closing_price,
                    'closing_date': str(c.closing_date) if c.closing_date else None,
                    'closing_type': c.closing_type,
                    'realized_pnl': c.realized_pnl,
                })

            lots_data.append({
                'lot_id': lot.id,
                'transaction_id': lot.transaction_id,
                'symbol': lot.symbol,
                'underlying': lot.underlying,
                'instrument_type': lot.instrument_type,
                'option_type': lot.option_type,
                'strike': lot.strike,
                'expiration': str(lot.expiration) if lot.expiration else None,
                'quantity': lot.quantity,
                'entry_price': lot.entry_price,
                'entry_date': str(lot.entry_date) if lot.entry_date else None,
                'remaining_quantity': lot.remaining_quantity,
                'original_quantity': lot.original_quantity,
                'status': lot.status,
                'leg_index': lot.leg_index,
                'derived_from_lot_id': lot.derived_from_lot_id,
                'derivation_type': lot.derivation_type,
                'cost_basis': cost_basis,
                'realized_pnl': lot_realized,
                'total_pnl': lot_realized,  # No unrealized calc here — frontend uses live quotes
                'closings': closings_data,
            })

        # Build orders for Action view
        orders_data = []
        for oid in sorted(group_order_ids.get(gid, []),
                          key=lambda x: order_cache.get(x, {}).get('order_date', ''),
                          reverse=True):
            if oid in order_cache:
                orders_data.append(order_cache[oid])

        result.append({
            'group_id': gid,
            'underlying': g['underlying'],
            'strategy_label': g['strategy_label'],
            'status': g['status'],
            'account_number': g['account_number'],
            'opening_date': g['opening_date'],
            'closing_date': g['closing_date'],
            'source_chain_id': g['source_chain_id'],
            'total_pnl': total_realized,
            'realized_pnl': total_realized,
            'unrealized_pnl': 0.0,
            'lot_count': len(lots),
            'open_lot_count': open_lot_count,
            'lots': lots_data,
            'orders': orders_data,
        })

    return result


@app.post("/api/ledger/seed")
async def seed_ledger():
    """Explicitly seed position groups from existing chains."""
    count = seed_position_groups()
    return {"message": f"Seeded {count} position groups", "groups_created": count}


@app.put("/api/ledger/groups/{group_id}")
async def update_ledger_group(group_id: str, body: LedgerGroupUpdate):
    """Update group metadata (strategy label)."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT group_id FROM position_groups WHERE group_id = ?", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Group not found")

        updates = []
        params = []
        if body.strategy_label is not None:
            updates.append("strategy_label = ?")
            params.append(body.strategy_label)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(group_id)
            cursor.execute(
                f"UPDATE position_groups SET {', '.join(updates)} WHERE group_id = ?",
                params
            )

    return {"message": "Group updated"}


@app.post("/api/ledger/move-lots")
async def move_lots(body: LedgerMoveLots):
    """Move lots between position groups. All lots and target must share underlying + account."""
    if not body.transaction_ids:
        raise HTTPException(status_code=400, detail="No transaction_ids provided")

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Validate target group exists
        cursor.execute(
            "SELECT account_number, underlying FROM position_groups WHERE group_id = ?",
            (body.target_group_id,)
        )
        target = cursor.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Target group not found")
        target_account, target_underlying = target

        # Validate all lots share same account/underlying as target
        placeholders = ','.join(['?' for _ in body.transaction_ids])
        cursor.execute(f"""
            SELECT DISTINCT pl.account_number, pl.underlying
            FROM position_lots pl
            WHERE pl.transaction_id IN ({placeholders})
        """, body.transaction_ids)
        lot_accounts = cursor.fetchall()

        for row in lot_accounts:
            if row[0] != target_account or (row[1] or '') != (target_underlying or ''):
                raise HTTPException(
                    status_code=400,
                    detail="All lots must share the same underlying and account as the target group"
                )

        # Find affected source groups before moving
        cursor.execute(f"""
            SELECT DISTINCT group_id FROM position_group_lots
            WHERE transaction_id IN ({placeholders})
        """, body.transaction_ids)
        source_groups = [row[0] for row in cursor.fetchall()]

        # Remove from current groups
        cursor.execute(f"""
            DELETE FROM position_group_lots
            WHERE transaction_id IN ({placeholders})
        """, body.transaction_ids)

        # Insert into target group
        for txn_id in body.transaction_ids:
            cursor.execute("""
                INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
                VALUES (?, ?)
            """, (body.target_group_id, txn_id))

        # Refresh status for all affected groups
        all_affected = set(source_groups + [body.target_group_id])
        for gid in all_affected:
            _refresh_group_status(cursor, gid)

        conn.commit()

    return {"message": f"Moved {len(body.transaction_ids)} lots"}


@app.post("/api/ledger/groups")
async def create_ledger_group(body: LedgerCreateGroup):
    """Create a new empty position group."""
    import uuid as _uuid
    group_id = str(_uuid.uuid4())

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO position_groups
                (group_id, account_number, underlying, strategy_label, status)
            VALUES (?, ?, ?, ?, 'OPEN')
        """, (group_id, body.account_number, body.underlying, body.strategy_label))

    return {"group_id": group_id, "message": "Group created"}


@app.delete("/api/ledger/groups/{group_id}")
async def delete_ledger_group(group_id: str):
    """Delete a group. Orphaned lots become unassigned (picked up by next seed)."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT group_id FROM position_groups WHERE group_id = ?", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Group not found")

        # CASCADE will delete position_group_lots rows
        cursor.execute("DELETE FROM position_groups WHERE group_id = ?", (group_id,))

    return {"message": "Group deleted"}


@app.get("/api/health")
async def health_check():
    """Simple health check endpoint"""
    return {"status": "ok", "service": "OptionLedger"}


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
    """Get open position groups for the Positions page — position_groups as single source of truth.

    Returns groups by account_number with:
    - Each group's realized_pnl, cost_basis_total, roll_count
    - open_legs: currently open option legs (from lots with remaining_quantity != 0)
    - shares: equity positions separated out per underlying
    """
    import json as _json

    try:
        # Auto-seed position_groups if empty (same guard as /api/ledger)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM position_groups")
            if cursor.fetchone()[0] == 0:
                cursor.execute("SELECT COUNT(*) FROM position_lots")
                if cursor.fetchone()[0] > 0:
                    seed_position_groups()

        # Query open position groups
        query = "SELECT * FROM position_groups WHERE status IN ('OPEN', 'ASSIGNED')"
        params = []
        if account_number and account_number != '':
            query += " AND account_number = ?"
            params.append(account_number)
        query += " ORDER BY underlying ASC, opening_date DESC"

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            groups_raw = [dict(row) for row in cursor.fetchall()]

        if not groups_raw:
            # Still need to check for equity positions even with no option groups
            result = {}
        else:
            group_ids = [g['group_id'] for g in groups_raw]

            # Batch-load lots for all groups
            lots_by_group = lot_manager.get_lots_for_groups_batch(group_ids)

            # Batch-load closings for all lots
            all_lot_ids = []
            for lots in lots_by_group.values():
                for lot in lots:
                    all_lot_ids.append(lot.id)
            closings_by_lot = lot_manager.get_lot_closings_batch(all_lot_ids) if all_lot_ids else {}

            # Batch-load order data from cache for roll_count/order_count
            all_order_ids = set()
            group_order_ids: Dict[str, set] = {gid: set() for gid in group_ids}
            for gid, lots in lots_by_group.items():
                for lot in lots:
                    if lot.opening_order_id:
                        all_order_ids.add(lot.opening_order_id)
                        group_order_ids[gid].add(lot.opening_order_id)
                    for closing in closings_by_lot.get(lot.id, []):
                        if closing.closing_order_id:
                            all_order_ids.add(closing.closing_order_id)
                            group_order_ids[gid].add(closing.closing_order_id)

            order_cache: Dict[str, Dict] = {}
            if all_order_ids:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    oid_list = list(all_order_ids)
                    placeholders = ','.join(['?' for _ in oid_list])
                    cursor.execute(f"""
                        SELECT order_id, order_data FROM order_chain_cache
                        WHERE order_id IN ({placeholders})
                    """, oid_list)
                    for row in cursor.fetchall():
                        try:
                            order_cache[row[0]] = _json.loads(row[1])
                        except Exception:
                            pass

            result = {}  # account_number -> { chains: [...], shares: {...} }

            for g in groups_raw:
                gid = g['group_id']
                acct = g['account_number']

                if acct not in result:
                    result[acct] = {"chains": [], "shares": {}}

                lots = lots_by_group.get(gid, [])

                # Build open_legs from lots with remaining_quantity != 0 and option instrument
                open_option_legs = []
                cost_basis_total = 0.0
                realized_pnl = 0.0
                has_assignment = False

                for lot in lots:
                    lot_closings = closings_by_lot.get(lot.id, [])
                    lot_realized = sum(c.realized_pnl for c in lot_closings)
                    realized_pnl += lot_realized

                    # Check for assignment/exercise closings
                    for c in lot_closings:
                        if c.closing_type in ('ASSIGNMENT', 'EXERCISE'):
                            has_assignment = True

                    # Check derived lots for assignment
                    if lot.derivation_type in ('ASSIGNMENT', 'EXERCISE'):
                        has_assignment = True

                    multiplier = 100 if lot.instrument_type == 'EQUITY_OPTION' else 1

                    # Accumulate cost basis across all lots
                    # quantity < 0 = short (sold, credit), quantity > 0 = long (bought, debit)
                    if lot.entry_price and lot.original_quantity:
                        amount = abs(lot.entry_price) * abs(lot.original_quantity) * multiplier
                        if lot.quantity < 0:
                            cost_basis_total += amount  # credit received (sold)
                        else:
                            cost_basis_total -= amount  # debit paid (bought)

                    # Add closing cash flows to cost basis
                    for c in lot_closings:
                        if c.closing_price and c.quantity_closed:
                            c_amount = abs(c.closing_price) * abs(c.quantity_closed) * multiplier
                            if lot.quantity < 0:
                                # Closing a short = buying back (debit)
                                cost_basis_total -= c_amount
                            else:
                                # Closing a long = selling (credit)
                                cost_basis_total += c_amount

                    # Only include open option lots in open_legs
                    if (lot.remaining_quantity != 0 and lot.status != 'CLOSED'
                            and lot.instrument_type == 'EQUITY_OPTION'):
                        qty = abs(lot.remaining_quantity)
                        # quantity < 0 = short position
                        qty_direction = 'Short' if lot.quantity < 0 else 'Long'
                        price = abs(lot.entry_price)
                        leg_amount = price * qty * 100 if price else 0
                        leg_cost = leg_amount if qty_direction == 'Short' else -leg_amount

                        open_option_legs.append({
                            "symbol": lot.symbol,
                            "underlying": lot.underlying or g['underlying'],
                            "instrument_type": lot.instrument_type,
                            "option_type": lot.option_type,
                            "strike": lot.strike,
                            "expiration": str(lot.expiration) if lot.expiration else None,
                            "quantity": qty,
                            "quantity_direction": qty_direction,
                            "opening_price": price,
                            "cost_basis": leg_cost,
                            "lot_id": lot.id,
                        })

                # Derive roll_count and order_count from cached orders
                roll_count = 0
                order_ids = group_order_ids.get(gid, set())
                for oid in order_ids:
                    od = order_cache.get(oid, {})
                    if od.get('order_type') == 'ROLLING':
                        roll_count += 1

                # Build group object for frontend (response shape matches old chain format)
                group_obj = {
                    "chain_id": gid,  # alias group_id as chain_id for frontend compat
                    "group_id": gid,
                    "source_chain_id": g.get('source_chain_id'),
                    "underlying": g['underlying'],
                    "account_number": acct,
                    "strategy_type": g['strategy_label'] or 'Unknown',
                    "opening_date": g['opening_date'],
                    "chain_status": g['status'],
                    "realized_pnl": realized_pnl,
                    "cost_basis_total": cost_basis_total,
                    "roll_count": roll_count,
                    "order_count": len(order_ids),
                    "has_assignment": has_assignment,
                    "open_legs": open_option_legs,
                }
                # Only include groups that have open option legs
                if open_option_legs:
                    result[acct]["chains"].append(group_obj)

        # Source equity positions from TT API positions table (reliable for shares)
        tt_positions = db.get_open_positions()
        for pos in tt_positions:
            instrument = pos.get('instrument_type', '')
            if 'OPTION' in instrument.upper():
                continue
            if 'EQUITY' not in instrument.upper():
                continue

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

        logger.info(f"/api/open-chains: Returning {sum(len(a['chains']) for a in result.values())} groups, {sum(len(a['shares']) for a in result.values())} equity groups across {len(result)} accounts")
        return result

    except Exception as e:
        logger.error(f"Error in /api/open-chains: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def reconcile_positions_vs_chains():
    """Compare TT API positions against position_lots-derived open legs.

    Returns a summary with categories:
    - MATCHED: symbol+account+quantity agree
    - QUANTITY_MISMATCH: same symbol but different quantity
    - UNLINKED: TT has position, lots don't
    - STALE: lots say open but TT doesn't have it (auto-closes stale lots and groups)
    """
    from datetime import date as _date

    try:
        # 1. Get TT API positions (from positions table)
        tt_positions = db.get_open_positions()
        tt_by_key = {}
        for pos in tt_positions:
            key = (pos.get('account_number', ''), (pos.get('symbol') or '').strip())
            tt_by_key[key] = pos

        # 2. Get open option legs from position_lots (single query, no per-chain iteration)
        lot_legs_by_key = {}  # (account, symbol) -> { quantity, group_id }
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pl.account_number, pl.symbol, pl.underlying,
                       SUM(pl.remaining_quantity) as net_qty,
                       pgl.group_id
                FROM position_lots pl
                LEFT JOIN position_group_lots pgl ON pl.transaction_id = pgl.transaction_id
                WHERE pl.remaining_quantity != 0 AND pl.status != 'CLOSED'
                  AND pl.instrument_type = 'EQUITY_OPTION'
                GROUP BY pl.account_number, pl.symbol
            """)
            for row in cursor.fetchall():
                acct = row[0]
                symbol = (row[1] or '').strip()
                net_qty = row[3]
                if net_qty != 0:
                    key = (acct, symbol)
                    lot_legs_by_key[key] = {
                        'quantity': net_qty,
                        'group_id': row[4],
                        'underlying': row[2],
                    }

        # 3. Reconcile
        matched = 0
        quantity_mismatch = []
        unlinked = []
        stale = []
        today = _date.today()

        all_lot_keys = set(lot_legs_by_key.keys())
        all_tt_keys = set(tt_by_key.keys())

        for key in all_tt_keys:
            acct, symbol = key
            tt_pos = tt_by_key[key]
            instrument = tt_pos.get('instrument_type', '').upper()
            if 'OPTION' not in instrument:
                continue

            tt_qty = tt_pos.get('quantity', 0)
            if tt_pos.get('quantity_direction') == 'Short':
                tt_signed = -abs(tt_qty)
            else:
                tt_signed = abs(tt_qty)

            if key in lot_legs_by_key:
                lot_data = lot_legs_by_key[key]
                if lot_data['quantity'] == tt_signed:
                    matched += 1
                else:
                    quantity_mismatch.append({
                        'symbol': symbol,
                        'account': acct,
                        'tt_quantity': tt_signed,
                        'chain_quantity': lot_data['quantity'],
                        'chain_id': lot_data.get('group_id', ''),
                    })
            else:
                unlinked.append({
                    'symbol': symbol,
                    'account': acct,
                    'quantity': tt_signed,
                    'instrument_type': tt_pos.get('instrument_type', ''),
                    'underlying': tt_pos.get('underlying', ''),
                })

        # Check lot legs that TT doesn't have (stale)
        for key in all_lot_keys - all_tt_keys:
            acct, symbol = key
            lot_data = lot_legs_by_key.get(key, {})
            stale.append({
                'symbol': symbol,
                'account': acct,
                'chain_quantity': lot_data.get('quantity', 0),
                'chain_id': lot_data.get('group_id', ''),
            })

        # Auto-close stale lots: close position_lots and refresh affected groups
        auto_closed = []
        if stale:
            # Collect group_ids that have at least one matched leg
            matched_group_ids = set()
            for key in all_lot_keys & all_tt_keys:
                ld = lot_legs_by_key.get(key, {})
                if ld.get('group_id'):
                    matched_group_ids.add(ld['group_id'])

            stale_group_ids = set(s['chain_id'] for s in stale if s.get('chain_id'))
            affected_groups = set()

            for group_id in stale_group_ids - matched_group_ids:
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        # Close stale lots in this group
                        cursor.execute("""
                            UPDATE position_lots SET remaining_quantity = 0, status = 'CLOSED'
                            WHERE transaction_id IN (
                                SELECT pgl.transaction_id FROM position_group_lots pgl
                                JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
                                WHERE pgl.group_id = ? AND pl.remaining_quantity != 0
                                  AND pl.status != 'CLOSED' AND pl.instrument_type = 'EQUITY_OPTION'
                            )
                        """, (group_id,))
                        if cursor.rowcount > 0:
                            auto_closed.append(group_id)
                            affected_groups.add(group_id)
                            logger.info(f"Auto-closed stale lots in group {group_id}")
                        conn.commit()
                except Exception as e:
                    logger.error(f"Failed to auto-close lots in group {group_id}: {e}")

            # Refresh status for affected groups
            if affected_groups:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    for gid in affected_groups:
                        _refresh_group_status(cursor, gid)
                    conn.commit()

        # Pass 2: Ghost groups — OPEN with no remaining lots and no TT positions
        tt_underlyings_by_acct = {}
        for pos in tt_positions:
            acct = pos.get('account_number', '')
            und = (pos.get('underlying') or pos.get('symbol', '')).strip()
            tt_underlyings_by_acct.setdefault(acct, set()).add(und)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pg.group_id, pg.account_number, pg.underlying
                FROM position_groups pg
                WHERE pg.status IN ('OPEN', 'ASSIGNED')
            """)
            open_groups = cursor.fetchall()

            for row in open_groups:
                group_id, acct, underlying = row[0], row[1], row[2]
                if group_id in set(auto_closed):
                    continue

                # Check if group has any open option lots
                cursor.execute("""
                    SELECT COUNT(*) FROM position_group_lots pgl
                    JOIN position_lots pl ON pgl.transaction_id = pl.transaction_id
                    WHERE pgl.group_id = ? AND pl.remaining_quantity != 0
                      AND pl.status != 'CLOSED' AND pl.instrument_type = 'EQUITY_OPTION'
                """, (group_id,))
                has_open_lots = cursor.fetchone()[0] > 0

                if not has_open_lots:
                    tt_has_underlying = underlying in tt_underlyings_by_acct.get(acct, set())
                    if not tt_has_underlying:
                        _refresh_group_status(cursor, group_id)
                        auto_closed.append(group_id)
                        logger.info(f"Auto-closed ghost group {group_id} ({underlying}/{acct})")

            conn.commit()

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
                if use_incremental and affected_underlyings:
                    lot_manager.clear_all_lots(underlyings=affected_underlyings)
                    logger.info(f"Cleared position inventory and lots for {len(affected_underlyings)} affected underlyings")
                else:
                    lot_manager.clear_all_lots()
                    logger.info("Cleared position inventory and lots for full reprocessing")

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
                        seed_new_lots_into_groups()
                        _reconcile_stale_groups()
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
            seed_new_lots_into_groups()
            _reconcile_stale_groups()
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

        # Assign new lots into position groups
        seed_new_lots_into_groups()

        # Update groups whose source chain changed (e.g. symbol changes)
        _reconcile_stale_groups()

        return {
            "message": "Reprocessing completed successfully",
            "orders_processed": len(raw_transactions),
            "orders_saved": len(raw_transactions),
            "chains_created": len(all_chains),
            "chains_saved": len(all_chains),
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








if __name__ == "__main__":
    logger.info("Starting OptionLedger on http://localhost:8000")
    logger.info("From Windows, also try: http://127.0.0.1:8000")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
# END OF FILE
