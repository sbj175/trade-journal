"""
Admin API endpoints — all require X-Admin-Secret header (enforced by middleware).

Every query uses get_session(unscoped=True) to bypass tenant filtering.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException
from loguru import logger as loguru_logger
from pydantic import BaseModel
from sqlalchemy import func, text

from src.database.engine import get_engine, get_session
from src.database.models import (
    Account,
    AccountBalance,
    LotClosing,
    Order,
    OrderChain,
    OrderChainCache,
    OrderChainMember,
    OrderComment,
    OrderPosition,
    Position,
    PositionGroup,
    PositionGroupLot,
    PositionGroupTag,
    PositionLot,
    PositionNote,
    RawTransaction,
    StrategyTarget,
    SyncMetadata,
    Tag,
    User,
    UserCredential,
    WaitlistEntry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Lock to prevent concurrent VACUUM operations
_vacuum_lock = asyncio.Lock()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/db-health")
async def db_health():
    """PostgreSQL database health metrics."""
    try:
        engine = get_engine()
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}

    dialect = engine.dialect.name
    if dialect != "postgresql":
        return {"status": "error", "error": f"Unsupported dialect: {dialect}"}

    try:
        with get_session(unscoped=True) as session:
            # Connectivity + latency
            t0 = time.perf_counter()
            session.execute(text("SELECT 1"))
            query_latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            # Database size
            row = session.execute(text(
                "SELECT pg_database_size(current_database()), "
                "pg_size_pretty(pg_database_size(current_database()))"
            )).one()
            database_size_bytes = row[0]
            database_size = row[1]

            # Schema version
            try:
                version_row = session.execute(text(
                    "SELECT version_num FROM alembic_version LIMIT 1"
                )).first()
                schema_version = version_row[0] if version_row else None
            except Exception:
                schema_version = None

            # Table sizes + estimated row counts + dead tuples + autovacuum
            table_rows = session.execute(text("""
                SELECT
                    c.relname AS name,
                    COALESCE(s.n_live_tup, 0) AS rows,
                    COALESCE(s.n_dead_tup, 0) AS dead_tuples,
                    pg_total_relation_size(c.oid) AS size_bytes,
                    pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
                    s.last_autovacuum,
                    s.last_autoanalyze
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                ORDER BY pg_total_relation_size(c.oid) DESC
            """)).all()

            tables = [
                {
                    "name": r.name,
                    "rows": r.rows,
                    "size": r.size,
                    "size_bytes": r.size_bytes,
                    "dead_tuples": r.dead_tuples,
                    "last_autovacuum": r.last_autovacuum.isoformat() if r.last_autovacuum else None,
                    "last_autoanalyze": r.last_autoanalyze.isoformat() if r.last_autoanalyze else None,
                }
                for r in table_rows
            ]
            total_dead_tuples = sum(t["dead_tuples"] for t in tables)

            # Cache hit ratio (database-level)
            cache_row = session.execute(text("""
                SELECT
                    CASE WHEN (blks_hit + blks_read) > 0
                         THEN round(100.0 * blks_hit / (blks_hit + blks_read), 2)
                         ELSE 100 END AS cache_hit_ratio
                FROM pg_stat_database
                WHERE datname = current_database()
            """)).first()
            cache_hit_ratio = float(cache_row.cache_hit_ratio) if cache_row else None

            # Index hit ratio (aggregated from user tables)
            idx_row = session.execute(text("""
                SELECT
                    CASE WHEN (sum(idx_blks_hit) + sum(idx_blks_read)) > 0
                         THEN round(100.0 * sum(idx_blks_hit) / (sum(idx_blks_hit) + sum(idx_blks_read)), 2)
                         ELSE 100 END AS index_hit_ratio
                FROM pg_statio_user_indexes
            """)).first()
            index_hit_ratio = float(idx_row.index_hit_ratio) if idx_row else None

        # Connection pool (accessed outside session)
        pool = engine.pool
        connection_pool = {
            "pool_size": pool.size(),
            "max_overflow": engine.pool._max_overflow,
            "checked_out": pool.checkedout(),
            "checked_in": pool.checkedin(),
            "overflow": pool.overflow(),
        }

        return {
            "status": "ok",
            "dialect": dialect,
            "query_latency_ms": query_latency_ms,
            "database_size": database_size,
            "database_size_bytes": database_size_bytes,
            "schema_version": schema_version,
            "cache_hit_ratio": cache_hit_ratio,
            "index_hit_ratio": index_hit_ratio,
            "total_dead_tuples": total_dead_tuples,
            "connection_pool": connection_pool,
            "tables": tables,
        }

    except Exception as exc:
        logger.exception("DB health check failed")
        return {"status": "error", "error": str(exc)}


class VacuumRequest(BaseModel):
    table: str


@router.post("/db-maintenance/vacuum")
async def vacuum_analyze(req: VacuumRequest):
    """Run VACUUM ANALYZE on a specific table or the entire database."""
    try:
        engine = get_engine()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if engine.dialect.name != "postgresql":
        raise HTTPException(status_code=400, detail="VACUUM is only supported on PostgreSQL")

    # Validate table name against actual public-schema tables
    if req.table != "all":
        with get_session(unscoped=True) as session:
            valid_tables = {
                row[0]
                for row in session.execute(text(
                    "SELECT relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
                )).all()
            }
        if req.table not in valid_tables:
            raise HTTPException(status_code=400, detail=f"Unknown table: {req.table}")

    # Only one VACUUM at a time
    if _vacuum_lock.locked():
        raise HTTPException(status_code=409, detail="A VACUUM operation is already in progress")

    async with _vacuum_lock:
        t0 = time.perf_counter()
        try:
            raw_conn = engine.raw_connection()
            try:
                raw_conn.set_isolation_level(0)  # autocommit — required for VACUUM
                cursor = raw_conn.cursor()
                if req.table == "all":
                    cursor.execute("VACUUM ANALYZE")
                else:
                    # Table name is validated against pg_class whitelist above
                    cursor.execute(f"VACUUM ANALYZE {req.table}")
                cursor.close()
            finally:
                raw_conn.close()
        except Exception as exc:
            logger.exception("VACUUM ANALYZE failed")
            raise HTTPException(status_code=500, detail=str(exc))

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info("VACUUM ANALYZE %s completed in %s ms", req.table, duration_ms)
        return {"status": "ok", "table": req.table, "duration_ms": duration_ms}


@router.get("/stats")
async def stats():
    """Summary metrics for the dashboard cards."""
    with get_session(unscoped=True) as session:
        total_users = session.query(func.count(User.id)).scalar()
        active_users = (
            session.query(func.count(User.id))
            .filter(User.is_active == True)
            .scalar()
        )
        tt_connected = (
            session.query(func.count(UserCredential.id))
            .filter(UserCredential.is_active == True)
            .scalar()
        )
        total_accounts = session.query(func.count(Account.id)).scalar()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "tt_connected": tt_connected,
        "total_accounts": total_accounts,
    }


@router.get("/users")
async def list_users():
    """Detailed per-user table data."""
    with get_session(unscoped=True) as session:
        users = session.query(User).order_by(User.created_at.desc()).all()
        result = []

        for user in users:
            uid = user.id

            # Account count
            account_count = (
                session.query(func.count(Account.id))
                .filter(Account.user_id == uid)
                .scalar()
            )

            # TT connected?
            cred = (
                session.query(UserCredential)
                .filter(
                    UserCredential.user_id == uid,
                    UserCredential.is_active == True,
                )
                .first()
            )
            tt_connected = cred is not None

            # Transaction count
            txn_count = (
                session.query(func.count(RawTransaction.row_id))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )

            # Days of history: difference between earliest and latest transaction
            earliest = (
                session.query(func.min(RawTransaction.executed_at))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )
            latest = (
                session.query(func.max(RawTransaction.executed_at))
                .filter(RawTransaction.user_id == uid)
                .scalar()
            )
            if earliest and latest:
                from datetime import datetime

                try:
                    fmt = "%Y-%m-%dT%H:%M:%S" if "T" in earliest else "%Y-%m-%d %H:%M:%S"
                    d1 = datetime.strptime(earliest[:19], fmt)
                    d2 = datetime.strptime(latest[:19], fmt)
                    days_of_history = (d2 - d1).days
                except (ValueError, TypeError):
                    days_of_history = None
            else:
                days_of_history = None

            # Last sync
            last_sync_row = (
                session.query(SyncMetadata)
                .filter(
                    SyncMetadata.user_id == uid,
                    SyncMetadata.key == "last_sync_timestamp",
                )
                .first()
            )
            last_sync = last_sync_row.value if last_sync_row else None

            # Position count
            position_count = (
                session.query(func.count(Position.id))
                .filter(Position.user_id == uid)
                .scalar()
            )

            # Strategies by account (from PositionGroup which has strategy labels)
            strategy_rows = (
                session.query(
                    PositionGroup.account_number,
                    PositionGroup.strategy_label,
                    func.count(PositionGroup.id),
                )
                .filter(PositionGroup.user_id == uid)
                .group_by(PositionGroup.account_number, PositionGroup.strategy_label)
                .all()
            )
            accounts_detail = {}
            for acct, strategy, count in strategy_rows:
                if acct not in accounts_detail:
                    accounts_detail[acct] = []
                accounts_detail[acct].append({
                    "strategy": strategy or "Unknown",
                    "count": count,
                })

            result.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "last_login_at": user.updated_at,
                    "accounts": account_count,
                    "tt_connected": tt_connected,
                    "txn_count": txn_count,
                    "days_of_history": days_of_history,
                    "last_sync": last_sync,
                    "positions": position_count,
                    "accounts_detail": accounts_detail,
                }
            )

        return result


@router.post("/users/{user_id}/reset-sync")
async def reset_sync(user_id: str):
    """Delete all SyncMetadata rows for a user, forcing a full re-sync."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        deleted = (
            session.query(SyncMetadata)
            .filter(SyncMetadata.user_id == user_id)
            .delete()
        )
        logger.info("Reset sync for user %s: deleted %d metadata rows", user_id, deleted)

    return {"status": "ok", "deleted_rows": deleted}


