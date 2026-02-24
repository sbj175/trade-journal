"""Auth routes — config endpoint and connection status."""

import os
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/auth/config")
async def get_auth_config():
    """Return public Supabase config for the frontend (no secrets).

    This endpoint is public — no auth required.
    """
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    auth_enabled = bool(supabase_url or os.getenv("SUPABASE_JWT_SECRET"))

    return {
        "auth_enabled": auth_enabled,
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_anon_key,
    }
