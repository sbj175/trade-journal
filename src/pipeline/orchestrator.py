"""
Pipeline Orchestrator — composes Stages 2-6 into a single ``reprocess()`` call.

Replaces the duplicated reprocessing logic in sync.py endpoints
(``/api/sync``, ``/api/sync/initial``, ``/api/reprocess-chains``).

Part of OPT-121.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src.models.order_processor import Chain
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.position_ledger import process_lots
from src.pipeline.chain_graph import derive_chains
from src.pipeline.group_manager import GroupPersister
from src.services.ledger_service import net_opposing_equity_lots

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    orders_assembled: int
    chains_derived: int
    groups_processed: int
    equity_lots_netted: int
    chains: List[Chain] = field(default_factory=list)


def reprocess(
    db_manager: "DatabaseManager",
    lot_manager: "LotManager",
    raw_transactions: List[Dict],
    affected_underlyings: Optional[Set[str]] = None,
) -> PipelineResult:
    """Run the full processing pipeline on raw transactions.

    Composes stages 2-6:
      1. Clear lots (full or incremental)
      2. OrderAssembler.assemble_orders() — produces typed Order objects
      3. position_ledger.process_lots() — creates lots, closings
      4. chain_graph.derive_chains() — graph-based chain derivation
      5. GroupPersister.process_groups() — cross-order grouping with strategy labels
      6. net_opposing_equity_lots() — equity netting cleanup

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
            chains_derived=0,
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
        logger.info("Cleared lots for full reprocessing")

    # ── Step 2: Stage 2 — Order Assembly (stateless) ──────────────────
    assembly = assemble_orders(raw_transactions)
    orders_assembled = len(assembly.orders)
    logger.info("Stage 2: assembled %d orders", orders_assembled)

    # ── Step 3: Stage 3 — Lot operations (position_ledger) ───────────
    if affected_underlyings:
        # Incremental: filter orders to only affected underlyings
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

    # ── Step 4: Stage 4 — Chain Graph (graph-based chain derivation) ──
    new_chains = derive_chains(db_manager, assembly.orders)
    chains_derived = len(new_chains)
    logger.info("Stage 4: derived %d chains via graph", chains_derived)

    # ── Step 5: Equity netting (before groups, so groups see final lot states)
    equity_lots_netted = net_opposing_equity_lots()
    if equity_lots_netted:
        logger.info("Stage 5: equity netting closed %d lot sides", equity_lots_netted)

    # ── Step 6: Group Manager (strategy + persistence) ─────────────
    persister = GroupPersister(db_manager, lot_manager)
    groups_processed = persister.process_groups(new_chains)
    logger.info("Stage 6: processed %d groups", groups_processed)

    return PipelineResult(
        orders_assembled=orders_assembled,
        chains_derived=chains_derived,
        groups_processed=groups_processed,
        equity_lots_netted=equity_lots_netted,
        chains=new_chains,
    )
