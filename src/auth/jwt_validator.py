"""Supabase JWT validation.

Validates JWTs issued by Supabase Auth using the project's JWT secret.
Fast, local validation — no network calls required.
"""

import os
import logging

import jwt

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


class AuthError(Exception):
    """Raised when JWT validation fails."""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_token(token: str) -> dict:
    """Decode and validate a Supabase JWT.

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        The decoded payload dict (contains 'sub', 'email', 'exp', etc.).

    Raises:
        AuthError: If the token is invalid, expired, or missing required claims.
    """
    if not SUPABASE_JWT_SECRET:
        raise AuthError("Authentication not configured on server", 500)

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            options={
                "require": ["sub", "exp", "aud"],
            },
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token has expired")
    except jwt.InvalidAudienceError:
        raise AuthError("Invalid token audience")
    except jwt.DecodeError:
        raise AuthError("Invalid token")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Token validation failed: {e}")

    if not payload.get("sub"):
        raise AuthError("Token missing subject claim")

    return payload
