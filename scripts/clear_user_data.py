#!/usr/bin/env python3
"""Clear all data for a given user_id.

Usage:
    venv/bin/python scripts/clear_user_data.py <user_id>
    venv/bin/python scripts/clear_user_data.py <user_id> --yes   # skip confirmation

Deletes all rows across the 19 user-scoped tables (in FK-safe order),
then deletes the User row itself. Does NOT touch QuoteCache (global).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.db_manager import DatabaseManager
from src.database.models import (
    PositionGroupLot,
    PositionGroup,
    LotClosing,
    PositionLot,
    OrderChainCache,
    OrderChainMember,
    OrderChain,
    OrderPosition,
    OrderComment,
    Order,
    RawTransaction,
    PositionsInventory,
    PositionNote,
    StrategyTarget,
    SyncMetadata,
    Position,
    AccountBalance,
    Account,
    UserCredential,
    User,
)

# Deletion order: children before parents to respect FK constraints
MODELS_IN_ORDER = [
    PositionGroupLot,
    PositionGroup,
    LotClosing,
    PositionLot,
    OrderChainCache,
    OrderChainMember,
    OrderChain,
    OrderPosition,
    OrderComment,
    Order,
    RawTransaction,
    PositionsInventory,
    PositionNote,
    StrategyTarget,
    SyncMetadata,
    Position,
    AccountBalance,
    Account,
    UserCredential,
    User,
]


def clear_user_data(user_id: str, db: DatabaseManager) -> dict:
    """Delete all data for user_id. Returns {table_name: rows_deleted}."""
    results = {}

    with db.get_session(user_id=user_id) as session:
        for model in MODELS_IN_ORDER:
            if model is User:
                count = session.query(model).filter(model.id == user_id).delete()
            else:
                count = session.query(model).filter(model.user_id == user_id).delete()
            results[model.__tablename__] = count

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: venv/bin/python scripts/clear_user_data.py <user_id> [--yes]")
        sys.exit(1)

    user_id = sys.argv[1]
    skip_confirm = "--yes" in sys.argv

    db = DatabaseManager(db_url=os.getenv("DATABASE_URL"))
    db.initialize_database()

    # Show what we're about to delete
    print(f"\nUser ID: {user_id}")

    with db.get_session(user_id=user_id) as session:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            print(f"Email:   {user.email or '(none)'}")
        else:
            print("WARNING: No User row found for this ID (will still clean orphaned data)")

    if not skip_confirm:
        answer = input("\nDelete ALL data for this user? Type 'yes' to confirm: ")
        if answer.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    results = clear_user_data(user_id, db)

    print()
    total = 0
    for table, count in results.items():
        if count > 0:
            print(f"  {table}: {count} rows deleted")
            total += count

    if total == 0:
        print("  (no data found)")
    else:
        print(f"\n  Total: {total} rows deleted")


if __name__ == "__main__":
    main()
