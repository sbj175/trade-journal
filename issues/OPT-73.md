---
id: OPT-73
title: Refine Positions page display: grouping, density, per-share values
status: Done
priority: Medium
assignee: Steve Johnson
created: 2026-02-19
started: 2026-02-19
completed: 2026-03-07
labels: [Improvement]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-73/refine-positions-page-display-grouping-density-per-share-values
---

# OPT-73: Refine Positions page display: grouping, density, per-share values

The Positions page needs several refinements to improve usability and consistency with the Ledger page.

## Issues

### 1\. Too crowded

The page has accumulated many columns (Symbol, IVR, Price, Strategy, DTE, Days, Cost Basis, Net Liq, Realized, Open, Total, % Rtn, % Max) and is becoming hard to scan. May need a mode toggle or column visibility controls to reduce density.

### 2\. Positions grouping doesn't match Ledger

On the Ledger page, shares and options for the same underlying (e.g., IBIT covered calls) are grouped together in the same position group. On the Positions page, shares and option chains show up as separate rows. These should mirror each other — if the Ledger groups them, the Positions page should too.

### 3\. Missing per-share values

The page shows total dollar values for Net Liq and cost basis, but doesn't show per-share (or per-contract) values. For option positions, knowing the per-contract cost basis and current mark is important for quick decision-making. TT shows both.

## Possible approach

Consider a display mode toggle similar to Wingman's "Cost Basis" vs "P/L" modes — one focused on cost basis / per-unit values, the other on P/L metrics. This could address the crowding issue while surfacing more detail in each mode.

## Comments

### 2026-02-19 — Steve Johnson

## Research & Plan: Unified Lot-Based Equity on Positions Page

### Root Cause
The Positions page uses **two separate data sources**:
- **Options**: from `position_groups` + `position_lots` (lot system)
- **Shares**: from `positions` table (raw TT API data)

This is why IBIT shows as two rows (shares + covered call) instead of one. The Ledger page already groups them correctly because it uses `position_lots` exclusively.

### Decision: Option A (Lot-Based Only)
After evaluating three approaches, we chose to source ALL position data from `position_lots` / `position_groups`:
- The `positions` table isn't "fresher" than lots — both only update on sync
- Live pricing comes from WebSocket regardless of data source
- Single source of truth eliminates reconciliation headaches
- Equity lots can be aggregated for display (multiple lots → one summary line with weighted avg cost)

### Plan Summary

**Backend** (`/api/open-chains`):
- Remove the `EQUITY_OPTION` filter — include equity lots from the same groups
- Add `equity_legs` and `equity_summary` (aggregated qty, avg price, cost basis) to each group
- Remove the `positions`-table equity block entirely
- Response shape: `{ account: { chains: [...] } }` (no more `shares` dict)

**Frontend** (`positions-dense.html`):
- Remove `_isShareRow` concept (~20 references)
- Update P/L functions to include equity (cost basis, net liq, open P/L)
- Add `_calculateEquityMarketValue()` using underlying WebSocket quotes
- Unified expanded detail panel: option legs section + equity summary section
- Equity-only groups show as "Shares" strategy

**No changes needed**: DB schema, Ledger endpoint, lot seeding, WebSocket subscriptions, roll analysis.

### Edge Cases Covered
- Mixed groups (covered calls): one unified row with combined P/L
- Equity-only groups: display as "Shares" strategy
- No live quote: returns 0 (consistent with option behavior)
- Option-only groups: completely unaffected (`equity_legs: []`)

---

### 2026-02-19 — Steve Johnson

## Display Hierarchy Comparison: Wingman vs OptionLedger

### Wingman (Open Positions page)
1. **Symbol** — top-level grouping
2. **Strategy Group** — e.g., covered call, iron condor
3. **Legs** — individual option/equity legs
4. **Leg Lots** — individual lots within a leg (different entry prices)

### OptionLedger (Positions page, current)
1. **Symbol** — subtotal rows when sorted by symbol (we also support sorting by P/L, DTE, % Rtn, etc. — Wingman only sorts by symbol)
2. **Position Group** — maps to strategy group
3. **Legs** + roll analysis in expanded panel

### Observations
- Wingman's **level 4 (leg lots)** breaks out individual lots within a leg, useful when you have multiple entries at different prices for the same contract or shares.
- Our **Ledger page** already covers levels 3-4 with full lot lifecycle detail. The Positions page is better suited as a live-monitoring view with aggregated data.
- With the planned equity unification, equity gets added as an aggregated summary within the position group (level 3). Individual equity lots are available in the data (`equity_legs` array) if we ever want level 4 on Positions, but the Ledger is the better place for that granularity.
- The Ledger link (book icon) on each position bridges the two views.
- Our sorting flexibility (P/L, DTE, % Rtn, % Max, days open, etc.) is a significant advantage over Wingman's symbol-only sorting.

---

### 2026-02-19 — Steve Johnson

Implementation complete on branch `opt-73-unify-positions-equity`.

**Changes:**

**Backend (`app.py` - `/api/open-chains`):**
- Added `equity_legs` and `equity_summary` fields to each group in the response
- Groups now include both option AND equity lots from `position_lots`
- Removed the entire positions-table equity block that queried `db.get_open_positions()` 
- Response shape changed from `{ chains: [...], shares: {...} }` to `{ chains: [...] }`
- Equity-only groups get `strategy_type: 'Shares'`

**Frontend (`positions-dense.html`):**
- Removed `allShares` state and all `_isShareRow` references (~20 locations)
- Added equity helper functions: `_hasEquity()`, `_isEquityOnly()`, `_calculateEquityMarketValue()`
- Updated `getGroupCostBasis()`, `getGroupOpenPnL()`, `getGroupNetLiqWithLiveQuotes()` to include equity
- Replaced dual option/share templates with unified expanded detail panel
- Added `+stk` badge for mixed groups (equity + options)
- All groups now link to Ledger page

**Result:** IBIT covered call (shares + options) shows as ONE unified row with combined P/L instead of two separate rows.
