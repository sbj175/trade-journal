"""
OptionLedger Admin Dashboard — separate FastAPI process on port 8001.

Usage:
    ADMIN_SECRET=mysecret python admin_app.py
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from admin.dependencies import admin_db
from admin.middleware import AdminAuthMiddleware
from admin.routers import api, pages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _log_startup_banner():
    """Log a configuration summary banner at startup."""
    from src.database.engine import get_dialect

    dialect = get_dialect()
    db_backend = "PostgreSQL" if dialect == "postgresql" else "SQLite"
    secret_set = bool(os.environ.get("ADMIN_SECRET"))
    port = os.environ.get("APP_PORT", os.environ.get("ADMIN_PORT", "8001"))

    lines = [
        "",
        "=" * 52,
        "  OptionLedger Admin v1.0.0",
        "=" * 52,
        f"  Database           : {db_backend}",
        f"  Admin secret       : {'configured' if secret_set else 'NOT SET'}",
        f"  Port               : {port}",
        "=" * 52,
        "",
    ]
    for line in lines:
        logger.info(line)


@asynccontextmanager
async def lifespan(app: FastAPI):
    admin_db.initialize_database()
    _log_startup_banner()
    yield


app = FastAPI(title="OptionLedger Admin", version="1.0.0", lifespan=lifespan)

# Middleware (order matters — CORS first, then auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AdminAuthMiddleware)

# Static files
app.mount("/static", StaticFiles(directory="admin/static"), name="admin-static")

# Routers
app.include_router(pages.router)
app.include_router(api.router)


if __name__ == "__main__":
    port = int(os.environ.get("ADMIN_PORT", "8001"))
    uvicorn.run("admin_app:app", host="0.0.0.0", port=port)
