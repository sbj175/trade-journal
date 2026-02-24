"""Health check and connection status routes."""

from datetime import datetime
from fastapi import APIRouter, Depends

from src.dependencies import connection_manager, get_current_user_id

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
    return connection_manager.get_status()


@router.post("/api/connection/reconnect")
async def reconnect(user_id: str = Depends(get_current_user_id)):
    """Force reconnection to Tastytrade (after .env update)"""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    success = await connection_manager.connect()
    return connection_manager.get_status()
