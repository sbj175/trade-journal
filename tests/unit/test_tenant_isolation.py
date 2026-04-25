"""
Tests for multi-tenant isolation via user_id scoping.

Verifies:
- User A cannot see User B's data
- before_flush auto-sets user_id on new ORM objects
- Default user sees all existing data
- QuoteCache (global) is unaffected by tenant filter
"""

import pytest

from src.database.db_manager import DatabaseManager
from src.database import engine as sa_engine
from src.database.tenant import DEFAULT_USER_ID
from src.database.models import (
    User, Account, SyncMetadata, StrategyTarget,
    QuoteCache, RawTransaction, OrderChain,
)


USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def tenant_db(tmp_path):
    """Temporary SQLite database with two test users seeded."""
    db_path = str(tmp_path / "tenant_test.db")
    db_manager = DatabaseManager(db_url=f"sqlite:///{db_path}")
    db_manager.initialize_database()

    # Seed two test users
    with db_manager.get_session() as session:
        session.add(User(id=USER_A, display_name="User A", is_active=True))
        session.add(User(id=USER_B, display_name="User B", is_active=True))

    return db_manager


def test_user_a_cannot_see_user_b_accounts(tenant_db):
    """One user's brokerage accounts should be invisible to another user."""
    # User A creates an account
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(Account(
            account_number="ACCT-A", account_name="A's Account",
            account_type="Individual",
        ))

    # User B creates an account
    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(Account(
            account_number="ACCT-B", account_name="B's Account",
            account_type="Individual",
        ))

    # User A should only see their account
    with tenant_db.get_session(user_id=USER_A) as session:
        accounts = session.query(Account).all()
        assert len(accounts) == 1
        assert accounts[0].account_number == "ACCT-A"

    # User B should only see their account
    with tenant_db.get_session(user_id=USER_B) as session:
        accounts = session.query(Account).all()
        assert len(accounts) == 1
        assert accounts[0].account_number == "ACCT-B"


def test_before_flush_auto_sets_user_id(tenant_db):
    """New rows added during a session should automatically be tagged with the current user's id."""
    with tenant_db.get_session(user_id=USER_A) as session:
        acct = Account(
            account_number="AUTO-A", account_name="Auto",
            account_type="Individual",
        )
        session.add(acct)
        session.flush()
        assert acct.user_id == USER_A


def test_default_user_sees_default_data(tenant_db):
    """The default seeded user should see the seeded strategy targets, while other users should see none of them."""
    # initialize_database() seeds default strategy targets with DEFAULT_USER_ID
    with tenant_db.get_session(user_id=DEFAULT_USER_ID) as session:
        targets = session.query(StrategyTarget).all()
        assert len(targets) > 0  # seeded by initialize_database

    # Another user should NOT see those
    with tenant_db.get_session(user_id=USER_A) as session:
        targets = session.query(StrategyTarget).all()
        assert len(targets) == 0


def test_quote_cache_is_global(tenant_db):
    """The shared market-quote cache should be visible to every user since it has no per-user scoping."""
    # Insert a quote (QuoteCache has no user_id, so it bypasses tenant filtering)
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(QuoteCache(symbol="AAPL", mark=150.0, bid=149.9, ask=150.1))

    # User B should also see it
    with tenant_db.get_session(user_id=USER_B) as session:
        quote = session.query(QuoteCache).filter(QuoteCache.symbol == "AAPL").first()
        assert quote is not None
        assert quote.mark == 150.0


def test_sync_metadata_scoped_per_user(tenant_db):
    """Two users storing different values under the same sync-metadata key should each see only their own value."""
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(SyncMetadata(key="last_sync", value="2025-01-01"))

    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(SyncMetadata(key="last_sync", value="2025-06-01"))

    # Each user sees only their own value
    with tenant_db.get_session(user_id=USER_A) as session:
        row = session.query(SyncMetadata).filter(SyncMetadata.key == "last_sync").first()
        assert row.value == "2025-01-01"

    with tenant_db.get_session(user_id=USER_B) as session:
        row = session.query(SyncMetadata).filter(SyncMetadata.key == "last_sync").first()
        assert row.value == "2025-06-01"


