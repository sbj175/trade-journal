# OptionLedger

A web application for options traders using Tastytrade. Imports your trade history, groups transactions into position chains, detects multi-leg strategies, tracks rolls, and shows real-time P&L across the entire lifecycle of every trade.

## Features

- **Automatic trade recognition** — multi-leg strategies (iron condors, verticals, calendars, strangles, etc.) are grouped into chains. Rolls and adjustments link into the original position so cost basis carries forward.
- **Live P&L** — WebSocket quote feed drives per-position mark-to-market on the Options and Equities pages.
- **Roll chain analysis** — full timeline of openings, rolls, adjustments, and closings per position group.
- **Reports** — time-filtered P&L reporting by strategy and symbol, backed by a denormalized `pnl_events` fact table.
- **Ledger** — historical position groups with tags, notes, and lot management.
- **Dark and light themes** — warm linen light palette for daytime reading, dark default for night.
- **Multi-account support** — account selector in the global toolbar; balances and positions scope to selected account.

## Tech Stack

- **Backend**: FastAPI (Python 3.11+), SQLAlchemy, Alembic migrations
- **Frontend**: Vue 3 (Composition API) + Vite + Tailwind CSS
- **Database**: PostgreSQL 16 (via Docker); SQLite supported as a dev fallback
- **Cache**: Redis 7 provisioned for future use (quote cache, reports aggregation, job queue) — not yet wired up
- **Auth**: Supabase JWT (optional — single-user mode works without it)
- **Broker integration**: Tastytrade OAuth2 via the official `tastytrade` SDK

## Prerequisites

- Docker and Docker Compose
- A Tastytrade account
- A Tastytrade OAuth2 application (my.tastytrade.com → Manage → My Profile → API → OAuth Applications)

## Quick Start

```bash
git clone https://github.com/sbj175/optionledger.git
cd optionledger
cp .env.example .env
# edit .env — see Configuration below
docker compose up -d
```

Open `http://localhost:8000`. The default route redirects to `/positions/options`.

## Configuration

All configuration lives in `.env`. The essentials:

```env
# Tastytrade OAuth2 (required)
TASTYTRADE_CLIENT_ID=<uuid>
TASTYTRADE_CLIENT_SECRET=<secret>
TASTYTRADE_REDIRECT_URI=http://localhost:8000/auth/tastytrade/callback

# Postgres (used by docker-compose)
POSTGRES_PASSWORD=<pick-one>
DATABASE_URL=postgresql://optionledger:${POSTGRES_PASSWORD}@postgres:5432/optionledger

# Fernet key for encrypting per-user credentials at rest
CREDENTIAL_ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Optional — display timezone
TIMEZONE=America/New_York
```

**Supabase auth (optional, for multi-user deployments):**

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_JWT_SECRET=your-secret
```

When `SUPABASE_JWT_SECRET` is unset, OptionLedger runs as a single-user local app with no login page. When set, JWT is enforced on all `/api/*` data endpoints.

Users can also connect Tastytrade interactively via the Settings page (`/settings`) — the OAuth2 authorization flow stores credentials encrypted in the database.

## Pages

| Route | Purpose |
|-------|---------|
| `/positions/options` | Option positions with live P&L, roll chain timeline |
| `/positions/equities` | Equity positions |
| `/ledger` | Position groups (historical + active), lots, tags, notes |
| `/reports` | Time-filtered P&L reporting by strategy |
| `/risk` | Portfolio Greeks, P&L curves, exposure charts |
| `/settings` | Tastytrade connection, tags, strategy targets, preferences |

## Database Migrations

Alembic runs automatically on container start. To run manually:

```bash
docker compose exec app alembic upgrade head
```

On a fresh database, the entrypoint will `create_all()` and stamp at head if `alembic upgrade` fails — no manual bootstrap needed.

## Development

Frontend builds are produced by Vite into `static/dist/`. The Docker image builds the frontend during image build, and the bind-mounted working directory lets you rebuild iteratively:

```bash
# Frontend — rebuild on change
cd frontend && npm run watch

# Or one-shot build
cd frontend && npm run build

# Backend logs
docker compose logs -f app
```

Linting and type checks follow the conventions in `CLAUDE.md`.

## Security

- `.env` is gitignored and must not be committed
- In multi-user mode, credentials are encrypted at rest with Fernet
- Tastytrade OAuth uses read-only scopes — OptionLedger cannot place trades or move money
- All API endpoints that return user data enforce `user_id` scoping via SQLAlchemy event listeners
- JWT validation is local (no external network calls)

## License

MIT. See `LICENSE` for details.
