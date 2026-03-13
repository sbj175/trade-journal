"""
Pipeline Orchestrator — composes processing stages into a single ``reprocess()`` call.

Replaces the duplicated reprocessing logic in sync.py endpoints
(``/api/sync``, ``/api/sync/initial``, ``/api/reprocess-chains``).

Part of OPT-121.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src.pipeline.order_assembler import assemble_orders
from src.pipeline.position_ledger import process_lots
from src.pipeline.group_manager import GroupPersister
from src.pipeline.pnl_events import populate_pnl_events
from src.services.ledger_service import net_opposing_equity_lots

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)


def _clear_groups(db_manager: "DatabaseManager") -> None:
    """Clear all position groups, group-lot links, tags, and notes for the current user."""
    from src.database.models import (
        PositionGroup, PositionGroupLot, PositionGroupTag, PositionNote,
    )
    from src.database.tenant import DEFAULT_USER_ID

    with db_manager.get_session() as session:
        user_id = session.info.get("user_id", DEFAULT_USER_ID)
        session.query(PositionGroupLot).filter(PositionGroupLot.user_id == user_id).delete()
        session.query(PositionGroupTag).filter(PositionGroupTag.user_id == user_id).delete()
        session.query(PositionNote).filter(
            PositionNote.note_key.like("group_%"),
            PositionNote.user_id == user_id,
        ).delete(synchronize_session=False)
        session.query(PositionGroup).filter(PositionGroup.user_id == user_id).delete()
        logger.info("Cleared all groups, group-lot links, tags, and group notes (user-scoped)")


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    orders_assembled: int
    groups_processed: int
    equity_lots_netted: int
    pnl_events_populated: int = 0


def reprocess(
    db_manager: "DatabaseManager",
    lot_manager: "LotManager",
    raw_transactions: List[Dict],
    affected_underlyings: Optional[Set[str]] = None,
) -> PipelineResult:
    """Run the full processing pipeline on raw transactions.

    Stages:
      1. Clear lots (full or incremental)
      2. OrderAssembler.assemble_orders() — produces typed Order objects
      3. position_ledger.process_lots() — creates lots, closings
      4. Equity netting (before groups, so groups see final lot states)
      5. GroupPersister.process_groups() — expiration-based grouping with strategy labels
      6. P&L Events (denormalized fact table)

    Parameters:
        db_manager: Database manager instance
        lot_manager: LotManager instance
        raw_transactions: Raw transaction dicts from DB
        affected_underlyings: If set, only reprocess these underlyings (incremental)

    Returns:
        PipelineResult with counts for each stage
    """
    if not raw_transactions:
        logger.info("No transactions to process — returning empty result")
        return PipelineResult(
            orders_assembled=0,
            groups_processed=0,
            equity_lots_netted=0,
        )

    # ── Step 1: Clear existing state ──────────────────────────────────
    if affected_underlyings:
        lot_manager.clear_all_lots(underlyings=affected_underlyings)
        logger.info(
            "Cleared lots for %d affected underlyings",
            len(affected_underlyings),
        )
    else:
        lot_manager.clear_all_lots()
        # Full reprocess: also clear groups so they're rebuilt from scratch
        # (prevents stale group-lot links from old grouping logic)
        _clear_groups(db_manager)
        logger.info("Cleared lots and groups for full reprocessing")

    # ── Step 2: Order Assembly (stateless) ─────────────────────────────
    assembly = assemble_orders(raw_transactions)
    orders_assembled = len(assembly.orders)
    logger.info("Stage 2: assembled %d orders", orders_assembled)

    # ── Step 3: Lot operations (position_ledger) ──────────────────────
    if affected_underlyings:
        filtered_orders = [
            o for o in assembly.orders
            if o.underlying in affected_underlyings
        ]
        filtered_stock_txs = [
            tx for tx in assembly.assignment_stock_transactions
            if tx.get("underlying_symbol", tx.get("symbol", "")) in affected_underlyings
        ]
        process_lots(
            filtered_orders,
            filtered_stock_txs,
            lot_manager,
            db_manager,
        )
        logger.info(
            "Stage 3: incremental lot processing for %d underlyings (%d orders)",
            len(affected_underlyings), len(filtered_orders),
        )
    else:
        process_lots(
            assembly.orders,
            assembly.assignment_stock_transactions,
            lot_manager,
            db_manager,
        )
        logger.info("Stage 3: full lot processing for %d orders", len(assembly.orders))

    # ── Step 4: Equity netting (before groups, so groups see final lot states)
    equity_lots_netted = net_opposing_equity_lots(db=db_manager, lot_manager=lot_manager)
    if equity_lots_netted:
        logger.info("Stage 4: equity netting closed %d lot sides", equity_lots_netted)

    # ── Step 5: Group Manager (strategy + persistence) ────────────────
    persister = GroupPersister(db_manager, lot_manager)
    groups_processed = persister.process_groups()
    logger.info("Stage 5: processed %d groups", groups_processed)

    # ── Step 6: P&L Events (denormalized fact table) ──────────────────
    pnl_events_count = populate_pnl_events(db_manager)
    logger.info("Stage 6: populated %d pnl_events", pnl_events_count)

    return PipelineResult(
        orders_assembled=orders_assembled,
        groups_processed=groups_processed,
        equity_lots_netted=equity_lots_netted,
        pnl_events_populated=pnl_events_count,
    )
