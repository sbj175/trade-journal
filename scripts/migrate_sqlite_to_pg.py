#!/usr/bin/env python3
"""
Migrate all data from an existing SQLite database to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_pg.py [--sqlite PATH] [--pg-url URL]

Defaults:
    --sqlite   trade_journal.db
    --pg-url   postgresql://optionledger:optionledger@localhost:5432/optionledger

Tables are migrated in FK dependency order.  The PostgreSQL schema must
already exist (run the app once or `alembic upgrade head` first).
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Base,
    Account, AccountBalance, Position,
    Order, OrderPosition,
    OrderChain, OrderChainMember, OrderChainCache,
    RawTransaction, SyncMetadata, QuoteCache, StrategyTarget,
    PositionLot, LotClosing, ChainMerge,
    PositionGroup, PositionGroupLot,
    PositionsInventory,
    OrderComment, PositionNote,
)

# Tables in FK dependency order (parents before children).
# position_lots is self-referential — we insert with derived_from_lot_id=NULL
# first, then do an UPDATE pass to set the FK.
MIGRATION_ORDER = [
    Account,
    AccountBalance,
    SyncMetadata,
    QuoteCache,
    StrategyTarget,
    RawTransaction,
    ChainMerge,
    OrderComment,
    PositionNote,
    PositionsInventory,
    Order,
    OrderChain,
    Position,
    OrderPosition,
    OrderChainMember,
    OrderChainCache,
    PositionGroup,
    PositionGroupLot,
    PositionLot,       # self-referential FK handled below
    LotClosing,
]

BATCH_SIZE = 500


def migrate(sqlite_path: str, pg_url: str):
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    pg_engine = create_engine(pg_url)

    SrcSession = sessionmaker(bind=sqlite_engine)
    DstSession = sessionmaker(bind=pg_engine)

    # Ensure PG schema exists
    Base.metadata.create_all(pg_engine)

    src = SrcSession()
    dst = DstSession()

    total_rows = 0

    try:
        for model in MIGRATION_ORDER:
            table_name = model.__tablename__
            columns = [col.key for col in model.__table__.columns]

            # Read all rows from SQLite
            rows = src.query(model).all()
            if not rows:
                print(f"  {table_name}: 0 rows (skipped)")
                continue

            # For position_lots: temporarily null out derived_from_lot_id
            # to avoid FK violations during insert
            deferred_updates = []
            is_position_lots = (model is PositionLot)

            # Batch insert into PostgreSQL
            count = 0
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                for row in batch:
                    data = {col: getattr(row, col) for col in columns}

                    if is_position_lots and data.get("derived_from_lot_id"):
                        deferred_updates.append(
                            (data["id"], data["derived_from_lot_id"])
                        )
                        data["derived_from_lot_id"] = None

                    dst.merge(model(**data))
                    count += 1

                dst.flush()

            dst.commit()

            # Deferred: set derived_from_lot_id for self-referential FK
            if deferred_updates:
                for lot_id, derived_id in deferred_updates:
                    dst.execute(
                        text("UPDATE position_lots SET derived_from_lot_id = :derived WHERE id = :id"),
                        {"derived": derived_id, "id": lot_id},
                    )
                dst.commit()
                print(f"  {table_name}: {count} rows ({len(deferred_updates)} deferred FK updates)")
            else:
                print(f"  {table_name}: {count} rows")

            total_rows += count

    except Exception as e:
        dst.rollback()
        print(f"\nERROR: Migration failed: {e}")
        raise
    finally:
        src.close()
        dst.close()

    print(f"\nMigration complete: {total_rows} total rows across {len(MIGRATION_ORDER)} tables")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument("--sqlite", default="trade_journal.db",
                        help="Path to SQLite database (default: trade_journal.db)")
    parser.add_argument("--pg-url",
                        default="postgresql://optionledger:optionledger@localhost:5432/optionledger",
                        help="PostgreSQL connection URL")
    args = parser.parse_args()

    if not Path(args.sqlite).exists():
        print(f"ERROR: SQLite database not found: {args.sqlite}")
        sys.exit(1)

    print(f"Migrating: {args.sqlite} → {args.pg_url.split('@')[-1]}")
    print()
    migrate(args.sqlite, args.pg_url)


if __name__ == "__main__":
    main()
