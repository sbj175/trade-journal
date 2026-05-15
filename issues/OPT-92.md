---
id: OPT-92
title: Auto Sync Behavior
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-20
completed: 2026-03-31
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-92/auto-sync-behavior
---

# OPT-92: Auto Sync Behavior

Currently the application looks at the time since the last transaction sync on startup and initiates one automatically if it has been more than 6 hours since the last one.

As we move this toward a commercial Saas application, I believe it should be handled like so:

* Record transaction sync times in a table (eventually this will be per user)
* Add a Settings page item for turning automatic transaction sync on/off
* Only perform automatic sync if the user is logged in and automatic sync is turned on, then perform the sync every X hours or minutes (maybe another config item?)
* Add information somewhere to show the last sync date/time

## Comments

### 2026-02-20 — Steve Johnson

## Technical Analysis of Current State

### What exists today
- **`sync_metadata` table** — key-value store that already tracks `last_sync_timestamp` and `initial_sync_completed`
- **Startup-only auto-sync** — fires once on app startup if >6 hours since last sync, no recurring timer
- **`background_incremental_sync()`** — dead code, defined but never called anywhere. Should be removed.
- **`lastSyncTimestamp` in positions JS** — declared but never rendered in the UI. The backend already returns `last_sync` from `/api/positions/cached` but no page displays it.

### Implementation thoughts

**1. Sync history table**
The existing `sync_metadata` key-value table could work for single-user, but for multi-tenant SaaS a proper `sync_history` table makes more sense:
```
sync_history(id, user_id, sync_type, started_at, completed_at, status, transactions_fetched, error_message)
```
This gives audit trail, per-user tracking, and the ability to show "last sync: 3 minutes ago" in the UI.

**2. Auto-sync settings**
Two new keys in a user settings/preferences table (or `sync_metadata` for now):
- `auto_sync_enabled` (boolean, default: true)
- `auto_sync_interval_minutes` (integer, default: 60)

Add a toggle + interval dropdown to the Settings page's existing tab UI.

**3. Periodic sync mechanism**
Two options:
- **Frontend timer** — `setInterval` in the nav partial that calls `/api/sync` on the configured interval. Simple, works now, but stops if no browser tab is open.
- **Backend scheduler** — use `asyncio` background task loop or APScheduler. Runs regardless of browser state, better for SaaS. More complex.

For the current single-user local app, a frontend timer is simpler and sufficient. For SaaS, switch to a backend scheduler (could be a Celery beat task or FastAPI background task with `asyncio.sleep` loop).

**4. Last sync display**
Add a small timestamp to the nav bar or status area: "Last sync: 12:34 PM" — the data is already available from the API, just needs a UI element.

### Suggested phasing
1. Show last sync time in the UI (quick win, data already available)
2. Add auto-sync on/off toggle to Settings
3. Implement frontend interval timer (simple, works for local app)
4. Defer backend scheduler + per-user sync history table to the SaaS conversion (OPT-51)

---

### 2026-02-20 — Steve Johnson

## Sync Dispatcher Pattern (per Steve's feedback)

Rather than per-user background tasks, use a single **sync dispatcher** — one background loop that wakes every 60 seconds and checks which users need syncing.

### How it works

```
Background loop (every 60s):
  1. Query: SELECT users WHERE auto_sync_enabled = true
       AND last_sync_at < now() - sync_interval
       AND sync_in_progress = false
     ORDER BY last_sync_at ASC
     LIMIT batch_size
  2. For each user in batch: run sync, update last_sync_at
```

### Why this is better than per-user tasks
- **One task to manage** — no tracking/canceling individual timers when users change settings or go offline
- **Natural rate limiting** — `LIMIT batch_size` prevents overloading the Tastytrade API during peak hours
- **Staggered by design** — users sync at different times since they signed up / last synced at different times, avoiding thundering herd
- **Simple shutdown** — cancel one task on app shutdown, not N tasks
- **Easy observability** — one place to log sync throughput, failures, queue depth

### Schema support needed
```sql
-- On user_settings or users table:
auto_sync_enabled    BOOLEAN DEFAULT true
sync_interval_minutes INTEGER DEFAULT 60
last_sync_at         TIMESTAMP
sync_in_progress     BOOLEAN DEFAULT false
```

The `sync_in_progress` flag prevents the dispatcher from re-queuing a user whose previous sync is still running (e.g., large account with many transactions).

---

### 2026-03-31 — Steve Johnson

I am marking this issue as DONE since I now believe it's better for the user to explicitly sync when they want to.
