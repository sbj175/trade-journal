# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What is OptionLedger?

A web application for options traders using Tastytrade. It imports, organizes, and analyzes trading data — grouping transactions into position groups, detecting strategies, tracking rolls, and providing real-time P&L.

**Stack**: FastAPI backend, Vue 3 SPA (Vite + Tailwind), SQLAlchemy ORM (SQLite default, PostgreSQL via Docker), WebSocket for live quotes.

**Data flow**:
```
Tastytrade API → Import → Pipeline (8 stages) → Database → Web Interface
Live Market Data → WebSocket → Real-time Position Updates → Dashboard
```

## Running the Application

```bash
docker compose up -d  # app (8000), admin (8002), postgres, redis
```

Default route `/` redirects to `/positions/options`.

### Alembic Migrations

The entrypoint runs migrations automatically on container start. To run them manually inside the running app container:

```bash
docker compose exec app alembic upgrade head
# Fresh DB path (the entrypoint falls back to this automatically if upgrade fails):
docker compose exec app alembic stamp head
```

## Architecture

### Backend Structure

```
src/
├── dependencies.py          # FastAPI deps (get_current_user_id, get_tastytrade_client)
├── schemas.py               # Pydantic schemas
├── sync_trades.py           # Legacy sync entrypoint
├── api/
│   ├── tastytrade_client.py # OAuth2 auth, async methods, quote caching (30s TTL)
│   └── tiingo_client.py     # Historical price + volatility data
├── auth/
│   ├── jwt_validator.py     # Supabase JWT validation (HS256)
│   └── user_provisioning.py # Auto-create User rows on first login
├── database/
│   ├── engine.py            # init_engine(), dialect_insert(), dual-dialect support
│   ├── models.py            # 24 SQLAlchemy models
│   ├── db_manager.py        # DatabaseManager, get_session()
│   └── tenant.py            # Multi-tenant filtering (user_id scoping, ContextVar)
├── models/
│   ├── lot_manager.py       # LotManager — lot creation and closing logic
│   ├── order_models.py      # Enums (OrderType, OrderStatus) and domain types
│   ├── order_processor.py   # OrderProcessor — transaction grouping engine
│   ├── pnl_calculator.py    # PnLCalculator — P&L with roll chain handling
│   └── strategy_detector.py # StrategyDetector — option strategy identification
├── pipeline/
│   ├── orchestrator.py      # 8-stage pipeline orchestration
│   ├── order_assembler.py   # Stage: assemble orders from transactions
│   ├── roll_splitter.py     # Stage: split orders that mix opens and closes
│   ├── position_ledger.py   # Stage: build position lots
│   ├── group_manager.py     # Stage: create/update position groups
│   ├── pnl_events.py        # Stage: populate pnl_events fact table
│   ├── roll_chain_summary.py # Stage: populate roll_chain_summaries
│   └── strategy_engine/     # Pattern-based strategy recognition
│       ├── recognizer.py    # Main recognizer entry point
│       ├── adapters.py      # Data adapters
│       ├── constants.py     # Strategy constants
│       ├── types.py         # Type definitions
│       └── patterns_*.py    # Pattern modules (single, vertical, combo, multi, calendar)
├── routers/                 # 13 FastAPI routers
│   ├── accounts.py          # /api/accounts, /api/account-balances
│   ├── auth.py              # /api/auth/config, /api/waitlist
│   ├── health.py            # /api/health, /api/connection/*
│   ├── ledger.py            # /api/ledger, /api/ledger/groups/*, /api/ledger/move-lots
│   ├── notes.py             # /api/order-comments, /api/position-notes
│   ├── pages.py             # /login, /beta-full, catch-all SPA route
│   ├── positions.py         # /api/positions/cached, /api/positions, /api/open-chains
│   ├── quotes.py            # /api/quotes
│   ├── reports.py           # /api/dashboard, /api/performance/*, /api/reports/*
│   ├── settings.py          # /api/settings/targets, /api/settings/credentials
│   ├── sync.py              # /api/sync, /api/reprocess, /api/sync/initial, /api/reconcile
│   ├── tags.py              # /api/tags, /api/tags/{id}
│   └── tastytrade_oauth.py  # /api/auth/tastytrade/authorize, /auth/tastytrade/callback
├── services/
│   ├── ledger_service.py    # Ledger business logic
│   ├── report_service.py    # Report/dashboard queries
│   ├── sync_service.py      # Sync orchestration
│   ├── price_service.py     # Historical price fetch/cache
│   └── volatility_service.py # IV/realized-vol computation
└── utils/
    ├── auth_manager.py      # ConnectionManager singleton (per-user pool, LRU, 60-min TTL)
    ├── credential_encryption.py  # Fernet encrypt/decrypt
    └── premium.py           # Option premium helpers
```

### Pipeline (8 stages)

