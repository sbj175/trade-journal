"""OAuth2 Authorization Code flow for Tastytrade onboarding.

Provides three endpoints:
  POST /api/auth/tastytrade/authorize  — builds authorization URL (requires JWT)
  GET  /auth/tastytrade/callback       — receives code from Tastytrade (public)
  POST /api/auth/tastytrade/disconnect — removes credentials (requires JWT)
"""

import json
import os
import time
from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from loguru import logger

from src.dependencies import (
    AUTH_ENABLED,
    db,
    connection_manager,
    get_current_user_id,
)
from src.utils.credential_encryption import encrypt_credential, decrypt_credential

router = APIRouter()

# Tastytrade OAuth endpoints
TASTYTRADE_AUTH_URL = "https://my.tastytrade.com/auth.html"
TASTYTRADE_TOKEN_URL = "https://api.tastyworks.com/oauth/token"

# State token max age (seconds)
STATE_MAX_AGE = 600  # 10 minutes


def _get_oauth_config() -> dict:
    """Read OAuth app config from environment."""
    client_id = os.getenv("TASTYTRADE_CLIENT_ID", "")
    client_secret = os.getenv(
        "TASTYTRADE_CLIENT_SECRET",
        os.getenv("TASTYTRADE_PROVIDER_SECRET", ""),
    )
    redirect_uri = os.getenv(
        "TASTYTRADE_REDIRECT_URI",
        "http://localhost:8000/auth/tastytrade/callback",
    )
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def _build_state(user_id: str) -> str:
    """Encrypt user_id + timestamp into a Fernet state token."""
    payload = json.dumps({"user_id": user_id, "ts": time.time()})
    return encrypt_credential(payload)


def _decode_state(state: str) -> dict:
    """Decrypt and validate a state token. Returns payload dict or raises."""
    try:
        payload = json.loads(decrypt_credential(state))
    except Exception as e:
        raise ValueError(f"Invalid state token: {e}")

    age = time.time() - payload.get("ts", 0)
    if age > STATE_MAX_AGE:
        raise ValueError(f"State token expired ({int(age)}s old, max {STATE_MAX_AGE}s)")

    if not payload.get("user_id"):
        raise ValueError("State token missing user_id")

    return payload


@router.post("/api/auth/tastytrade/authorize")
async def tastytrade_authorize(user_id: str = Depends(get_current_user_id)):
    """Build Tastytrade authorization URL and return it to the frontend."""
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="OAuth flow only available in multi-user mode",
        )

    cfg = _get_oauth_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=500,
            detail="TASTYTRADE_CLIENT_ID and TASTYTRADE_CLIENT_SECRET must be configured",
        )

    state = _build_state(user_id)

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "read",
        "state": state,
    }
    authorization_url = f"{TASTYTRADE_AUTH_URL}?{urlencode(params)}"

    logger.info(f"Generated Tastytrade auth URL for user {user_id[:8]}...")
    return {"authorization_url": authorization_url}


@router.get("/auth/tastytrade/callback")
async def tastytrade_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Handle the redirect from Tastytrade after user authorizes.

    This is a PUBLIC endpoint (no JWT) because the browser is redirected here
    by Tastytrade. The state parameter carries the encrypted user_id.
    """
    settings_error_url = "/settings?tab=connection"

    # Handle authorization denial
    if error:
        logger.warning(f"Tastytrade OAuth denied: {error}")
        return RedirectResponse(
            url=f"{settings_error_url}&error={error}",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings_error_url}&error=Missing+code+or+state+parameter",
            status_code=302,
        )

    # Decrypt and validate state
    try:
        payload = _decode_state(state)
    except ValueError as e:
        logger.warning(f"State validation failed: {e}")
        return RedirectResponse(
            url=f"{settings_error_url}&error=Invalid+or+expired+state.+Please+try+again.",
            status_code=302,
        )

    user_id = payload["user_id"]
    cfg = _get_oauth_config()

    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_resp = await client.post(
                TASTYTRADE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "redirect_uri": cfg["redirect_uri"],
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_resp.status_code != 200:
            body = token_resp.text[:200]
            logger.error(f"Token exchange failed ({token_resp.status_code}): {body}")
            return RedirectResponse(
                url=f"{settings_error_url}&error=Token+exchange+failed.+Please+try+again.",
                status_code=302,
            )

        token_data = token_resp.json()
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            logger.error(f"No refresh_token in token response: {list(token_data.keys())}")
            return RedirectResponse(
                url=f"{settings_error_url}&error=No+refresh+token+received.+Please+try+again.",
                status_code=302,
            )

    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return RedirectResponse(
            url=f"{settings_error_url}&error=Connection+error+during+token+exchange.",
            status_code=302,
        )

    # Store the refresh token (encrypted) in user_credentials.
    # provider_secret is NULL — we use the app-level client_secret from env.
    try:
        from src.database.models import UserCredential
        from src.database.engine import dialect_insert

        enc_token = encrypt_credential(refresh_token)
        now = datetime.now().isoformat()

        with db.get_session(user_id=user_id) as session:
            stmt = dialect_insert(UserCredential).values(
                user_id=user_id,
                provider="tastytrade",
                encrypted_provider_secret=None,
                encrypted_refresh_token=enc_token,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            if session.bind.dialect.name == "sqlite":
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id", "provider"],
                    set_={
                        "encrypted_provider_secret": None,
                        "encrypted_refresh_token": enc_token,
                        "is_active": True,
                        "updated_at": now,
                    },
                )
            else:
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_user_credentials_user_provider",
                    set_={
                        "encrypted_provider_secret": None,
                        "encrypted_refresh_token": enc_token,
                        "is_active": True,
                        "updated_at": now,
                    },
                )
            session.execute(stmt)

        # Clear any cached connection so next request picks up the new token
        connection_manager.disconnect_user(user_id)
        logger.info(f"OAuth callback: stored refresh token for user {user_id[:8]}...")

    except Exception as e:
        logger.error(f"Failed to store credentials for user {user_id[:8]}...: {e}")
        return RedirectResponse(
            url=f"{settings_error_url}&error=Failed+to+save+credentials.",
            status_code=302,
        )

    # Success — send user to positions page
    return RedirectResponse(url="/positions", status_code=302)


@router.post("/api/auth/tastytrade/disconnect")
async def tastytrade_disconnect(user_id: str = Depends(get_current_user_id)):
    """Remove Tastytrade credentials and disconnect."""
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Disconnect only available in multi-user mode",
        )

    try:
        from src.database.models import UserCredential

        with db.get_session(user_id=user_id) as session:
            deleted = session.query(UserCredential).filter(
                UserCredential.provider == "tastytrade",
            ).delete()

        connection_manager.disconnect_user(user_id)
        logger.info(f"Disconnected Tastytrade for user {user_id[:8]}... ({deleted} row(s))")
        return {"message": "Tastytrade disconnected"}
    except Exception as e:
        logger.error(f"Failed to disconnect: {e}")
        raise HTTPException(status_code=500, detail=str(e))
