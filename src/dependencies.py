"""Singleton instances shared across routers and services."""

import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates

from src.api.tastytrade_client import TastytradeClient

from src.database.db_manager import DatabaseManager
from src.database.tenant import DEFAULT_USER_ID, set_current_user_id
from src.models.order_models import OrderManager
from src.models.order_processor import OrderProcessor
from src.models.strategy_detector import StrategyDetector
from src.models.pnl_calculator import PnLCalculator
from src.models.lot_manager import LotManager
from src.utils.auth_manager import ConnectionManager

db = DatabaseManager(db_url=os.getenv("DATABASE_URL"))
order_manager = OrderManager(db)
lot_manager = LotManager(db)
order_processor = OrderProcessor(db, lot_manager)
strategy_detector = StrategyDetector(db)
pnl_calculator = PnLCalculator(db, lot_manager)
connection_manager = ConnectionManager()
templates = Jinja2Templates(directory="static")

# Auth is enabled when Supabase credentials are configured (URL for ES256, or legacy JWT secret for HS256)
AUTH_ENABLED = bool(os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_JWT_SECRET"))

# Beta capacity gate: 0 or absent = unlimited (no gate)
BETA_MAX_USERS = int(os.getenv("BETA_MAX_USERS", "0"))

# HTTPBearer with auto_error=False so we can handle missing tokens ourselves
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Extract and validate the authenticated user ID.

    When auth is disabled (no SUPABASE_JWT_SECRET), returns DEFAULT_USER_ID
    for full backward compatibility.

    When auth is enabled, validates the Supabase JWT and returns the user's
    UUID from the 'sub' claim. Also sets the contextvar so get_session()
    automatically scopes queries.
    """
    if not AUTH_ENABLED:
        set_current_user_id(DEFAULT_USER_ID)
        return DEFAULT_USER_ID

    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from src.auth.jwt_validator import validate_token, AuthError
    from src.auth.user_provisioning import ensure_user_exists, BetaFullError

    try:
        payload = validate_token(credentials.credentials)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    uid = payload["sub"]
    email = payload.get("email")

    try:
        ensure_user_exists(uid, email)
    except BetaFullError:
        raise HTTPException(status_code=403, detail="beta_full")

    set_current_user_id(uid)
    return uid


async def get_tastytrade_client(
    user_id: str = Depends(get_current_user_id),
) -> TastytradeClient:
    """Resolve the Tastytrade client for the current request.

    Auth disabled  → returns the global singleton from .env credentials.
    Auth enabled   → returns a per-user client from encrypted DB credentials.
    Raises 503 if no client is available.
    """
    if not AUTH_ENABLED:
        client = connection_manager.get_client()
    else:
        client = await connection_manager.get_user_client(user_id)

    if not client:
        raise HTTPException(
            status_code=503,
            detail="Tastytrade not connected. Configure credentials in Settings.",
        )
    return client
