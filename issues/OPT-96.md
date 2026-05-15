---
id: OPT-96
title: Auto-close expired options?
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-21
started: 2026-02-22
completed: 2026-02-22
labels: [Research]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-96/auto-close-expired-options
---

# OPT-96: Auto-close expired options?

Consider auto-closing expired options. Although this could have Sync implications, so I don't know if we should do that or just hide them from Positions.

## Comments

### 2026-02-22 — Steve Johnson

## Research Findings: Auto-close Expired Options (OPT-96)

### 1. What does Tastytrade's API return for expired positions?

**Key finding from [Tastytrade API docs](https://developer.tastytrade.com/api-guides/account-positions/):**
> "A position with a quantity of 0 is considered closed. We purge these positions overnight."

This means:
- On expiration day (after market close), the expired option likely still appears with quantity 0 briefly
- By the next morning, Tastytrade removes it from the positions response entirely
- The SDK's `get_positions()` method has an `include_closed` parameter (defaults to `None`/false), so by default only open positions are returned
- **OptionLedger does NOT pass `include_closed=True`** — see `tastytrade_client.py:185`: `positions = await account.get_positions(self.session, include_marks=True)`

**Implication:** After overnight processing, Tastytrade stops returning expired option legs. The "problem window" is between market close on expiration Friday and TT's overnight purge.

### 2. What happens to positions in the local database when TT stops reporting them?

There are **two separate data paths** on the Positions page, and they behave differently:

#### Path A: `positions` table (legacy, used by `/api/positions/cached`)
- `save_positions()` in `db_manager.py:772-823` does a **DELETE + INSERT** for the entire account on every sync
- Line 779: `cursor.execute("DELETE FROM positions WHERE account_number = ?", (account_number,))`
- So when TT stops returning an expired option, it **automatically disappears** from this table on next sync
- **This path works correctly** — no stale data issue

#### Path B: `position_lots` / `position_groups` (current, used by `/api/open-chains`)
- This is what the Positions page actually uses now (confirmed: `fetchPositions()` calls `/api/open-chains`)
- Position lots are created from **transaction history**, not from the TT positions API
- Lots are only closed when there's a matching closing transaction (expiration, assignment, manual close)
- **The expiration transaction IS processed** — `order_processor.py:522-523` detects `is_expiration` and calls `lot_manager.close_lot_fifo()` with `closing_type='EXPIRATION'`
- **However**, this only happens during a **full sync** (`/api/sync`) that fetches transactions and reprocesses chains
- The `reconcile_positions_vs_chains()` function (called at end of full sync) also auto-closes stale lots/groups where TT has no position but lots say OPEN

**The bug scenario:** If the user's last sync was BEFORE expiration, and they haven't synced since, the expired option lot remains OPEN in `position_lots` with `remaining_quantity != 0`. The Positions page shows it with negative DTE.

### 3. The IBIT Covered Call scenario

For a covered call (e.g., short IBIT call + long IBIT shares):
- When the call expires worthless, TT removes the option leg from positions
- The stock leg remains as an active position
- In the lot system: the call lot should get closed via EXPIRATION transaction, the stock lot stays open
- The position_group stays OPEN because the stock lot still has `remaining_quantity != 0`
- **Expected behavior:** Group shows only the stock leg after expiration processing
- **Current bug:** If no sync has happened since expiration, both legs show, with DTE showing negative for the option

### 4. Edge cases: Assignment/Exercise vs Simple Expiration

| Event | TT API Behavior | Lot System Behavior |
|-------|----------------|---------------------|
| **Expiration (OTM)** | Option disappears from positions after overnight purge | `close_lot_fifo` with `EXPIRATION` type closes the lot |
| **Assignment (ITM short)** | Option disappears + stock position created/adjusted | `close_lot_fifo` with `ASSIGNMENT` + derived equity lot created via `_detect_assignment_pairs()` |
| **Exercise (ITM long)** | Option disappears + stock position created/adjusted | `close_lot_fifo` with `EXERCISE` + derived equity lot created |

All three are handled by the order processor when transactions are synced. The `verify_expiration_position_bug.py` file documents a known bug where expiration positions in the legacy `positions_new` table have `opening_action = None`, but this is in the **old order system** (not the current lot-based system).

### 5. Frontend DTE behavior

Two different DTE functions exist:
- `getMinDTE(group)` (line 564-578): Used for the group-level DTE column. **Does NOT clamp negative values** — returns raw negative numbers like -1, -2, etc.
- `getDTE(leg)` (line 693-700): Used for per-leg display in expanded view. **Clamps to 0** — `return dte > 0 ? dte : 0`

So expired options show negative DTE at the group level but "0" in the expanded leg view — inconsistent.

### 6. The `/api/sync-positions-only` endpoint

CLAUDE.md references this endpoint but **it no longer exists**. The Positions page now uses:
- Sync button → POST `/api/sync` (full sync with transactions + chain reprocessing + reconciliation)
- Data display → GET `/api/open-chains` (reads from position_groups/position_lots)

---

## Summary of the Problem

The problem is a **timing gap**: Between when an option expires and when the user does a full sync, the expired option leg remains visible on the Positions page with negative DTE. Once a full sync happens, the expiration transaction is processed, the lot gets closed, and the leg disappears.

## Recommended Approach

There are three possible solutions, not mutually exclusive:

### Option A: Frontend-only hide (simplest, lowest risk)
- In the `/api/open-chains` endpoint or in the frontend `getMinDTE`/display logic, filter out option legs where `expiration < today`
- Pros: Zero risk to data integrity, instant fix
- Cons: Doesn't actually close the lot — if user looks at Ledger, the lot still shows as OPEN

### Option B: Backend expiration check at display time
- In `positions.py` `/api/open-chains`, when building `open_option_legs`, skip legs where `lot.expiration < date.today()`
- This is the user's stated preference: "hide only the expired leg, not the whole position row"
- The stock leg of a covered call would remain visible
- Pros: Clean data at the API level, Ledger unaffected
- Cons: Still doesn't close the lot in the database

### Option C: Automatic lot closure on detection (most complete)
- When `/api/open-chains` encounters a lot with `expiration < today`, auto-close it (`remaining_quantity = 0, status = 'CLOSED'`) with `closing_type = 'EXPIRATION'` and `realized_pnl` calculated from the entry price
- Pros: Database stays accurate, reconciliation stays clean
- Cons: More complex, must handle P&L calculation correctly (expired options are worth $0 at close)

### Recommended: Option B first, Option C later
- Ship Option B immediately — it's safe and addresses the visible bug
- Implement Option C as a follow-up once the P&L implications are tested
- The reconciliation system (`reconcile_positions_vs_chains`) already handles this for fully-synced positions, so Option C would just be catching the edge case earlier

---

### 2026-02-22 — Steve Johnson

## Research Findings: Auto-close Expired Options

### Root Cause

Tastytrade purges expired positions overnight, so they disappear on next sync. But between expiration and the next sync, expired option lots remain `OPEN` in the `position_lots` table and show with negative DTE on the Positions page.

### Two data paths behave differently

- **Legacy `positions` table**: DELETE + re-insert on sync — expired legs auto-vanish. Works correctly.
- **Current `position_lots` system** (what Positions page uses): Lots only close when expiration *transactions* are processed during a full sync. Without a sync after expiration, stale lots persist.

### Three Implementation Options (recommended order)

1. **Backend filter at display time** (safest): In `/api/open-chains`, skip option lots where `expiration < today`. Hides expired legs without touching data. Stock legs remain visible.
2. **Frontend filter** (lowest risk): Filter in Alpine.js display logic. Quick but API still returns stale data.
3. **Auto-close lots** (most thorough): When encountering `expiration < today`, auto-close the lot in the database with `EXPIRATION` type. Requires P&L calculation. Follow-up work.

### DTE Display Inconsistency

`getMinDTE()` returns negative values, but `getDTE()` clamps to 0. Should be made consistent — either both clamp or both allow negatives.

### Edge Cases

Assignment and exercise are already handled separately in the order processor — no changes needed there.

### Recommendation

Option 1 (backend filter) is the best first step. It's safe, reversible, and immediately solves the user-facing problem. Option 3 can be done as follow-up work if we want the database to accurately reflect expired positions.
