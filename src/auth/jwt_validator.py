"""Supabase JWT validation.

Validates JWTs issued by Supabase Auth. Supports two modes:

1. **ES256 (JWKS)** — modern Supabase projects. Uses the JWKS endpoint at
   ``SUPABASE_URL/auth/v1/.well-known/jwks.json`` to fetch public keys.
   Requires ``SUPABASE_URL`` env var.

2. **HS256 (legacy secret)** — older Supabase projects that still use a
   symmetric JWT secret.  Requires ``SUPABASE_JWT_SECRET`` env var.

Either env var being set enables authentication.  If both are set, ES256/JWKS
takes precedence (it's what the token will actually use).
"""

import os
import logging

import jwt

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# Tolerate clock skew (seconds) — common on WSL2 where the clock drifts
_LEEWAY = 120

# JWKS client for ES256 validation (cached, thread-safe)
_jwks_client = None

def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        logger.info("JWKS client initialized: %s", jwks_url)
    return _jwks_client


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
    if not SUPABASE_URL and not SUPABASE_JWT_SECRET:
        raise AuthError("Authentication not configured on server", 500)

    # Peek at the token header to determine the algorithm
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError:
        raise AuthError("Malformed token")

    alg = header.get("alg", "")

    try:
        if alg == "ES256" and SUPABASE_URL:
            # Modern Supabase: asymmetric ES256 via JWKS
            client = _get_jwks_client()
            if client is None:
                raise AuthError("JWKS not configured (SUPABASE_URL missing)", 500)
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                leeway=_LEEWAY,
                options={"require": ["sub", "exp", "aud"]},
            )
        elif SUPABASE_JWT_SECRET:
            # Legacy Supabase: symmetric HS256
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
                leeway=_LEEWAY,
                options={"require": ["sub", "exp", "aud"]},
            )
        else:
            raise AuthError(
                f"Token uses {alg} but no matching credentials configured", 500
            )
    except jwt.ExpiredSignatureError:
        logger.warning("JWT validation failed: token expired")
        raise AuthError("Token has expired")
    except jwt.InvalidAudienceError:
        logger.warning("JWT validation failed: invalid audience")
        raise AuthError("Invalid token audience")
    except jwt.DecodeError as e:
        logger.warning("JWT validation failed: decode error — %s", e)
        raise AuthError("Invalid token")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise AuthError(f"Token validation failed: {e}")

    if not payload.get("sub"):
        raise AuthError("Token missing subject claim")

    return payload
