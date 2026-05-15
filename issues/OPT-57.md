---
id: OPT-57
title: Manual chain merge: select and merge chains within the same underlying
status: Done
priority: Medium
assignee: Steve Johnson
created: 2026-02-15
started: 2026-02-16
completed: 2026-02-17
labels: [Feature]
related: [OPT-63]
linear_url: https://linear.app/optionedge/issue/OPT-57/manual-chain-merge-select-and-merge-chains-within-the-same-underlying
---

# OPT-57: Manual chain merge: select and merge chains within the same underlying

## Summary

Add the ability to manually select two or more chains on the same underlying and merge them into a single chain. This addresses cases where related trades end up in separate chains due to order entry timing (e.g., IBIT covered calls split across chains).

## Motivation

The automatic chain derivation sometimes creates separate chains for trades that the user considers part of the same position. For example, entering covered call legs as separate orders can result in the shares and calls being in different chains. Currently there's no way to fix this without reprocessing.

## Proposed Approach

### Backend

* New endpoint `POST /api/merge-chains` accepting a list of chain IDs
* Validate all chains belong to the same underlying and account
* Move all `order_chain_members` records from source chains into the target chain
* Recalculate merged chain metadata (total_pnl, realized_pnl, order_count, strategy_type, opening_date, etc.)
* Re-run strategy detection on the merged chain
* Delete source chains from `order_chains`
* Migrate any comments keyed by old `chain_id`

### Frontend

* Add selectable mode (checkboxes or shift-click) for chains within the same underlying
* Show a "Merge" button when 2+ chains of the same underlying are selected
* Confirmation dialog showing what will be merged
* Refresh positions after merge

### Edge Cases

* Strategy re-detection on merged chain
* Roll count aggregation
* Comment migration (localStorage keys use `chain_${chain_id}`)
* Opening date should use earliest date from merged chains

## Comments

### 2026-02-15 — Steve Johnson

## Real-world example: IBIT Covered Calls in 5WZ26959

Investigation of the IBIT position in account 5WZ26959 reveals exactly the kind of fragmentation this feature would solve.

### Current state: 18 separate chains for one ongoing position

The user has held IBIT shares continuously since March 2025 and has been writing covered calls against them repeatedly. The chain system currently produces **18 separate chains** because each new batch of calls (STO) is classified as `OrderType.OPENING` and starts a fresh chain. There's no connecting tissue between call cycles.

| Chain | Strategy | Dates | P&L |
|-------|----------|-------|-----|
| `IBIT_OPENING_20250401_37555788` | Covered Call | Apr 1 – Apr 4 | $3,960 |
| `IBIT_OPENING_20250407_37708926` | Covered Call | Apr 7 – May 2 | -$65,880 |
| `IBIT_OPENING_20250505_38216801` | Covered Call | May 5 – May 28 | $8,010 |
| `IBIT_OPENING_20250630_39244084` | Covered Call | Jun 30 | $2,400 |
| `IBIT_OPENING_20250707_39334205` | Covered Call | Jul 7 – Jul 25 | $9,010 |
| `IBIT_OPENING_20250910_40636937` | Short Call | Sep 10 – Sep 12 | $1,200 |
| `IBIT_OPENING_20250916_40744402` | Short Call | Sep 16 – Sep 19 | $3,600 |
| `IBIT_OPENING_20251027_41648601` | Covered Call | Oct 27 – Oct 31 | $40,775 |
| `IBIT_OPENING_20251120_42228217_MERGED` | Covered Call | Nov 20 – Dec 12 | $24,425 |
| `IBIT_OPENING_20251208_42543030` | Covered Call | Dec 8 – Dec 19 | $10,159 |
| ...and 8 more | | | |

### Why automatic merging doesn't help here

- **Stock shares are completely outside the chain system.** Every IBIT equity transaction has no chain association — the initial purchases have `order_id=None` (likely a transfer), and later stock buys/sells are pure equity orders never linked to option chains.
- **Each new call cycle is a fresh STO** with no closing component, so it's classified as `OrderType.OPENING` → new chain. The existing `_find_stock_merge_target` logic only merges stock-only orders into existing chains with open stock lots — it doesn't handle the reverse case of options that should merge because shares are continuously held.
- **No time-proximity or strategy-aware matching exists** to detect that consecutive covered call chains on the same underlying are part of one ongoing position.

### Why manual merge is the right solution

The user knows these are all part of one IBIT covered call campaign. Manual merge would let them select the relevant chains and combine them into a single chain showing:
- Complete P&L history of writing calls against the position
- Total premium collected across all call cycles
- Full timeline from first call written to current open position

### Also relevant: Iron Condor rolls

TT has a 4-leg order limit, so rolling an Iron Condor requires two separate orders (close 4 legs, open 4 legs). These end up as separate chains since the close and open have different strikes/expirations. Manual merge would let users link these as a single rolled IC chain — something automatic detection can't do since the two orders share no common option symbols.

---

### 2026-02-15 — Steve Johnson

## Design exploration: Chain Groups (from OPT-62 investigation)

While investigating OPT-62 (STO calls not merging into stock chains), we explored progressively deeper solutions and arrived at a "chain groups" concept that may be a better architecture than physical chain merging.

### Problem with physical merge

Physically combining 18 IBIT covered call chains into one giant chain has downsides:
- Loses per-cycle P&L visibility
- Strategy detection gets confused with mixed strikes/expirations
- Unwieldy to view in the UI
- Destructive — hard to undo

### Chain Groups concept

A non-destructive grouping layer on top of existing chains:

