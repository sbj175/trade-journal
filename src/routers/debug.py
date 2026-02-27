"""Debug routes — strategy inspection, cache debugging, reconciliation."""

from fastapi import APIRouter, Depends
from loguru import logger

from src.database.models import OrderChain
from src.database.db_manager import DatabaseManager
from src.models.strategy_detector import StrategyDetector
from src.dependencies import get_db, get_strategy_detector, get_current_user_id
from src.pipeline.order_assembler import assemble_orders
from src.pipeline.chain_graph import derive_chains
from src.services.sync_service import reconcile_positions_vs_chains

router = APIRouter()


@router.get("/api/reconcile")
async def get_reconciliation(user_id: str = Depends(get_current_user_id)):
    """Run position reconciliation and return results"""
    return await reconcile_positions_vs_chains()


@router.get("/api/debug/strategy/{chain_id}")
async def debug_strategy(chain_id: str, db: DatabaseManager = Depends(get_db), strategy_detector: StrategyDetector = Depends(get_strategy_detector), user_id: str = Depends(get_current_user_id)):
    """Debug strategy detection for a specific chain"""
    raw_transactions = db.get_raw_transactions()
    assembly = assemble_orders(raw_transactions)
    all_chains = derive_chains(db, assembly.orders)

    target_chain = None
    for chain in all_chains:
        if chain.chain_id == chain_id:
            target_chain = chain
            break

    if not target_chain:
        return {"error": f"Chain {chain_id} not found"}

    debug_info = {
        "chain_id": chain_id,
        "underlying": target_chain.underlying,
        "orders": len(target_chain.orders),
        "opening_orders": [],
        "debug_path": "graph_derived"
    }

    for order in target_chain.orders:
        if order.order_type.value == 'OPENING':
            order_info = {
                "order_id": order.order_id,
                "transactions": []
            }
            for tx in order.transactions:
                tx_info = {
                    "symbol": tx.symbol,
                    "action": tx.action,
                    "quantity": tx.quantity,
                    "option_type": tx.option_type,
                    "strike": tx.strike,
                    "has_option_type": tx.option_type is not None,
                    "underlying_symbol": tx.underlying_symbol
                }
                order_info["transactions"].append(tx_info)
            debug_info["opening_orders"].append(order_info)

    try:
        detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
        debug_info["detected_strategy"] = detected_strategy
    except Exception as e:
        debug_info["strategy_error"] = str(e)

    return debug_info


@router.get("/api/debug/cache-path/{chain_id}")
async def debug_cache_path(chain_id: str, db: DatabaseManager = Depends(get_db), strategy_detector: StrategyDetector = Depends(get_strategy_detector), user_id: str = Depends(get_current_user_id)):
    """Debug strategy detection using the EXACT same code path as cache update"""
    raw_transactions = db.get_raw_transactions()
    assembly = assemble_orders(raw_transactions)
    all_chains = derive_chains(db, assembly.orders)

    target_chain = None
    for chain in all_chains:
        if chain.chain_id == chain_id:
            target_chain = chain
            break

    if not target_chain:
        return {"error": f"Chain {chain_id} not found"}

    try:
        detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
        if detected_strategy is None:
            detected_strategy = "Unknown"
    except Exception as e:
        detected_strategy = "Unknown"

    return {
        "chain_id": chain_id,
        "underlying": target_chain.underlying,
        "strategy_from_cache_path": detected_strategy,
        "opening_orders": len([o for o in target_chain.orders if o.order_type.value == 'OPENING']),
        "total_orders": len(target_chain.orders)
    }


@router.get("/api/debug/cache-update/{chain_id}")
async def debug_cache_update(chain_id: str, db: DatabaseManager = Depends(get_db), strategy_detector: StrategyDetector = Depends(get_strategy_detector), user_id: str = Depends(get_current_user_id)):
    """Debug the full cache update process for a specific chain"""
    try:
        raw_transactions = db.get_raw_transactions()
        assembly = assemble_orders(raw_transactions)
        all_chains = derive_chains(db, assembly.orders)

        target_chain = None
        for chain in all_chains:
            if chain.chain_id == chain_id:
                target_chain = chain
                break

        if not target_chain:
            return {"error": f"Chain {chain_id} not found"}

        try:
            detected_strategy = strategy_detector.detect_chain_strategy(target_chain)
            if detected_strategy is None:
                detected_strategy = "Unknown"
        except Exception as e:
            detected_strategy = "Unknown"

        insert_params = {
            "chain_id": target_chain.chain_id,
            "underlying": target_chain.underlying,
            "account_number": target_chain.account_number,
            "opening_order_id": target_chain.orders[0].order_id if target_chain.orders else None,
            "strategy_type": detected_strategy,
            "opening_date": target_chain.opening_date,
            "closing_date": target_chain.closing_date,
            "chain_status": target_chain.status,
            "order_count": len(target_chain.orders)
        }

        with db.get_session() as session:
            row = session.query(OrderChain.strategy_type).filter(
                OrderChain.chain_id == chain_id
            ).first()
            current_db_strategy = row[0] if row else "NOT_FOUND"

        return {
            "chain_id": chain_id,
            "detected_strategy": detected_strategy,
            "would_insert": insert_params,
            "current_in_db": current_db_strategy,
            "opening_order_transactions": len(target_chain.orders[0].transactions) if target_chain.orders else 0
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
