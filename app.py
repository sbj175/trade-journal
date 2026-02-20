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

from src.dependencies import db, connection_manager
from src.services.sync_service import background_auto_sync
from src.routers import (
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
)

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

# Create static directory if it doesn't exist
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
(static_dir / "css").mkdir(exist_ok=True)
(static_dir / "js").mkdir(exist_ok=True)
(static_dir / "images").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers
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
