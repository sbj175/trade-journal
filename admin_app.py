"""
OptionLedger Admin Dashboard — separate FastAPI process on port 8001.

Usage:
    ADMIN_SECRET=mysecret python admin_app.py
"""

import logging
import os
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    admin_db.initialize_database()
    secret = os.environ.get("ADMIN_SECRET", "")
    if not secret:
        logger.warning("ADMIN_SECRET not set — all API requests will be rejected")
    else:
        logger.info("Admin dashboard ready (ADMIN_SECRET configured)")
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
