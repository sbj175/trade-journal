"""
Pipeline Orchestrator — composes Stages 2-6 into a single ``reprocess()`` call.

Replaces the duplicated reprocessing logic scattered across sync.py endpoints.
Built alongside the existing code — NOT wired into any router yet (shadow build).

Part of OPT-121 (final piece).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src.models.order_processor import Chain
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.chain_graph import derive_chains
from src.pipeline.group_manager import GroupPersister
from src.services.ledger_service import net_opposing_equity_lots

if TYPE_CHECKING:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager
    from src.models.order_processor import OrderProcessor
    from src.models.position_inventory import PositionInventoryManager

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    orders_assembled: int
    chains_derived: int
    groups_processed: int
    equity_lots_netted: int


def reprocess(
    db_manager: "DatabaseManager",
    order_processor: "OrderProcessor",
    lot_manager: "LotManager",
    position_manager: "PositionInventoryManager",
    raw_transactions: List[Dict],
    affected_underlyings: Optional[Set[str]] = None,
) -> PipelineResult:
    """Run the full processing pipeline on raw transactions.

    Composes stages 2-6:
      1. Clear positions & lots (full or incremental)
      2. OrderAssembler.assemble_orders() — produces typed Order objects
      3. OrderProcessor.process_transactions() — creates lots, closings, old chains
      4. chain_graph.derive_chains() — graph-based chain derivation
      5. GroupPersister.process_groups() — cross-order grouping with strategy labels
      6. net_opposing_equity_lots() — equity netting cleanup

    Parameters:
        db_manager: Database manager instance
        order_processor: OrderProcessor instance
        lot_manager: LotManager instance
        position_manager: PositionInventoryManager instance
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
    position_manager.clear_all_positions()
    if affected_underlyings:
        lot_manager.clear_all_lots(underlyings=affected_underlyings)
        logger.info(
            "Cleared position inventory and lots for %d affected underlyings",
            len(affected_underlyings),
        )
    else:
        lot_manager.clear_all_lots()
        logger.info("Cleared position inventory and lots for full reprocessing")

    # ── Step 2: Stage 2 — Order Assembly (stateless) ──────────────────
    assembly = assemble_orders(raw_transactions)
    orders_assembled = len(assembly.orders)
    logger.info("Stage 2: assembled %d orders", orders_assembled)

    # ── Step 3: Stage 3 — OrderProcessor (creates lots, closings, old chains)
    if affected_underlyings:
        all_chains: List[Chain] = []
        for underlying in affected_underlyings:
            underlying_txs = [
                tx for tx in raw_transactions
                if tx.get("underlying_symbol") == underlying
            ]
            if underlying_txs:
                chains_by_account = order_processor.process_transactions(underlying_txs)
                for chains in chains_by_account.values():
                    all_chains.extend(chains)
        logger.info(
            "Stage 3: incremental reprocessing created %d chains for %d underlyings",
            len(all_chains),
            len(affected_underlyings),
        )
    else:
        chains_by_account = order_processor.process_transactions(raw_transactions)
        all_chains = [
            chain
            for chains in chains_by_account.values()
            for chain in chains
        ]
        logger.info("Stage 3: full reprocessing created %d chains", len(all_chains))

    # ── Step 4: Stage 4 — Chain Graph (graph-based chain derivation) ──
    new_chains = derive_chains(db_manager, assembly.orders)
    chains_derived = len(new_chains)
    logger.info("Stage 4: derived %d chains via graph", chains_derived)

    # ── Step 5+6: Stages 5 & 6 — Group Manager (strategy + persistence)
    persister = GroupPersister(db_manager, lot_manager)
    groups_processed = persister.process_groups(new_chains)
    logger.info("Stage 6: processed %d groups", groups_processed)

    # ── Step 7: Equity netting ────────────────────────────────────────
    equity_lots_netted = net_opposing_equity_lots()
    if equity_lots_netted:
        logger.info("Equity netting: closed %d lot sides", equity_lots_netted)

    return PipelineResult(
        orders_assembled=orders_assembled,
        chains_derived=chains_derived,
        groups_processed=groups_processed,
        equity_lots_netted=equity_lots_netted,
    )
