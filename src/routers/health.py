"""Health check and connection status routes."""

import time
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends
from loguru import logger

from src.utils.auth_manager import ConnectionManager
from src.dependencies import get_connection_manager, get_current_user_id, get_tastytrade_client, AUTH_ENABLED

router = APIRouter()

# In-memory cache for market status (shared across requests)
_market_status_cache = {"data": None, "expires_at": 0}


@router.get("/api/health")
async def health_check():
    """Simple health check endpoint"""
    return {"status": "ok", "service": "OptionLedger"}


@router.get("/health")
async def health_check_alt():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@router.get("/api/connection/status")
async def get_connection_status(connection_manager: ConnectionManager = Depends(get_connection_manager), user_id: str = Depends(get_current_user_id)):
    """Get Tastytrade connection status"""
    if AUTH_ENABLED:
        return connection_manager.get_user_status(user_id)
    return connection_manager.get_status()


@router.get("/api/market-status")
async def get_market_status(
    connection_manager: ConnectionManager = Depends(get_connection_manager),
    user_id: str = Depends(get_current_user_id),
):
    """Get current market session status from Tastytrade API."""
    from tastytrade.market_sessions import (
        ExchangeType, get_market_sessions,
    )

    now = time.time()
    if _market_status_cache["data"] and now < _market_status_cache["expires_at"]:
        return _market_status_cache["data"]

    # Resolve the client
    try:
        if AUTH_ENABLED:
            client = await connection_manager.get_user_client(user_id)
        else:
            client = connection_manager.get_client()
        if not client or not client.session:
            return {"connected": False, "sessions": []}
    except Exception:
        return {"connected": False, "sessions": []}

    try:
        exchanges = [ExchangeType.NYSE, ExchangeType.CFE]
        sessions = await get_market_sessions(client.session, exchanges)

        result = {
            "connected": True,
            "sessions": [],
        }
        for s in sessions:
            session_data = {
                "exchange": s.instrument_collection,
                "status": s.status.value,
                "open_at": s.open_at.isoformat() if s.open_at else None,
                "close_at": s.close_at.isoformat() if s.close_at else None,
                "close_at_ext": s.close_at_ext.isoformat() if s.close_at_ext else None,
                "start_at": s.start_at.isoformat() if s.start_at else None,
            }
            if s.next_session:
                # The SDK sometimes returns stale next_session dates (weekends/past).
                # Advance to the next weekday if the session_date is today or earlier.
                raw_date = s.next_session.session_date
                # Handle both date and datetime objects from SDK
                next_date = raw_date.date() if isinstance(raw_date, datetime) else raw_date
                today = date.today()
                logger.debug(f"Market next_session for {s.instrument_collection}: raw={raw_date} type={type(raw_date)} next_date={next_date} today={today}")
                if next_date <= today:
                    next_date = today + timedelta(days=1)
                # Skip weekends (5=Saturday, 6=Sunday)
                while next_date.weekday() in (5, 6):
                    next_date = next_date + timedelta(days=1)
                # Compute day offset to shift open/close times accordingly
                orig_date = raw_date.date() if isinstance(raw_date, datetime) else raw_date
                day_offset = next_date - orig_date
                session_data["next_session"] = {
                    "open_at": (s.next_session.open_at + day_offset).isoformat(),
                    "close_at": (s.next_session.close_at + day_offset).isoformat(),
                    "session_date": next_date.isoformat(),
                }
            result["sessions"].append(session_data)

        # Derive overall status from equity (NYSE) session
        equity = next((s for s in sessions if s.instrument_collection == "Equity"), None)
        result["overall_status"] = equity.status.value if equity else "Unknown"

        _market_status_cache["data"] = result
        _market_status_cache["expires_at"] = now + 60  # 60s cache

        return result
    except Exception as e:
        logger.error(f"Failed to fetch market sessions: {e}")
        return {"connected": True, "sessions": [], "overall_status": "Unknown", "error": str(e)}


@router.post("/api/connection/reconnect")
async def reconnect(connection_manager: ConnectionManager = Depends(get_connection_manager), user_id: str = Depends(get_current_user_id)):
    """Force reconnection to Tastytrade (after credential update)"""
    if AUTH_ENABLED:
        connection_manager.disconnect_user(user_id)
        client = await connection_manager.get_user_client(user_id)
        return connection_manager.get_user_status(user_id)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        await connection_manager.connect()
        return connection_manager.get_status()