The sync pipeline (`src/pipeline/orchestrator.py`) processes data in order:
1. **Fetch + save** — pull transactions from Tastytrade API and persist raw rows
2. **Assemble orders** — group raw transactions into `Order` objects (`order_assembler.py`)
3. **Split rolling orders** — orders that mix opens and closes get split (`roll_splitter.py`)
4. **Lot processing** — build position lots from orders (`LotManager`, `position_ledger.py`); strategy detection runs here via `strategy_engine/`
5. **Equity netting** — close out equity lot sides
6. **Process groups** — create/update position groups (`GroupManager`, `group_manager.py`)
7. **Populate pnl_events** — denormalized fact table for time-based P&L reporting (`pnl_events.py`)
8. **Populate roll_chain_summaries** — per-chain aggregates (`roll_chain_summary.py`)

### Database Models (24 tables)

**Core data**: Account, AccountBalance, Position, RawTransaction, SyncMetadata, QuoteCache (no user_id)
**Order system**: OrderChain, OrderChainCache, OrderComment, RollChainSummary
**Position model**: PositionLot, LotClosing, PositionGroup, PositionGroupLot
**P&L**: PnlEvent (denormalized fact table)
**Market data**: HistoricalPrice, SymbolVolatilityMetric
**User/auth**: User, UserCredential, WaitlistEntry
**Config**: StrategyTarget, Tag, PositionGroupTag, PositionNote

### Frontend Structure

Vue 3 SPA with Vue Router, Pinia stores, `<script setup>` composition API. Vite builds from `frontend/src/main.js` → `static/dist/`.

```
frontend/src/
├── main.js, App.vue           # SPA entry + root component
├── router/index.js            # Routes + auth/tastytrade navigation guards
├── stores/                    # Pinia stores
│   ├── accounts.js            # Selected account, account list (localStorage)
│   ├── auth.js                # Auth state, user email, feature flags
│   ├── balances.js            # Account balance snapshots
│   ├── market.js              # Market status, expanded popover
│   ├── quotes.js              # Live option quote cache
│   ├── sync.js                # Sync progress, toast summary
│   └── targets.js             # Strategy targets (moved out of local state)
├── composables/               # ~20 use*.js composables (useLedgerGroups, usePositionsData, useReportsFilters, etc.)
├── components/                # Shared components
│   ├── NavBar.vue             # Top nav, mobile drawer, theme toggle
│   ├── GlobalToolbar.vue      # Sync, market, account selector, filter/overview toggles
│   ├── BaseButton.vue, BaseIcon.vue  # Primitives
│   ├── Detail.vue             # Position detail page component
│   ├── RollChainModal.vue, StreamingPrice.vue, DateFilter.vue, InfoPopover.vue, ConfirmModal.vue
│   ├── PositionsDesktopHeader/Row.vue, PositionsMobileCard.vue, PositionsExpandedPanel.vue, PositionsRollAnalysis.vue
│   ├── EquitiesDesktopHeader/Row.vue, EquitiesMobileCard.vue
│   ├── LedgerDesktopHeader/Row.vue, LedgerMobileCard.vue, LedgerFilters.vue
│   ├── ReportsSummaryCards.vue, ReportsBreakdownTable.vue, ReportsFilters.vue
│   └── Settings{Accounts,Alerts,Connection,Import,Privacy,Tags,Targets}.vue
├── layouts/DefaultLayout.vue  # Shared nav + <router-view>
├── lib/                       # Shared utilities
│   ├── constants.js, design-tokens.js, formatters.js, rules.js, math.js
│   ├── blackScholes.js, riskCalculations.js
│   └── {positions,equities,ledger}DesktopCols.js  # CSS Grid column definitions
├── styles/main.css            # Tailwind + theme CSS custom properties (dark default, :root.light override)
└── pages/                     # Each page has index.vue + per-page logic
    ├── positions/             # /positions/options — options with live quotes, WebSocket
    ├── positions-equities/    # /positions/equities — equity positions
    ├── ledger/                # /ledger — position groups, lots, group management
    ├── reports/               # /reports — strategy breakdown, performance (pnl_events)
    ├── risk/                  # /risk — portfolio Greeks, Black-Scholes, ApexCharts
    ├── settings/              # /settings — OAuth, connection, tags, targets, preferences
    ├── privacy/               # /privacy — privacy policy (no auth)
    └── components/            # /components — design system showcase (no auth)
```

Page `index.vue` files are thin — they wire up composables, stores, and sub-components. Composables under `composables/` hold the data/logic (`usePositionsData`, `useLedgerGroups`, `useReportsFilters`, `useRiskCharts`, `useSettingsConnection`, etc.).

**Standalone page**: Login (`static/login.html`) — Supabase auth via Alpine.js (only when auth enabled).

### Routes

