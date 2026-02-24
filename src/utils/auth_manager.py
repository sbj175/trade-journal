"""
Connection management for OptionLedger.

Manages a shared, app-level TastytradeClient that authenticates via OAuth2
on startup and is reused across all requests.

When AUTH_ENABLED (multi-user mode), also maintains a per-user connection pool
so each authenticated user gets their own Tastytrade session backed by their
own encrypted credentials stored in the database.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from loguru import logger

from src.api.tastytrade_client import TastytradeClient

load_dotenv()

# Per-user connection pool constants
CONNECTION_TTL = 3600   # 60 minutes
MAX_CONNECTIONS = 50


@dataclass
class UserConnection:
    """A cached per-user Tastytrade connection."""
    client: TastytradeClient
    connected_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


class ConnectionManager:
    """Manages a shared TastytradeClient singleton authenticated via OAuth2.

    In multi-user mode, also provides per-user connection pooling via
    get_user_client / get_user_status / disconnect_user.
    """

    def __init__(self):
        # Legacy (auth-disabled) state
        self.client: Optional[TastytradeClient] = None
        self.connected: bool = False
        self.error: Optional[str] = None

        # Per-user connection pool (auth-enabled)
        self._user_connections: Dict[str, UserConnection] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Legacy methods (auth-disabled path) — unchanged
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Per-user methods (auth-enabled path)
    # ------------------------------------------------------------------

    async def get_user_client(self, user_id: str) -> Optional[TastytradeClient]:
        """Get (or create) an authenticated TastytradeClient for *user_id*.

        Looks up cached connection first; if missing or expired, loads
        encrypted credentials from the DB, decrypts, creates a new client,
        authenticates, and caches it.

        Returns None if the user has no credentials stored.
        """
        async with self._lock:
            # Check cache
            conn = self._user_connections.get(user_id)
            if conn is not None:
                age = time.time() - conn.connected_at
                if age < CONNECTION_TTL:
                    conn.last_used = time.time()
                    return conn.client
                else:
                    # Expired — evict
                    logger.info(f"Connection expired for user {user_id[:8]}..., reconnecting")
                    self._user_connections.pop(user_id, None)

            # Load credentials from DB
            creds = self._load_user_credentials(user_id)
            if creds is None:
                return None

            provider_secret, refresh_token = creds

            # Create and authenticate client
            client = TastytradeClient(
                provider_secret=provider_secret,
                refresh_token=refresh_token,
            )
            success = await client.authenticate()
            if not success:
                logger.warning(f"Authentication failed for user {user_id[:8]}...")
                return None

            # Evict oldest if pool is full
            if len(self._user_connections) >= MAX_CONNECTIONS:
                self._evict_oldest()

            self._user_connections[user_id] = UserConnection(client=client)
            logger.info(f"Cached new connection for user {user_id[:8]}... (pool size: {len(self._user_connections)})")
            return client

    def get_user_status(self, user_id: str) -> Dict[str, Any]:
        """Return per-user connection status info."""
        conn = self._user_connections.get(user_id)
        if conn is not None:
            accounts = conn.client.get_all_accounts()
            return {
                'connected': True,
                'configured': True,
                'error': None,
                'accounts': accounts,
            }

        # Not cached — check if credentials exist in DB
        has_creds = self._load_user_credentials(user_id) is not None
        return {
            'connected': False,
            'configured': has_creds,
            'error': None if has_creds else None,
            'accounts': [],
        }

    def disconnect_user(self, user_id: str) -> None:
        """Evict a user's cached connection (e.g., after credential update)."""
        removed = self._user_connections.pop(user_id, None)
        if removed:
            logger.info(f"Disconnected user {user_id[:8]}... from pool")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_user_credentials(self, user_id: str) -> Optional[tuple[str, str]]:
        """Load and decrypt credentials from the user_credentials table.

        Returns (provider_secret, refresh_token) or None.

        For auth-code-flow users, encrypted_provider_secret is NULL because
        the client_secret is app-level. We fall back to the env var.
        """
        try:
            from src.database.models import UserCredential
            from src.dependencies import db
            from src.utils.credential_encryption import decrypt_credential

            with db.get_session(user_id=user_id) as session:
                row = session.query(UserCredential).filter(
                    UserCredential.provider == "tastytrade",
                    UserCredential.is_active.is_(True),
                ).first()

                if row is None:
                    return None

                # provider_secret: use per-user value if present, else app-level env var
                provider_secret = (
                    decrypt_credential(row.encrypted_provider_secret)
                    if row.encrypted_provider_secret
                    else os.getenv(
                        "TASTYTRADE_CLIENT_SECRET",
                        os.getenv("TASTYTRADE_PROVIDER_SECRET", ""),
                    )
                )

                return (
                    provider_secret,
                    decrypt_credential(row.encrypted_refresh_token),
                )
        except Exception as e:
            logger.error(f"Failed to load credentials for user {user_id[:8]}...: {e}")
            return None

    def _evict_oldest(self) -> None:
        """Remove the least-recently-used connection from the pool."""
        if not self._user_connections:
            return
        oldest_uid = min(
            self._user_connections,
            key=lambda uid: self._user_connections[uid].last_used,
        )
        self._user_connections.pop(oldest_uid, None)
        logger.info(f"Evicted LRU connection for user {oldest_uid[:8]}...")
