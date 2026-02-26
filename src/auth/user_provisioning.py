"""Auto-provision users on first authenticated request.

When a user authenticates via Supabase for the first time, we create a local
User row so foreign-key constraints are satisfied. Subsequent requests are
a fast PK lookup (no-op if user already exists).
"""

import logging
from datetime import datetime, timezone

from src.database.models import User, StrategyTarget

logger = logging.getLogger(__name__)


def ensure_user_exists(user_id: str, email: str | None = None) -> None:
    """Create a User row if one doesn't exist for this user_id.

    Also updates email if it changed since last login.
    Seeds default strategy targets for new users.
    Uses an unscoped session (no user_id in session.info) because the users
    table is in _GLOBAL_TABLES and not tenant-filtered.
    """
    from src.database.engine import get_session

    with get_session(user_id=user_id) as session:
        user = session.get(User, user_id)

        now = datetime.now(timezone.utc).isoformat()

        if user is None:
            display_name = email.split("@")[0] if email else None
            user = User(
                id=user_id,
                email=email,
                display_name=display_name,
                auth_provider="supabase",
                last_login_at=now,
            )
            session.add(user)
            _seed_default_strategy_targets(session)
            logger.info("Provisioned new user: %s (%s)", user_id, email)
        else:
            user.last_login_at = now
            if email and user.email != email:
                user.email = email
                logger.info("Updated email for user %s: %s", user_id, email)


def _seed_default_strategy_targets(session) -> None:
    """Seed default strategy targets for a new user.

    The session already has user_id set, so the tenant before_flush
    event will auto-assign it to each new StrategyTarget row.
    """
    defaults = [
        ('Bull Put Spread', 50.0, 100.0), ('Bear Call Spread', 50.0, 100.0),
        ('Iron Condor', 50.0, 100.0), ('Cash Secured Put', 50.0, 100.0),
        ('Covered Call', 50.0, 100.0), ('Short Put', 50.0, 100.0),
        ('Short Call', 50.0, 100.0), ('Short Strangle', 50.0, 100.0),
        ('Iron Butterfly', 25.0, 100.0), ('Short Straddle', 25.0, 100.0),
        ('Bull Call Spread', 100.0, 50.0), ('Bear Put Spread', 100.0, 50.0),
        ('Long Call', 100.0, 50.0), ('Long Put', 100.0, 50.0),
        ('Long Strangle', 100.0, 50.0), ('Long Straddle', 100.0, 50.0),
        ('Shares', 20.0, 10.0),
    ]
    for name, profit, loss in defaults:
        session.add(StrategyTarget(
            strategy_name=name, profit_target_pct=profit, loss_target_pct=loss,
        ))
