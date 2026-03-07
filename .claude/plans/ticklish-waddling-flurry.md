# OPT-106: PostgreSQL Migration (Local Docker)

## Context

OPT-105 (SQLAlchemy ORM migration) is complete — all 314 raw SQL queries are now SQLAlchemy ORM. The next step in the SaaS conversion is making the app work with PostgreSQL so it can eventually run as a multi-tenant service. This phase adds PostgreSQL as an alternative backend via Docker while keeping SQLite as the default for backward compatibility. The app stays local (not containerized) — only PostgreSQL runs in Docker.

## Key Decisions

- **Dual dialect**: Both SQLite and PostgreSQL supported. `DATABASE_URL` env var selects the backend. No `DATABASE_URL` = SQLite default.
- **Docker scope**: Only PostgreSQL in Docker. App runs natively via `start.sh`.
- **Tests**: Continue using SQLite for speed. Optional `TEST_DATABASE_URL` for PostgreSQL CI testing.

## Phase 1: Engine and Configuration

Make engine initialization dialect-aware. Zero behavior change for existing SQLite users.

**`src/database/engine.py`** — Rewrite `init_engine()`:
- Change signature from `init_engine(db_path: str)` to `init_engine(db_url: str = None)`
- If `db_url` is None, read `DATABASE_URL` from env; if that's missing, default to `sqlite:///trade_journal.db`
- Detect dialect from URL prefix (`sqlite` vs `postgresql`)
- SQLite: keep `check_same_thread=False` and PRAGMA foreign_keys listener
- PostgreSQL: use `pool_size=5, max_overflow=10`, no SQLite-specific args
- Store dialect in module-level `_dialect` variable
- Export `get_dialect() -> str` function
- Export `dialect_insert(model)` function that returns the correct dialect's `insert()` (resolved once at init, not per-call)

**`src/database/db_manager.py`** — Update init:
- Change `__init__(self, db_path="trade_journal.db")` to `__init__(self, db_url=None)`
- In `initialize_database()`, change `sa_engine.init_engine(self.db_path)` to `sa_engine.init_engine(self.db_url)`

**`src/dependencies.py`** — Read from env:
```python
import os
db = DatabaseManager(db_url=os.getenv("DATABASE_URL"))
```

**`.env`** — Add commented-out template:
```
# DATABASE_URL=postgresql://optionledger:optionledger@localhost:5432/optionledger
```

**`tests/conftest.py`** — Update fixture to pass `db_url=` instead of `db_path=`:
```python
db_manager = DatabaseManager(db_url=f"sqlite:///{db_path}")
```

**Test gate:** All 71 tests pass (SQLite, no behavior change).

## Phase 2: Dialect-Agnostic Upserts

Replace all 22 `sqlite_insert` call sites with `dialect_insert` from engine.py.

The `on_conflict_do_update()` and `on_conflict_do_nothing()` APIs are identical between SQLite and PostgreSQL dialects, so this is a mechanical find-and-replace.

**Per-file changes (6 files, 22 call sites):**

| File | Sites | Change |
|------|-------|--------|
| `src/database/db_manager.py` | 7 | Replace inline imports + calls |
| `src/services/chain_service.py` | 3 | Replace module-level import + calls |
| `src/services/ledger_service.py` | 4 | Replace module-level import + calls |
| `src/models/pnl_calculator.py` | 1 | Replace module-level import + call |
| `src/models/order_models.py` | 2 | Replace inline imports + calls |
| `src/routers/ledger.py` | 1 | Replace inline import + call |

For each file:
1. Remove: `from sqlalchemy.dialects.sqlite import insert as sqlite_insert`
2. Add: `from src.database.engine import dialect_insert`
3. Replace: `sqlite_insert(Model)` with `dialect_insert(Model)`

**Test gate:** All 71 tests pass. Grep confirms zero remaining `sqlite_insert` references.

## Phase 3: Remove Legacy sqlite3 Code

**`src/database/db_manager.py`:**
- Delete `_add_transaction_columns()` method (lines 101-289) — all columns already in ORM models
- Delete `get_connection()` method (lines 37-49) — no callers remain
- Delete `_seed_default_strategy_targets(self, cursor)` — ORM version already exists
- Remove `import sqlite3`
- Remove `self._add_transaction_columns()` call from `initialize_database()`

**`tests/conftest.py`:**
- Remove the `_add_transaction_columns` stub workaround (lines 33-37). With the method gone, `initialize_database()` is clean ORM-only.

**Test gate:** All 71 tests pass.

## Phase 4: Alembic Dual-Dialect Support

**`alembic.ini`:**
- Remove hardcoded `sqlalchemy.url = sqlite:///trade_journal.db`
- URL now set programmatically in env.py

**`alembic/env.py`:**
- Read URL from `DATABASE_URL` env var, fall back to `sqlite:///trade_journal.db`
- Make `render_as_batch` conditional: `True` for SQLite, `False` for PostgreSQL
- Make SQLite type comparison function conditional (only for SQLite)

**Test gate:** `alembic upgrade head` works on both SQLite and PostgreSQL.

## Phase 5: Docker Compose + Dependencies

**`docker-compose.yml`** (new):
- PostgreSQL 16 Alpine image
- User/password/database: `optionledger`
- Port 5432 exposed
- Named volume `pgdata` for persistence
- Healthcheck with `pg_isready`

**`requirements.txt`:**
- Add `psycopg2-binary>=2.9`

**Test gate:** `docker compose up -d` starts PostgreSQL. App connects with `DATABASE_URL` set. Tables created.

## Phase 6: Data Migration Script

**`scripts/migrate_sqlite_to_pg.py`** (new):
- Reads all data from existing SQLite `trade_journal.db`
- Bulk-inserts into PostgreSQL (respecting FK dependency order)
- Reports row counts per table

## Phase 7: Documentation

Update **CLAUDE.md** with:
- How to run with PostgreSQL (`docker compose up -d`, uncomment `DATABASE_URL`)
- How to migrate existing SQLite data
- How to switch back to SQLite (comment out `DATABASE_URL`)

## Files Summary

| Category | Files |
|----------|-------|
| **Modified** | `src/database/engine.py`, `src/database/db_manager.py`, `src/dependencies.py`, `tests/conftest.py`, `alembic.ini`, `alembic/env.py`, `requirements.txt`, `.env`, `CLAUDE.md` |
| **Modified (upsert)** | `src/services/chain_service.py`, `src/services/ledger_service.py`, `src/models/pnl_calculator.py`, `src/models/order_models.py`, `src/routers/ledger.py` |
| **New** | `docker-compose.yml`, `scripts/migrate_sqlite_to_pg.py` |

## Verification

After each phase: `pytest tests/ -v` — all 71 tests pass (SQLite).

End-to-end PostgreSQL verification (after Phase 5):
1. `docker compose up -d`
2. Uncomment `DATABASE_URL` in `.env`
3. Start app with `./start.sh`
4. Confirm tables created in PostgreSQL
5. Run a sync, verify chains/positions appear in UI
6. Run `scripts/migrate_sqlite_to_pg.py` to test data migration from existing SQLite
