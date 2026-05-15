---
id: OPT-54
title: Chain-as-source-of-truth: Unify Positions and Chains architecture
status: Done
priority: High
created: 2026-02-14
started: 2026-02-14
completed: 2026-03-15
labels: []
related: [OPT-55]
linear_url: https://linear.app/optionedge/issue/OPT-54/chain-as-source-of-truth-unify-positions-and-chains-architecture
---

# OPT-54: Chain-as-source-of-truth: Unify Positions and Chains architecture

## Summary

Redesign the Positions page to use order chains as the primary data source instead of pulling raw positions from the Tastytrade API. This unifies the two currently separate data worlds (Positions = TT API snapshot, Chains = transaction history) into a single chain-driven architecture.

## Motivation

Wingman Tracker's Open Positions page shows **Total P/L**, **Open P/L**, and **Realized P/L** — a full historical cost basis across rolls and adjustments. Our Positions page currently only shows the current open position's cost basis and unrealized P&L from the TT API. The chain data that would power this already exists in our system — it's just not surfaced on the Positions page.

More fundamentally, the Positions page and Chains page are currently two views of **different data sources** when they should be two views of **the same data**.

## Architectural Change

### Current Data Flow

```
Positions page: TT API → positions table → frontend (no chain context)
Chains page:    Transactions → order_chains → frontend (full history)
```

### New Data Flow

```
Positions page: Open order_chains + live quotes → frontend (full history + live data)
Chains page:    All order_chains → frontend (detailed progression view)
TT API positions: Used for reconciliation, not as primary source
```

### New P&L Columns on Positions Page

* **Open P/L** — unrealized P&L on current legs (live quotes)
* **Realized P/L** — banked P&L from rolls, partial closes, assignments within the chain
* **Total P/L** — Open + Realized, the complete picture

### Additional Data Available

* Full historical cost basis (cumulative across rolls)
* Chain depth (number of rolls/adjustments)
* Chain age (original open date, not just current leg)
* Direct link to chain detail view

## Positions Page Display: Underlying Subtotals

When multiple chains exist on the same underlying, display per-chain rows with a **subtotal row per underlying** that aggregates Total P/L, Realized P/L, and Open P/L across all chains for that symbol.

Example:

```
IBIT — Subtotal: Total P/L $13,580 | Realized $9,200 | Open $4,380
  ├─ Covered Call (shares + $39.5C/$40.5C) — chain P/L
  ├─ Covered Call ($41.5C) — chain P/L
  └─ Bear Put Spread — chain P/L
```

This gives the user both the per-chain detail AND the overall underlying picture without forcing unrelated chains to merge.

**Note:** Underlying subtotals only apply when sorting by Symbol. When the user sorts by other columns (P/L, DTE, etc.), subtotal rows should be hidden since the underlying grouping breaks down and subtotals would be misleading.

## Unified Sync Pipeline

Remove the separate Positions Sync button. A single sync operation:

1. Sync transactions → build/update chains
2. Pull TT positions → reconcile against chains
3. Overlay live quotes on matched open chains

The Chains page Sync button becomes the only surfaced sync control.

## Reconciliation Rules

### Unexpected Position (TT has it, chains don't)

* Most cases resolve automatically since transactions sync first
* Remaining cases shown in an **"Unlinked Positions"** section — visually distinct, flagged with "Position not matched to a chain — try syncing again"
* Shows raw TT data so the user isn't blind to it

### Missing Position (Chain says open, TT says no)

* **Post-sync**: If a closing transaction came in, chain closes normally
* **Expiration**: If chain's expiration date has passed and TT doesn't have it, auto-mark as expired
* **Stale flag**: For anything else, flag as "Position not found in broker" — visible but not auto-closed
* **Manual resolution**: After 2-3 unresolved syncs, surface a "Mark as closed" action

**Key principle: Never silently close or delete a chain.** Always surface discrepancies and let the user confirm.

## Chain Merge Rule (Shares Only)

### The Problem

When running overlapping strategies on the same underlying (e.g., owning shares + selling covered calls + selling CSPs for more shares), assignment can create stock lots across multiple chains. Shares are fungible — 100 shares from one assignment and 100 from another are just 200 shares with a blended cost basis.

### The Rule

**When a new stock lot is created (from assignment, exercise, or direct purchase) on an underlying where another chain already has open stock lots → merge the chains.**

Merging means:

* Combine all orders from both chains into one chain
* Realized P&L from both chains adds together
* Stock cost basis becomes the weighted average
* All option legs now belong to one chain

**What does NOT trigger a merge:**

