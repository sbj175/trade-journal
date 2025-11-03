"""
Authentication and session management for Trade Journal.

Handles user authentication against Tastytrade API and manages session state.
Credentials are only held in memory for the duration of a session.
"""

import secrets
import time
from typing import Optional, Tuple
from src.api.tastytrade_client import TastytradeClient


class SessionData:
    """Represents a single authenticated session."""

    def __init__(self, username: str, password: str, session_id: str, created_at: float):
        self.username = username
        self.password = password
        self.session_id = session_id
        self.created_at = created_at

    def is_expired(self, timeout_seconds: int = 3600) -> bool:
        """Check if session has expired (default 1 hour)."""
        return time.time() - self.created_at > timeout_seconds


class AuthManager:
    """Manages authentication and session state."""

    def __init__(self, session_timeout_seconds: int = 3600):
        """
        Initialize AuthManager.

        Args:
            session_timeout_seconds: How long sessions remain valid (default 1 hour)
        """
        self.sessions: dict[str, SessionData] = {}
        self.session_timeout = session_timeout_seconds

    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[str]]:
        """
        Authenticate a user against Tastytrade API.

        Args:
            username: Tastytrade username
            password: Tastytrade password

        Returns:
            Tuple of (success: bool, session_id: Optional[str])
            If successful, session_id is returned and can be used in cookies
        """
        try:
            # Try to authenticate with provided credentials
            client = TastytradeClient(username=username, password=password)
            success = client.authenticate()

            if success:
                # Create new session with credentials stored for use during this session
                session_id = secrets.token_urlsafe(32)
                self.sessions[session_id] = SessionData(username, password, session_id, time.time())
                return True, session_id
            else:
                return False, None

        except Exception as e:
            # Authentication failed (invalid credentials or API error)
            print(f"Authentication error: {e}")
            return False, None

    def validate_session(self, session_id: str) -> bool:
        """
        Check if a session is valid and not expired.

        Args:
            session_id: Session ID to validate

        Returns:
            True if session is valid, False otherwise
        """
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        if session.is_expired(self.session_timeout):
            # Remove expired session
            del self.sessions[session_id]
            return False

        return True

    def get_session_username(self, session_id: str) -> Optional[str]:
        """
        Get the username for a valid session.

        Args:
            session_id: Session ID to look up

        Returns:
            Username if session is valid, None otherwise
        """
        if not self.validate_session(session_id):
            return None

        return self.sessions[session_id].username

    def get_session_credentials(self, session_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the username and password for a valid session.

        Args:
            session_id: Session ID to look up

        Returns:
            Tuple of (username, password) if session is valid, (None, None) otherwise
        """
        if not self.validate_session(session_id):
            return None, None

        session = self.sessions[session_id]
        return session.username, session.password

    def logout(self, session_id: str) -> bool:
        """
        Logout a user by invalidating their session.

        Args:
            session_id: Session ID to invalidate

        Returns:
            True if session was found and removed, False otherwise
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def get_any_session_credentials(self) -> Optional[Tuple[str, str]]:
        """
        Get credentials from any valid session (used for background tasks).

        Returns:
            Tuple of (username, password) from first valid session, or None if no valid sessions
        """
        for session_id, session in list(self.sessions.items()):
            if not session.is_expired(self.session_timeout):
                return session.username, session.password

        return None

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions.

        Returns:
            Number of sessions removed
        """
        expired_ids = [
            sid for sid, session in self.sessions.items()
            if session.is_expired(self.session_timeout)
        ]

        for sid in expired_ids:
            del self.sessions[sid]

        return len(expired_ids)