def test_bulk_delete_scoped_to_user(tenant_db):
    """A bulk delete run by one user should never wipe out another user's rows."""
    # User A creates 2 accounts
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(Account(account_number="DEL-A1", account_name="A1", account_type="Individual"))
        session.add(Account(account_number="DEL-A2", account_name="A2", account_type="Individual"))

    # User B creates 1 account
    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(Account(account_number="DEL-B1", account_name="B1", account_type="Individual"))

    # User A bulk-deletes all accounts (should only affect User A's rows)
    with tenant_db.get_session(user_id=USER_A) as session:
        deleted = session.query(Account).delete()
        assert deleted == 2

    # User B's account should still exist
    with tenant_db.get_session(user_id=USER_B) as session:
        accounts = session.query(Account).all()
        assert len(accounts) == 1
        assert accounts[0].account_number == "DEL-B1"


def test_bulk_update_scoped_to_user(tenant_db):
    """A bulk update run by one user should never modify another user's rows."""
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(Account(account_number="UPD-A", account_name="Original A", account_type="Individual"))

    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(Account(account_number="UPD-B", account_name="Original B", account_type="Individual"))

    # User A bulk-updates all accounts (should only affect User A's rows)
    with tenant_db.get_session(user_id=USER_A) as session:
        updated = session.query(Account).update({"account_name": "UPDATED"})
        assert updated == 1

    # User B's account should be unchanged
    with tenant_db.get_session(user_id=USER_B) as session:
        acct = session.query(Account).first()
        assert acct.account_name == "Original B"

    # User A's account should be updated
    with tenant_db.get_session(user_id=USER_A) as session:
        acct = session.query(Account).first()
        assert acct.account_name == "UPDATED"


def test_subquery_scoped_to_user(tenant_db):
    """Subqueries skip the automatic per-user filter, so callers must add an explicit user-id filter to keep one user's data from leaking into another user's results."""
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(SyncMetadata(key="sub_test", value="A-value"))

    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(SyncMetadata(key="sub_test", value="B-value"))

    with tenant_db.get_session(user_id=USER_A) as session:
        # Without explicit user_id filter, subquery leaks cross-tenant data
        from sqlalchemy import select
        unscoped_subq = (
            session.query(SyncMetadata.value)
            .filter(SyncMetadata.key == "sub_test")
            .subquery()
        )
        leaked = session.execute(select(unscoped_subq.c.value)).scalars().all()
        assert len(leaked) == 2  # BOTH users' data — demonstrates the gap

        # With explicit user_id filter, subquery is properly scoped
        scoped_subq = (
            session.query(SyncMetadata.value)
            .filter(SyncMetadata.key == "sub_test")
            .filter(SyncMetadata.user_id == USER_A)
            .subquery()
        )
        result = session.execute(select(scoped_subq.c.value)).scalars().all()
        assert result == ["A-value"]


def test_raw_transactions_isolated(tenant_db):
    """Raw broker transactions should only be visible to the user who imported them."""
    with tenant_db.get_session(user_id=USER_A) as session:
        session.add(Account(account_number="ACCT-A", account_name="A"))
        session.add(RawTransaction(
            id="tx-a-001", account_number="ACCT-A",
            transaction_type="Trade", transaction_sub_type="Sell to Open",
        ))

    with tenant_db.get_session(user_id=USER_B) as session:
        session.add(Account(account_number="ACCT-B", account_name="B"))
        session.add(RawTransaction(
            id="tx-b-001", account_number="ACCT-B",
            transaction_type="Trade", transaction_sub_type="Buy to Open",
        ))

    with tenant_db.get_session(user_id=USER_A) as session:
        txns = session.query(RawTransaction).all()
        assert len(txns) == 1
        assert txns[0].id == "tx-a-001"

    with tenant_db.get_session(user_id=USER_B) as session:
        txns = session.query(RawTransaction).all()
        assert len(txns) == 1
        assert txns[0].id == "tx-b-001"