# Tables containing user trading data (order matters for FK constraints)
_USER_DATA_TABLES = [
    LotClosing,
    PositionGroupLot,
    PositionGroupTag,
    PositionGroup,
    PositionLot,
    OrderChainCache,
    OrderChainMember,
    OrderChain,
    OrderPosition,
    OrderComment,
    Order,
    PositionNote,
    Position,
    AccountBalance,
    RawTransaction,
    SyncMetadata,
    StrategyTarget,
    Tag,
    Account,
    UserCredential,
]


@router.delete("/users/{user_id}/data")
async def delete_user_data(user_id: str):
    """Hard-delete all trading data for a user (keeps the User row)."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        totals = {}
        for model in _USER_DATA_TABLES:
            count = (
                session.query(model)
                .filter(model.user_id == user_id)
                .delete()
            )
            if count > 0:
                totals[model.__tablename__] = count

        logger.info(
            "Deleted all data for user %s (%s): %s",
            user_id,
            user.email,
            totals,
        )

    return {"status": "ok", "deleted": totals}


@router.get("/waitlist")
async def list_waitlist():
    """Waitlist entries, newest first."""
    with get_session(unscoped=True) as session:
        entries = (
            session.query(WaitlistEntry)
            .order_by(WaitlistEntry.created_at.desc())
            .all()
        )
        return [
            {
                "id": e.id,
                "email": e.email,
                "created_at": e.created_at,
            }
            for e in entries
        ]


@router.post("/users/{user_id}/reprocess-chains")
async def reprocess_chains(user_id: str):
    """Reprocess order chains for a specific user from their raw transactions."""
    from src.database.db_manager import DatabaseManager
    from src.database.tenant import set_current_user_id
    from src.models.lot_manager import LotManager
    from src.pipeline.orchestrator import reprocess
    from src.services.chain_service import update_chain_cache

    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    # Scope all subsequent ORM operations to this user
    set_current_user_id(user_id)

    try:
        import os
        admin_db = DatabaseManager(db_url=os.getenv("DATABASE_URL"))
        admin_lot_manager = LotManager(admin_db)

        raw_transactions = admin_db.get_raw_transactions()
        loguru_logger.info(
            "Admin reprocess for user {}: {} raw transactions",
            user_id, len(raw_transactions),
        )

        result = reprocess(admin_db, admin_lot_manager, raw_transactions)

        if result.chains:
            await update_chain_cache(result.chains, db=admin_db)

        loguru_logger.info(
            "Admin reprocess completed for user {}: {} orders, {} chains",
            user_id, result.orders_assembled, result.chains_derived,
        )

        return {
            "status": "ok",
            "orders_processed": result.orders_assembled,
            "chains_created": result.chains_derived,
        }
    except Exception as exc:
        loguru_logger.error("Reprocess failed for user {}: {}", user_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Hard-delete a user and all their trading data."""
    with get_session(unscoped=True) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        email = user.email

        # Delete all tenant-scoped data first (FK constraints)
        totals = {}
        for model in _USER_DATA_TABLES:
            count = (
                session.query(model)
                .filter(model.user_id == user_id)
                .delete()
            )
            if count > 0:
                totals[model.__tablename__] = count

        # Delete the User row itself
        session.delete(user)
        totals["users"] = 1

        logger.info(
            "Deleted user %s (%s) and all data: %s",
            user_id,
            email,
            totals,
        )

    return {"status": "ok", "deleted": totals}
