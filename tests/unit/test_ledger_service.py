"""Tests for ledger_service — position group seeding and equity lot grouping."""

import uuid
import pytest

from src.database.models import PositionGroup, PositionGroupLot, PositionLot as PositionLotModel
from src.services import ledger_service
from src.models.lot_manager import Lot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_position_group(session, *, group_id, account_number, underlying,
                           strategy_label, status='OPEN', source_chain_id=None,
                           opening_date='2025-01-15'):
    session.add(PositionGroup(
        group_id=group_id, account_number=account_number, underlying=underlying,
        strategy_label=strategy_label, status=status,
        source_chain_id=source_chain_id, opening_date=opening_date,
    ))


def _insert_position_lot(session, *, transaction_id, account_number, underlying,
                         symbol=None, chain_id=None, instrument_type='EQUITY',
                         quantity=100, entry_price=50.0,
                         entry_date='2025-02-01T10:00:00'):
    symbol = symbol or underlying
    session.add(PositionLotModel(
        transaction_id=transaction_id, account_number=account_number,
        symbol=symbol, underlying=underlying, instrument_type=instrument_type,
        quantity=quantity, entry_price=entry_price, entry_date=entry_date,
        remaining_quantity=quantity, original_quantity=quantity,
        chain_id=chain_id, leg_index=0, status='OPEN',
    ))


def _link_lot_to_group(session, group_id, transaction_id):
    from src.database.engine import dialect_insert
    stmt = dialect_insert(PositionGroupLot).values(
        group_id=group_id, transaction_id=transaction_id,
    )
    session.execute(stmt.on_conflict_do_nothing())


def _get_group_lots(session, group_id):
    rows = session.query(PositionGroupLot.transaction_id).filter(
        PositionGroupLot.group_id == group_id,
    ).all()
    return [r[0] for r in rows]


def _get_all_groups(session, account_number, underlying):
    return session.query(
        PositionGroup.group_id, PositionGroup.strategy_label,
        PositionGroup.source_chain_id, PositionGroup.status,
    ).filter(
        PositionGroup.account_number == account_number,
        PositionGroup.underlying == underlying,
    ).all()


# ---------------------------------------------------------------------------
# Tests for seed_position_groups — initial seeding with ungrouped equity lots
# ---------------------------------------------------------------------------

class TestSeedPositionGroupsUngrouped:
    """seed_position_groups should add chainless lots to an existing OPEN group
    (created from chain-based seeding) instead of always creating a new 'Shares' group."""

    def test_ungrouped_lots_join_existing_open_group(self, db, lot_manager):
        """During initial seeding, chainless lots should join an existing OPEN group
        for the same account+underlying rather than creating a duplicate."""
        chain_id = 'chain-cc-002'
        cc_group_id = str(uuid.uuid4())

        with db.get_session() as session:
            _insert_position_group(session, group_id=cc_group_id,
                                   account_number='ACCT1', underlying='IBIT',
                                   strategy_label='Covered Call', status='OPEN',
                                   source_chain_id=chain_id)
            _insert_position_lot(session, transaction_id='tx-option-leg',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=chain_id, instrument_type='EQUITY_OPTION',
                                 quantity=-1, entry_price=2.50)
            _link_lot_to_group(session, cc_group_id, 'tx-option-leg')

            _insert_position_lot(session, transaction_id='tx-shares-no-chain',
                                 account_number='ACCT1', underlying='IBIT',
                                 chain_id=None, quantity=100)

        groups_created = ledger_service.seed_position_groups(db=db, lot_manager=lot_manager)

        with db.get_session() as session:
            groups = _get_all_groups(session, 'ACCT1', 'IBIT')
            lots_in_cc = _get_group_lots(session, cc_group_id)

        assert 'tx-shares-no-chain' in lots_in_cc
        assert len(groups) == 1
        assert groups[0][1] == 'Covered Call'
