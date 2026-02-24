"""Fernet-based encryption for user credentials stored in the database.

Reads CREDENTIAL_ENCRYPTION_KEY from the environment.  If the key is not set,
auto-generates one and sets it in os.environ so the running process can
function, but logs a warning telling the operator to persist the key in .env.
"""

import os

from cryptography.fernet import Fernet
from loguru import logger

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Return (and lazily initialize) the module-level Fernet instance."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["CREDENTIAL_ENCRYPTION_KEY"] = key
        logger.warning(
            "CREDENTIAL_ENCRYPTION_KEY not set — generated a temporary key. "
            "Add this to your .env to persist across restarts:\n"
            f"  CREDENTIAL_ENCRYPTION_KEY={key}"
        )

    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a plaintext credential string, returning a URL-safe base64 token."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a previously encrypted credential token back to plaintext."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
