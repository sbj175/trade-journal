"""
Connection management for OptionEdge.

Manages a shared, app-level TastytradeClient that authenticates via OAuth2
on startup and is reused across all requests.
"""

import os
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from loguru import logger
from src.api.tastytrade_client import TastytradeClient

load_dotenv()


class ConnectionManager:
    """Manages a shared TastytradeClient singleton authenticated via OAuth2."""

    def __init__(self):
        self.client: Optional[TastytradeClient] = None
        self.connected: bool = False
        self.error: Optional[str] = None

    async def connect(self) -> bool:
        """Initialize and authenticate TastytradeClient from .env credentials."""
        try:
            self.client = TastytradeClient()
            self.connected = await self.client.authenticate()
            if not self.connected:
                self.error = "Failed to authenticate - check OAuth credentials in .env"
                logger.warning(self.error)
            else:
                self.error = None
                logger.info("ConnectionManager: successfully connected to Tastytrade")
            return self.connected
        except Exception as e:
            self.error = f"Connection error: {str(e)}"
            self.connected = False
            logger.error(self.error)
            return False

    def get_client(self) -> Optional[TastytradeClient]:
        """Get the shared authenticated client, or None if not connected."""
        return self.client if self.connected else None

    def is_configured(self) -> bool:
        """Check if OAuth credentials are present in .env."""
        return bool(os.getenv('TASTYTRADE_PROVIDER_SECRET') and
                     os.getenv('TASTYTRADE_REFRESH_TOKEN'))

    def get_status(self) -> Dict[str, Any]:
        """Return connection status info for API responses."""
        accounts = []
        if self.connected and self.client:
            accounts = self.client.get_all_accounts()
        return {
            'connected': self.connected,
            'configured': self.is_configured(),
            'error': self.error,
            'accounts': accounts,
        }
