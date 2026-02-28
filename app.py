#!/usr/bin/env python3

"""
OptionLedger Web Application
A beautiful, local web app for tracking and analyzing options trades
"""

import asyncio
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.dependencies import db, connection_manager, AUTH_ENABLED
from src.services.sync_service import background_auto_sync
from src.routers import (
    auth,
    health,
    pages,
    notes,
    settings,
    accounts,
    quotes,
    ledger,
    positions,
    sync,
    reports,
    debug,
    tags,
    tastytrade_oauth,
)

# Configure logging
import os
logger.remove()  # remove default stderr sink (DEBUG level)
logger.add(
    "logs/webapp_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
)
logger.add(
    lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO"),
    colorize=True,
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

# Create static directory if it doesn't exist
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
(static_dir / "css").mkdir(exist_ok=True)
(static_dir / "js").mkdir(exist_ok=True)
(static_dir / "images").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(health.router)
app.include_router(notes.router)
app.include_router(settings.router)
app.include_router(accounts.router)
app.include_router(quotes.router)
app.include_router(ledger.router)
app.include_router(positions.router)
app.include_router(sync.router)
app.include_router(reports.router)
app.include_router(debug.router)
app.include_router(tags.router)
app.include_router(tastytrade_oauth.router)


def _log_startup_banner():
    """Log a configuration summary banner at startup."""
    import os
    from src.database.engine import get_dialect

    dialect = get_dialect()
    db_backend = "PostgreSQL" if dialect == "postgresql" else "SQLite"

    auth_enabled = AUTH_ENABLED
    oauth_flow = bool(os.getenv("TASTYTRADE_CLIENT_ID"))
    encryption_key = bool(os.getenv("CREDENTIAL_ENCRYPTION_KEY"))

    # Single-user Tastytrade credentials (from .env)
    tt_env_creds = bool(
        os.getenv("TASTYTRADE_PROVIDER_SECRET")
        and os.getenv("TASTYTRADE_REFRESH_TOKEN")
    )

    lines = [
        "",
        "=" * 52,
        "  OptionLedger v1.0.0",
        "=" * 52,
        f"  Database           : {db_backend}",
        f"  Auth (Supabase)    : {'ENABLED' if auth_enabled else 'disabled'}",
        f"  OAuth2 flow        : {'configured' if oauth_flow else 'not configured'}",
        f"  Encryption key     : {'set' if encryption_key else 'auto-generated'}",
    ]

    if auth_enabled:
        lines.append(f"  Mode               : multi-user (per-user credentials)")
    else:
        lines.append(f"  TT credentials     : {'found in .env' if tt_env_creds else 'not configured'}")
        lines.append(f"  Mode               : single-user")

    lines.append("=" * 52)
    lines.append("")

    for line in lines:
        logger.info(line)


@app.on_event("startup")
async def startup_event():
    """Initialize database and connect to Tastytrade on startup"""
    logger.info("Starting OptionLedger Web App")
    db.initialize_database()
    _log_startup_banner()

    if AUTH_ENABLED:
        # Multi-user mode: each user connects on demand with their own credentials
        logger.info("Multi-user mode: per-user Tastytrade connections on demand")
        return

    # Single-user mode: auto-connect to Tastytrade using OAuth credentials from .env
    if connection_manager.is_configured():
        logger.info("OAuth credentials found, connecting to Tastytrade...")
        await connection_manager.connect()

        # Auto-sync if connected and it's been a while since last sync
        if connection_manager.connected:
            try:
                from datetime import datetime
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