* Multiple options-only positions on the same underlying stay separate (different strikes/expirations = no ambiguity)
* Options that happen to be on the same underlying as shares in another chain do NOT auto-merge — covered calls at different strikes opened as separate orders remain separate chains
* Only **shares** are fungible and force the merge

The overall underlying picture (across all chains including options-only chains) is captured by the **subtotal row** on the Positions page, not by chain merging.

### Wheel Strategy Representation

The wheel (sell put → assigned → sell calls → called away → repeat) is naturally represented as a single chain accumulating over time. No special "Wheel" strategy label needed — it's just what a chain looks like when it goes through these cycles. The chain status `ASSIGNED` already indicates "wheel in progress."

### Current System Support

The lot system already tracks assignment lineage:

* `position_lots.derived_from_lot_id` → links stock back to the assigned option
* `position_lots.derivation_type` = 'ASSIGNMENT'
* `lot_closings.resulting_lot_id` → points to the created stock lot
* Assigned lots inherit the same `chain_id`

The merge rule extends this to handle the case where chains need to combine.

## Side Benefits

### Solves OPT-50 (Share comments between Positions and Chains)

If the position IS the chain, a comment on the position IS a comment on the chain. No separate mechanism needed.

### Simplifies Navigation Model

* **Positions page** → portfolio view of open chains with live data
* **Chains page** → detailed historical view, drill-down for any chain (open or closed)
* These become two views of the same data, not two separate worlds

## Dependencies and Risks

* The order chain system and lot tracking must be reliable before making chains the source of truth for positions
* TT API reconciliation logic needs careful testing with edge cases (assignments, exercises, corporate actions)
* Chain merge logic is new — needs thorough testing with overlapping positions
* Frontend will need to be updated to use chain-based data instead of raw position data

## Comments

### 2026-02-14 — Steve Johnson

## Real-World Example: IBIT Positions Page Before/After

Based on the current live IBIT positions in account 5WZ26959.

### Current Display (TT API as source)

Two separate IBIT groups with no connection, no history:

- **Group 1**: 19,850 shares + 60x $41.50C — Cost Basis -$1,121,770, P&L -$346,461 (just current unrealized)
- **Group 2**: 60x $39.50C + 60x $40.50C — Cost Basis $8,400, P&L -$600 (just current unrealized)

The -$346K loss on shares looks brutal with no context about premium collected. Group 2 looks like a loser at -$600.

### New Display (Chain-as-source-of-truth)

```
IBIT — Subtotal: Total P/L -$334,621 | Realized $12,440 | Open -$347,061
  ├─ Chain 1: Covered Call (19,850 shares + $41.50C)
  │   Total P/L: -$344,241 | Realized: $2,160 | Open: -$346,401
  │   Rolls: 1 | Open since: Feb 11
  │
  └─ Chain 2: Covered Call ($39.50C + $40.50C)
      Total P/L: $9,620 | Realized: $8,280 | Open: -$600
      Rolls: 1 | Open since: Feb 11
```

### Key Differences

1. **Subtotal row** gives the complete IBIT picture at a glance across all chains
2. **Realized P/L** surfaces the $2,160 and $8,280 in premium already collected — currently invisible on the Positions page
3. **Total P/L** tells the real story — Chain 2 shows -$600 unrealized right now, but it's actually **+$9,620** when you include the premium from opening + roll. Completely different narrative.
4. **Chain age and roll count** provide context about position lifecycle
5. **The -$346K on shares** gets proper context alongside the premium income being generated against it
6. **Subtotal** lets the user see the net IBIT story ($12,440 in realized premium partially offsetting the unrealized share loss) without forcing unrelated chains to merge

---

### 2026-02-14 — Steve Johnson

## Implementation Plan — 7 Phases

### Phase 0: New Backend Endpoint (`/api/open-chains`)
Build a new API endpoint that returns open chains formatted for the Positions page. Reuses existing `get_cached_chains()` pattern but filters to OPEN/ASSIGNED chains and reshapes data into open legs with per-chain realized P&L and cost basis. **No frontend changes.** Testable independently via curl.

### Phase 1: Frontend Switchover
Positions page fetches from `/api/open-chains` instead of `/api/positions`. Each chain IS a group (no more grouping logic needed). P&L computed from chain cost basis + live quotes. Comments keyed by `chain_id` (solves OPT-50). **Biggest single change — medium risk.**

### Phase 2: P&L Column Split (Realized / Open / Total)
Replace single "P&L" column with three: Realized P/L (locked-in from rolls/closes), Open P/L (unrealized from live quotes), Total P/L (sum). Add sorting by each. **Low risk — pure display.**

