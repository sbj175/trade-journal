"""Tests for ledger_service — position group seeding and equity lot grouping."""

import uuid
import pytest

from src.services import ledger_service
from src.models.lot_manager import Lot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_position_group(cursor, *, group_id, account_number, underlying,
                           strategy_label, status='OPEN', source_chain_id=None,
                           opening_date='2025-01-15'):
    cursor.execute("""
        INSERT INTO position_groups
            (group_id, account_number, underlying, strategy_label, status,
             source_chain_id, opening_date, closing_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
    """, (group_id, account_number, underlying, strategy_label, status,
          source_chain_id, opening_date))


def _insert_position_lot(cursor, *, transaction_id, account_number, underlying,
                         symbol=None, chain_id=None, instrument_type='EQUITY',
                         quantity=100, entry_price=50.0,
                         entry_date='2025-02-01T10:00:00'):
    symbol = symbol or underlying
    cursor.execute("""
        INSERT INTO position_lots
            (transaction_id, account_number, symbol, underlying, instrument_type,
             option_type, strike, expiration, quantity, entry_price, entry_date,
             remaining_quantity, original_quantity, chain_id, leg_index,
             opening_order_id, derived_from_lot_id, derivation_type, status)
        VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, 0,
                NULL, NULL, NULL, 'OPEN')
    """, (transaction_id, account_number, symbol, underlying, instrument_type,
          quantity, entry_price, entry_date, quantity, quantity, chain_id))


def _link_lot_to_group(cursor, group_id, transaction_id):
    cursor.execute("""
        INSERT OR IGNORE INTO position_group_lots (group_id, transaction_id)
        VALUES (?, ?)
    """, (group_id, transaction_id))


def _get_group_lots(cursor, group_id):
    cursor.execute(
        "SELECT transaction_id FROM position_group_lots WHERE group_id = ?",
        (group_id,)
    )
    return [row[0] for row in cursor.fetchall()]


def _get_all_groups(cursor, account_number, underlying):
    cursor.execute("""
        SELECT group_id, strategy_label, source_chain_id, status
        FROM position_groups
        WHERE account_number = ? AND underlying = ?
    """, (account_number, underlying))
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Tests for seed_new_lots_into_groups — equity lots join existing group
# ---------------------------------------------------------------------------