- **User-initiated**: user selects chains to group (no auto-grouping)
- **Non-destructive**: individual chains retain their identity, strategy, dates, P&L
- **Aggregate P&L**: group sums member chain P&L
- **Group lifecycle**: group is "open" as long as any member chain is open OR shares are held on the underlying
- **Positions page**: group's aggregate P&L shows at the symbol header level, feeding into cost basis
- **Chains page**: visual grouping indicator, collapsible group view

### Generality

Works beyond covered calls:
- Multiple vertical spreads on same underlying
- Iron Condor roll sequences (close + reopen as separate orders due to TT's 4-leg limit)
- Any "trading campaign" the user wants to track as a unit

### Open questions

- Data model: separate `chain_groups` + `chain_group_members` tables? Or just a `group_id` column on `order_chains`?
- How does group P&L interact with the Positions page symbol header when there's no open position?
- Should the group have its own strategy label or just show "Chain Group"?
- How does this interact with the Reports page aggregation?

### Relationship to OPT-57 and OPT-62

Chain groups could subsume OPT-57 (manual chain merge) as a non-destructive alternative. OPT-62 (the STO call merge bug) could be addressed by chain groups rather than modifying chain derivation logic.

---

### 2026-02-16 — Steve Johnson

## Implementation Complete

### Changes Made

**Backend (`app.py`)**:
- Added `MergeChainsRequest` Pydantic model
- Added `POST /api/merge-chains` endpoint with:
  - Validation: all chains must exist, share same underlying + account
  - Target chain selection: earliest `opening_date`
  - Merged chain ID: `{target_chain_id}_MERGED` suffix
  - Full metadata recalculation from cached order data (P&L, dates, status, strategy)
  - Single transaction: deletes source chains, inserts merged chain, migrates members/cache/notes/lots/positions
  - Position notes concatenated with `---` separator
  - Position lots and positions table `chain_id` references updated

**Frontend (`static/js/app.js`)**:
- Added merge mode state: `mergeMode`, `selectedChains`, `selectedUnderlying`, `selectedMergeAccount`, `merging`
- `toggleMergeMode()` - enter/exit selection mode
- `toggleChainSelection(chain)` - add/remove chains; first selection locks underlying + account
- `isChainSelectable(chain)` - enforces same underlying + account constraint
- `mergeSelectedChains()` - confirmation dialog, API call, reload on success

**UI (`static/chains-dense.html`)**:
- "Merge Chains" toggle button in action bar (blue when active)
- Checkbox column on each chain row (disabled for incompatible chains)
- Floating action bar at bottom showing selection count + merge/cancel buttons
- Smooth transitions on the floating bar

### Key Design Decisions
- Merged chain ID uses `_MERGED` suffix to survive reprocessing
- Strategy becomes "Multi-Strategy" when merging different strategy types
- Chain status is OPEN if any source chain was open
- Notes from multiple chains are concatenated with `---` separator

---

### 2026-02-16 — Steve Johnson

## Follow-up Fixes

### Bug: "Invalid Date" in Opened column
- **Cause**: `opening_date` was stored as full ISO datetime (e.g. `2025-12-15T14:30:00`) from order cache data, but the frontend's `formatChainDate()` expects date-only format (`2025-12-15`) and appends `T00:00:00`
- **Fix**: Added `[:10]` slice to extract date-only portion when calculating `opening_date` and `closing_date` in the merge endpoint

### Bug: Reprocess Chains splits merged chains
- **Cause**: Reprocessing rebuilds all chains from raw transactions, completely unaware of manual merges
- **Fix**: 
  1. Added `chain_merges` table to `db_manager.py` that records merge relationships (merged_chain_id → source_chain_id)
  2. The merge endpoint now writes to `chain_merges` so merge intent is persisted
  3. Added `reapply_chain_merges()` helper that reads `chain_merges` and re-combines the auto-derived chains after a rebuild
  4. Called after `update_chain_cache()` in all three rebuild paths: reprocess chains, initial sync, and regular sync

---

### 2026-02-17 — Steve Johnson

## Auto-merge chains when lots are moved between groups (Ledger → Positions sync)

Implemented automatic order chain merging that keeps the Positions page in sync with Ledger group changes:

### Problem
When a user moved lots between groups on the Ledger page (e.g., merging IBIT 41.5 strike into the 39.5/40.5 group), only the `position_group_lots` table was updated. The underlying `order_chains` (which the Positions page reads from) remained separate, causing the Positions page to show them as distinct entries.

### Solution
Added `_merge_order_chains(cursor, chain_ids)` helper function in `app.py` that:
1. Merges multiple `order_chains` into a single chain with recalculated metadata
2. Records the merge in `chain_merges` table for durability across reprocessing
3. Handles "unwinding" previous merges (if a chain was itself a merge result)
4. Updates `position_lots`, `positions`, and `position_groups` to reference the merged chain

### Integration points
- **`/api/ledger/move-lots`**: After moving lots, checks if the target group now contains lots from multiple chains. If so, auto-merges them.
- **`_reconcile_stale_groups()`**: Enhanced to also detect and fix multi-chain groups (catches any that were created before auto-merge was added), and cleans up orphaned `chain_merges` records.

### Files changed
- `app.py`: Added `_merge_order_chains()`, updated `move_lots()` endpoint, enhanced `_reconcile_stale_groups()`

### Verified
- IBIT covered calls in Traditional IRA: merged 2 chains (5 orders) into 1, reducing IBIT OPEN chains from 4 to 3, matching 3 OPEN groups.
