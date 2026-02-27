"""Auth routes — config endpoint, beta gate, and waitlist."""

import os
import logging

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr
from sqlalchemy import func

from src.database.engine import get_session
from src.database.models import User, WaitlistEntry
from src.dependencies import BETA_MAX_USERS

logger = logging.getLogger(__name__)

router = APIRouter()


def _count_supabase_users() -> int:
    """Count users that signed up via Supabase."""
    with get_session(unscoped=True) as session:
        return session.query(func.count(User.id)).filter(
            User.auth_provider == "supabase"
        ).scalar() or 0


@router.get("/api/auth/config")
async def get_auth_config():
    """Return public Supabase config for the frontend (no secrets).

    This endpoint is public — no auth required.
    """
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    auth_enabled = bool(supabase_url or os.getenv("SUPABASE_JWT_SECRET"))

    # Beta capacity info
    if BETA_MAX_USERS > 0:
        current = _count_supabase_users()
        beta_open = current < BETA_MAX_USERS
        beta_spots_remaining = max(0, BETA_MAX_USERS - current)
    else:
        beta_open = True
        beta_spots_remaining = None  # unlimited

    return {
        "auth_enabled": auth_enabled,
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_anon_key,
        "beta_max_users": BETA_MAX_USERS,
        "beta_open": beta_open,
        "beta_spots_remaining": beta_spots_remaining,
    }


# ── Waitlist ──────────────────────────────────────────────────────────────

class WaitlistRequest(BaseModel):
    email: str


@router.post("/api/waitlist")
async def join_waitlist(body: WaitlistRequest):
    """Submit an email to the beta waitlist (public endpoint)."""
    with get_session(unscoped=True) as session:
        existing = session.query(WaitlistEntry).filter(
            WaitlistEntry.email == body.email
        ).first()
        if existing:
            return {"status": "already_registered"}

        session.add(WaitlistEntry(email=body.email))

    return {"status": "ok"}


@router.get("/api/waitlist/count")
async def waitlist_count():
    """Return the number of waitlist entries (public endpoint)."""
    with get_session(unscoped=True) as session:
        count = session.query(func.count(WaitlistEntry.id)).scalar() or 0
    return {"count": count}
