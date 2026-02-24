"""Auto-provision users on first authenticated request.

When a user authenticates via Supabase for the first time, we create a local
User row so foreign-key constraints are satisfied. Subsequent requests are
a fast PK lookup (no-op if user already exists).
"""

import logging

from src.database.models import User

logger = logging.getLogger(__name__)


def ensure_user_exists(user_id: str, email: str | None = None) -> None:
    """Create a User row if one doesn't exist for this user_id.

    Also updates email if it changed since last login.
    Uses an unscoped session (no user_id in session.info) because the users
    table is in _GLOBAL_TABLES and not tenant-filtered.
    """
    from src.database.engine import get_session

    with get_session(user_id=user_id) as session:
        user = session.get(User, user_id)

        if user is None:
            display_name = email.split("@")[0] if email else None
            user = User(
                id=user_id,
                email=email,
                display_name=display_name,
                auth_provider="supabase",
            )
            session.add(user)
            logger.info("Provisioned new user: %s (%s)", user_id, email)
        elif email and user.email != email:
            user.email = email
            logger.info("Updated email for user %s: %s", user_id, email)