| Path | Auth | Tastytrade | Description |
|------|------|-----------|-------------|
| `/positions/options` | Y | Y | Options positions with live P&L |
| `/positions/equities` | Y | Y | Equity positions |
| `/ledger` | Y | Y | Position groups and lots |
| `/reports` | Y | Y | Performance reports |
| `/risk` | Y | Y | Portfolio Greeks and risk |
| `/settings` | Y | N | Configuration |
| `/privacy` | N | N | Privacy policy |
| `/components` | N | N | Design system |

### Docker Compose Services

- **app** — FastAPI on port 8000
- **admin** — admin_app.py on port 8002
- **postgres** — PostgreSQL 16 with healthcheck
- **redis** — Redis 7 with healthcheck (provisioned but not yet wired into code)

## Multi-Tenancy (user_id Scoping)

Every data table (except `quote_cache`) has a `user_id` column for multi-user support.

- **`src/database/tenant.py`**: SQLAlchemy event listeners auto-append `WHERE user_id = ?` on SELECTs and auto-set `user_id` on new objects
- **`get_session(user_id=None)`**: Stores user_id in `session.info['user_id']`, defaults to `DEFAULT_USER_ID`
- **`dialect_insert()` calls**: Bypass ORM events — must include `user_id` in `.values()` explicitly
- **`get_current_user_id()`** in `src/dependencies.py`: Validates JWT and returns authenticated user ID

## Authentication

### Tastytrade API (OAuth2)

- Uses tastytrade SDK v12 (async-only) with OAuth2
- Credentials in `.env` (`TASTYTRADE_PROVIDER_SECRET`, `TASTYTRADE_REFRESH_TOKEN`) or per-user in `user_credentials` table
- `ConnectionManager` singleton with per-user connection pool (LRU, max 50, 60-min TTL)
- Use `get_tastytrade_client` FastAPI dependency for endpoints needing the client

### Tastytrade OAuth2 Authorization Code Flow

When auth is enabled, users connect via redirect flow: click "Connect to Tastytrade" → redirect to Tastytrade → authorize → redirect back with credentials stored automatically.

- **`src/routers/tastytrade_oauth.py`**: authorize, callback, disconnect endpoints
- Callback endpoint is PUBLIC (receives redirect from Tastytrade); state parameter is Fernet-encrypted `{user_id, timestamp}`
- Auth-code-flow users have `encrypted_provider_secret = NULL` — app-level client_secret from env is used

```
TASTYTRADE_CLIENT_ID=<uuid>
TASTYTRADE_CLIENT_SECRET=<secret>
TASTYTRADE_REDIRECT_URI=http://localhost:8000/auth/tastytrade/callback
```

### Supabase Auth (optional)

When `SUPABASE_JWT_SECRET` is set, auth is enforced on all `/api/*` data endpoints. When not set, app works as single-user local app.

- All `/api/*` data endpoints must have `user_id: str = Depends(get_current_user_id)`
- Public endpoints (health, `/api/auth/config`) must NOT use the dependency
- Frontend uses `Auth.authFetch()` for authenticated requests
- WebSocket passes token as `?token=JWT` query parameter
- New pages: register in `frontend/src/router/index.js` with `meta: { requiresAuth: true }`
- Data claim: `/api/auth/claim-data` migrates DEFAULT_USER_ID data to authenticated user (one-time)

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_JWT_SECRET=your-secret
CREDENTIAL_ENCRYPTION_KEY=<Fernet key>
```

## Security

- Auth disabled: credentials in local `.env` (gitignored)
- Auth enabled: credentials encrypted at rest with Fernet in `user_credentials`
- JWT validation is local (no network calls)
- Never commit: `.env`, `*.db`, credentials

## Development Workflow

Every code change must follow this process:

### 1. Linear Issue Required
- Every change must be associated with a Linear issue — use an existing one or create a new one before starting work
- When I refer to "Issues" I am referring to the issues, bugs, enhancements, etc. that are kept in Linear
- Don't ask for permission to read or write to Linear - just do it
- When creating a new issue, always assign it to me (Steve Johnson)
- Sometimes there will be issues labeled "Research"
  - Update Research issues with your findings in the comments

### 2. Git Workflow
- **Branch per task**: Create a feature branch from `main` for each issue (e.g., `opt-70-feature-name`)
- **Commit frequently**: Make meaningful commits as you work, not one giant commit at the end
- **Merge to main when done**: After changes are tested, merge the branch back to `main`

### 3. Linear Issue Lifecycle
- **Starting work**: Update the issue status to "In Progress"
- **During work**: Update the issue comments in Linear with progress notes or decisions made
- **Code complete**: Change status to "In Review" if you believe the issue is fixed or completed
- **After merge to main**: Mark the issue as "Done"

## Screenshot References

When I reference an image like `img_88`, `img_12`, etc., resolve it to `screenshots/img_88.png` (relative to project root) and read the file.