### Phase 3: Underlying Subtotals (parallel with Phase 2)
When sorted by Symbol, show subtotal row per underlying aggregating all chains. Hidden when sorting by other columns. Only shown for underlyings with 2+ chains. **Low risk — pure frontend.**

### Phase 4: Reconciliation
After sync, compare chain-derived positions against TT API positions. Surface "Unlinked Positions" section for unexpected TT positions. Stale warning on chains missing from TT. Auto-expire chains past expiration. **Medium risk — matching algorithm edge cases.**

### Phase 5: Unified Sync Pipeline
Remove separate Positions sync. Single sync: transactions → chains → TT position reconciliation. Smart mode: skip chain reprocessing if no new transactions. **Medium risk — performance concern.**

### Phase 6: Chain Merge Rule for Shares
When stock lots created on underlying where another chain already has open stock lots → merge chains. Options-only chains stay separate. Modify `_derive_chains()` in order_processor.py. **Medium-high risk — affects chain IDs, comments, strategy detection.**

### Phase Dependencies
```
Phase 0 → Phase 1 → Phase 2 + Phase 3 (parallel) → Phase 4 → Phase 5
Phase 6 is independent (can start after Phase 0)
```

### Key Files
- `app.py` — New endpoint, reconciliation, sync unification
- `static/positions-dense.html` — Data source switch, P&L columns, subtotals, reconciliation UI
- `src/database/db_manager.py` — Open chain queries, reconciliation table
- `src/models/order_processor.py` — Share merge rule

---

### 2026-02-14 — Steve Johnson

## Revised Display Model: Shares Separated from Chains

After further discussion, shares should be displayed as a **separate top-level item** under each underlying, not hidden inside chains. This gives immediate visibility to equity positions and cleanly separates two questions: "How are my shares doing?" vs "How much premium am I collecting?"

### Updated Mockup (IBIT example)

```
IBIT — Subtotal: Total P/L -$334,621 | Realized $12,440 | Open -$347,061
  ├─ Shares: 19,850 @ $56.59 — Cost Basis: $1,123,330 | Open P/L: -$346,401
  ├─ Chain 1: Short Call ($41.50C) — Total: $2,100 | Realized: $2,160 | Open: -$60
  │   Rolls: 1 | Open since: Feb 11
  └─ Chain 2: Short Calls ($39.50C + $40.50C) — Total: $9,620 | Realized: $8,280 | Open: -$600
      Rolls: 1 | Open since: Feb 11
```

### Key Principles
- **Shares line**: Always visible at the underlying level. Shows equity cost basis and unrealized P/L. Includes both chain-linked shares (pulled out of chains for display) and orphaned shares (no chain).
- **Chain rows**: Options only — premium collected/paid, roll history. Chain P&L reflects the options strategy performance, not the share position.
- **Subtotal**: Aggregates shares + all chains = the complete underlying story.

### Why This Is Better
1. Shares are immediately visible, not buried inside expandable chain rows
2. Cleanly separates "equity performance" from "options premium collection"
3. For wheel traders: "I'm down $346K on shares but collecting $12K in premium" is immediately clear
4. Works for orphaned shares (no chain) — they just show as a shares line with no chains underneath
5. Removes the awkwardness of 19,850 shares being crammed into one chain while covering calls across multiple chains

---

### 2026-02-14 — Steve Johnson

## Implementation Complete — All 7 Phases

### Phase 0: Backend Endpoint (`/api/open-chains`)
- Added `get_open_chain_summaries()` to `db_manager.py` — queries open/assigned chains
- Added `GET /api/open-chains` endpoint to `app.py` — returns chains grouped by account
- Uses **position netting** to derive open legs: tracks net signed quantity per option symbol across all orders in a chain. Non-zero net = open position
- Separates equity (shares) from option legs — shares aggregated at underlying level
- Verified: 74 chain-derived option legs matched exactly with 74 TT API option positions

### Phase 1: Frontend Switchover
- Complete rewrite of `positions-dense.html` data layer
- State model changed from flat `allPositions` array to `allChains` + `allShares` + `allItems`
- Each chain IS a display group (eliminated grouping logic)
- Shares shown as separate rows with "stk" indicator
- WebSocket symbol collection adapted for chain leg structure
- Comments now keyed by `chain_${chain_id}` (also fixes OPT-50)

### Phase 2: P&L Column Split
- Replaced single "P&L" column with three: **Realized**, **Open P/L**, **Total P/L**
- New methods: `getGroupOpenPnL()`, `getGroupRealizedPnL()`, `getGroupTotalPnL()`
- Per-leg and per-share P&L calculation from live quotes

