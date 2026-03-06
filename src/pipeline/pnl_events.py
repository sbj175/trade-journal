"""
P&L Events — denormalized fact table population.

Rebuilds pnl_events from lot_closings + position_lots + position_group_lots.
100% derived data, safe to delete-and-rebuild on every pipeline run.

Part of OPT-176.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func

from src.database.models import (
    LotClosing as LotClosingModel,
    PnlEvent,
    PositionGroupLot,
    PositionLot as PositionLotModel,
)
from src.database.tenant import DEFAULT_USER_ID

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


def populate_pnl_events(db_manager: "DatabaseManager") -> int:
    """Delete and rebuild all pnl_events for the current user.

    Joins LotClosing -> PositionLot for immutable facts, and
    LEFT JOINs PositionGroupLot for group_id (nullable for orphans).

    Returns the number of events inserted.
    """
    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)

        # Delete all existing events for this user
        deleted = session.query(PnlEvent).filter(
            PnlEvent.user_id == user_id,
        ).delete(synchronize_session=False)
        if deleted:
            logger.debug("Deleted %d existing pnl_events", deleted)

        # Query all closings with lot data and optional group_id
        rows = (
            session.query(
                LotClosingModel.closing_id,
                LotClosingModel.lot_id,
                LotClosingModel.closing_date,
                LotClosingModel.closing_price,
                LotClosingModel.closing_type,
                LotClosingModel.quantity_closed,
                LotClosingModel.realized_pnl,
                LotClosingModel.resulting_lot_id,
                PositionLotModel.account_number,
                PositionLotModel.underlying,
                PositionLotModel.symbol,
                PositionLotModel.instrument_type,
                PositionLotModel.option_type,
                PositionLotModel.strike,
                PositionLotModel.expiration,
                PositionLotModel.entry_date,
                PositionLotModel.entry_price,
                PositionLotModel.transaction_id,
            )
            .join(PositionLotModel, LotClosingModel.lot_id == PositionLotModel.id)
            .all()
        )

        if not rows:
            logger.info("No lot closings found — pnl_events empty")
            return 0

        # Build transaction_id -> group_id lookup
        txn_ids = list({r.transaction_id for r in rows})
        group_links = session.query(
            PositionGroupLot.transaction_id,
            PositionGroupLot.group_id,
        ).filter(
            PositionGroupLot.transaction_id.in_(txn_ids),
            PositionGroupLot.user_id == user_id,
        ).all()
        txn_to_group = {txn_id: group_id for txn_id, group_id in group_links}

        # Bulk insert
        events = []
        for r in rows:
            events.append(PnlEvent(
                user_id=user_id,
                closing_id=r.closing_id,
                lot_id=r.lot_id,
                group_id=txn_to_group.get(r.transaction_id),
                account_number=r.account_number,
                underlying=r.underlying,
                symbol=r.symbol,
                instrument_type=r.instrument_type,
                option_type=r.option_type,
                strike=r.strike,
                expiration=r.expiration,
                entry_date=r.entry_date,
                entry_price=r.entry_price,
                closing_date=r.closing_date,
                closing_price=r.closing_price,
                closing_type=r.closing_type,
                quantity_closed=r.quantity_closed,
                realized_pnl=r.realized_pnl,
                is_roll=r.resulting_lot_id is not None,
            ))

        session.add_all(events)
        logger.info("Populated %d pnl_events", len(events))
        return len(events)