class TestSeedNewLotsIntoGroups:
    """seed_new_lots_into_groups should add chainless equity lots to an existing
    OPEN group for the same account+underlying, even if that group is a
    Covered Call (has source_chain_id and strategy_label != 'Shares')."""

    def test_new_equity_lot_joins_covered_call_group(self, db, lot_manager, monkeypatch):
        """New equity lot with no chain_id should join an existing Covered Call group."""
        monkeypatch.setattr(ledger_service, 'db', db)
        monkeypatch.setattr(ledger_service, 'lot_manager', lot_manager)

        cc_group_id = str(uuid.uuid4())
        chain_id = 'chain-cc-001'

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Existing Covered Call group with an equity lot already in it
            _insert_position_group(cursor, group_id=cc_group_id,
                                   account_number='ACCT1', underlying='IBIT',
                                   strategy_label='Covered Call', status='OPEN',
                                   source_chain_id=chain_id)
            _insert_position_lot(cursor, transaction_id='tx-existing-shares',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=chain_id, quantity=100)
            _link_lot_to_group(cursor, cc_group_id, 'tx-existing-shares')

            # New equity lot — no chain_id (direct stock purchase)
            _insert_position_lot(cursor, transaction_id='tx-new-shares',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=None, quantity=100,
                                 entry_date='2025-02-10T10:00:00')
            conn.commit()

        assigned = ledger_service.seed_new_lots_into_groups()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            lots_in_group = _get_group_lots(cursor, cc_group_id)
            groups = _get_all_groups(cursor, 'ACCT1', 'IBIT')

        # New lot should be in the existing Covered Call group
        assert 'tx-new-shares' in lots_in_group
        # No new group should have been created — still just the one
        assert len(groups) == 1
        assert groups[0][1] == 'Covered Call'

    def test_new_equity_lot_creates_shares_group_when_none_exists(self, db, lot_manager, monkeypatch):
        """When no OPEN group exists for the underlying, a new 'Shares' group is created."""
        monkeypatch.setattr(ledger_service, 'db', db)
        monkeypatch.setattr(ledger_service, 'lot_manager', lot_manager)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Insert a dummy group so we don't trigger full seed_position_groups path
            _insert_position_group(cursor, group_id=str(uuid.uuid4()),
                                   account_number='ACCT1', underlying='AAPL',
                                   strategy_label='Shares', status='OPEN')

            # Equity lot for a different underlying with no group
            _insert_position_lot(cursor, transaction_id='tx-new-spy',
                                 account_number='ACCT1', underlying='SPY',
                                 chain_id=None, quantity=50)
            conn.commit()

        assigned = ledger_service.seed_new_lots_into_groups()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            groups = _get_all_groups(cursor, 'ACCT1', 'SPY')

        assert len(groups) == 1
        assert groups[0][1] == 'Shares'

        with db.get_connection() as conn:
            lots = _get_group_lots(conn.cursor(), groups[0][0])
        assert 'tx-new-spy' in lots

    def test_new_equity_lot_ignores_closed_groups(self, db, lot_manager, monkeypatch):
        """Chainless equity lots should NOT be added to CLOSED groups."""
        monkeypatch.setattr(ledger_service, 'db', db)
        monkeypatch.setattr(ledger_service, 'lot_manager', lot_manager)

        closed_group_id = str(uuid.uuid4())

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Existing CLOSED group for IBIT
            _insert_position_group(cursor, group_id=closed_group_id,
                                   account_number='ACCT1', underlying='IBIT',
                                   strategy_label='Covered Call', status='CLOSED',
                                   source_chain_id='chain-old')
            _insert_position_lot(cursor, transaction_id='tx-old-shares',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id='chain-old', quantity=0,
                                 entry_date='2024-06-01T10:00:00')
            _link_lot_to_group(cursor, closed_group_id, 'tx-old-shares')

            # Ensure position_groups is not empty (so full seed isn't triggered)
            _insert_position_group(cursor, group_id=str(uuid.uuid4()),
                                   account_number='ACCT1', underlying='AAPL',
                                   strategy_label='Shares', status='OPEN')

            # New equity lot
            _insert_position_lot(cursor, transaction_id='tx-new-ibit',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=None, quantity=100)
            conn.commit()

        ledger_service.seed_new_lots_into_groups()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Should NOT be in the closed group
            lots_in_closed = _get_group_lots(cursor, closed_group_id)
            assert 'tx-new-ibit' not in lots_in_closed

            # A new Shares group should have been created
            groups = _get_all_groups(cursor, 'ACCT1', 'IBIT')
            open_groups = [g for g in groups if g[3] == 'OPEN']
            assert len(open_groups) == 1
            assert open_groups[0][1] == 'Shares'


# ---------------------------------------------------------------------------
# Tests for seed_position_groups — initial seeding with ungrouped equity lots
# ---------------------------------------------------------------------------

class TestSeedPositionGroupsUngrouped:
    """seed_position_groups should add chainless lots to an existing OPEN group
    (created from chain-based seeding) instead of always creating a new 'Shares' group."""

    def test_ungrouped_lots_join_existing_open_group(self, db, lot_manager, monkeypatch):
        """During initial seeding, chainless lots should join an existing OPEN group
        for the same account+underlying rather than creating a duplicate."""
        monkeypatch.setattr(ledger_service, 'db', db)
        monkeypatch.setattr(ledger_service, 'lot_manager', lot_manager)

        chain_id = 'chain-cc-002'
        cc_group_id = str(uuid.uuid4())

        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Pre-create a chain-based group (simulating what happens for chain lots
            # earlier in seed_position_groups)
            _insert_position_group(cursor, group_id=cc_group_id,
                                   account_number='ACCT1', underlying='IBIT',
                                   strategy_label='Covered Call', status='OPEN',
                                   source_chain_id=chain_id)
            # Lot that's already in a chain and linked to the group
            _insert_position_lot(cursor, transaction_id='tx-option-leg',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=chain_id, instrument_type='EQUITY_OPTION',
                                 quantity=-1, entry_price=2.50)
            _link_lot_to_group(cursor, cc_group_id, 'tx-option-leg')

            # Chainless equity lot — NOT linked to any group
            _insert_position_lot(cursor, transaction_id='tx-shares-no-chain',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=None, quantity=100)
            conn.commit()

        groups_created = ledger_service.seed_position_groups()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            groups = _get_all_groups(cursor, 'ACCT1', 'IBIT')
            lots_in_cc = _get_group_lots(cursor, cc_group_id)

        # The chainless lot should have joined the existing CC group
        assert 'tx-shares-no-chain' in lots_in_cc
        # No new group should have been created for IBIT
        assert len(groups) == 1
        assert groups[0][1] == 'Covered Call'