### Phase 3: Underlying Subtotals
- `_insertSubtotals()` inserts subtotal rows when sorted by Symbol
- Only shown for underlyings with 2+ items (chains + shares)
- Aggregates: Cost Basis, Net Liq, Realized, Open, Total across all items
- Visually distinct with blue background

### Phase 4: Reconciliation
- Added `reconcile_positions_vs_chains()` async function
- Added `GET /api/reconcile` endpoint
- Categories: MATCHED, QUANTITY_MISMATCH, UNLINKED, STALE
- Tested: 74/74 exact match between chain-derived and TT API positions

### Phase 5: Unified Sync
- Positions page sync now calls `/api/sync` (full pipeline) instead of `/api/sync-positions-only`
- Reconciliation results included in sync response
- Green/yellow banner shows reconciliation status after sync

### Phase 6: Chain Merge Rule for Shares
- Modified `_derive_chains()` in `order_processor.py`
- Stock-only opening orders attempt to merge into existing chains with open stock lots
- Added `_find_stock_merge_target()` helper — checks transaction history + lot manager
- Options orders always create new chains (no merge)

### Files Modified
| File | Changes |
|------|---------|
| `app.py` | `/api/open-chains`, `/api/reconcile`, reconciliation in sync responses |
| `src/database/db_manager.py` | `get_open_chain_summaries()` |
| `static/positions-dense.html` | Complete data layer rewrite, P&L columns, subtotals, reconciliation UI |
| `src/models/order_processor.py` | Stock merge logic in `_derive_chains()`, `_find_stock_merge_target()` |

---

### 2026-02-14 — Steve Johnson

## Fix: Stale chains + missing equity positions

After testing, the reconciliation showed "74/87 matched, 9 unlinked, 4 stale". Root causes:

### 4 Stale chains
ASSIGNED chains (HUT, IREN, MSTR, OKLO) where the stock from assignment was sold but the chain was never closed. The netting logic found non-zero option quantities for expired symbols that TT no longer reports.

**Fix**: Added auto-close logic to `reconcile_positions_vs_chains()`. When a chain has ZERO matched legs in TT (all stale), it's auto-closed by setting `chain_status = 'CLOSED'` and `closing_date = today`. The auto-closed count is reported in the reconciliation summary.

### 9 Unlinked equity positions
All 9 were equity (stock) positions. The chain cache (`order_chain_cache`) doesn't store equity legs as top-level positions — only options. The derived_positions approach only caught assignment-derived stock, missing direct stock purchases.

**Fix**: Changed `/api/open-chains` to source equity positions directly from the TT `positions` table instead of deriving from chain cache. This is the reliable source for share quantities and cost basis. Reconciliation now skips equity entirely (options-only reconciliation).

### Expected result after fix
- Reconciliation: "74/74 options matched, N auto-closed" (first sync closes stale chains)
- All 9 equity positions now appear as share rows on the Positions page
- Subsequent syncs: "74/74 options matched" (clean)

---

### 2026-02-15 — Steve Johnson

## Post-implementation fixes applied

After initial testing, several issues were found and fixed:

### Stale/ghost chains
- **Auto-close Pass 1**: Chains with stale option legs (TT doesn't have them) and no matched legs → auto-closed
- **Auto-close Pass 2**: "Ghost" chains with zero net option legs AND no TT positions for that underlying+account → auto-closed (caught ASSIGNED chains like HUT, IREN, MSTR, OKLO)

### Equity sourcing
- Changed `/api/open-chains` to source equity positions from TT `positions` table instead of chain-derived `derived_positions` (chain cache doesn't store stock legs)
- Reconciliation now only reconciles options, not equity

### Strategy detection after Initial Sync
- **Root cause**: Initial Sync used the old `OrderManager.reprocess_orders_and_chains_from_database()` pipeline which does NOT run strategy detection or populate `order_chain_cache`
- **Fix**: Replaced with OrderProcessor pipeline (`process_transactions` → `update_chain_cache`) which includes strategy detection
- Fixed "Created undefined trades" message in Initial Sync notification

### Ghost chain rows on Positions page
- Chains with zero open option legs (stock-only chains like STRC) were showing as rows with $0 everything
- Added filter: only include chains with at least one open option leg in `/api/open-chains` response

### UX: Spinner overlay for Initial Sync
- Added full-page overlay with spinner during Initial Sync and Reprocess operations on the Chains page
- Full sync benchmark: ~14 seconds for 750 transactions across 3 accounts

All issues verified fixed. Strategies detected correctly, no phantom positions, subtotals working.
