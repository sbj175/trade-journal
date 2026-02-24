"""Health check and connection status routes."""

from datetime import datetime
from fastapi import APIRouter, Depends

from src.dependencies import connection_manager, get_current_user_id, AUTH_ENABLED

router = APIRouter()


@router.get("/api/health")
async def health_check():
    """Simple health check endpoint"""
    return {"status": "ok", "service": "OptionLedger"}


@router.get("/health")
async def health_check_alt():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@router.get("/api/connection/status")
async def get_connection_status(user_id: str = Depends(get_current_user_id)):
    """Get Tastytrade connection status"""
    if AUTH_ENABLED:
        return connection_manager.get_user_status(user_id)
    return connection_manager.get_status()


@router.post("/api/connection/reconnect")
async def reconnect(user_id: str = Depends(get_current_user_id)):
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
