---
id: OPT-65
title: Ledger page: position-centric view with action toggle
status: Done
priority: High
assignee: Steve Johnson
created: 2026-02-16
completed: 2026-02-17
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-65/ledger-page-position-centric-view-with-action-toggle
---

# OPT-65: Ledger page: position-centric view with action toggle

## Summary

Add a new **Ledger** page (`/ledger`) that provides a position-centric view of trading history, with the ability to toggle between **Position** view and **Action** view within each chain.

## Motivation

The current Chains page displays data organized by **orders** (OPENING → ROLLING → CLOSING). While this is great for seeing roll credits/debits the way TT shows them, it makes cost basis tracking awkward — the cost of a position is scattered across multiple orders.

A position-centric view solves this naturally: each position tracks its own lifecycle and cost basis accumulates on the position as transactions act on it. This also resolves the covered call cost basis problem (OPT-57 context) without needing chain merges — premium collected from call positions can be summed at the underlying level to adjust shares cost basis.

### Key Insight

The raw transaction data supports both views — they're just different projections:

* **Positions** = what you *held* and what it cost
* **Actions** = what you *did* and when (open/roll/close with credits/debits)

## Design

### Position View (default)

Each row is a position lot (e.g., "-60 IBIT Feb 20 39.5C") showing:

* Entry date and entry price
* Cost basis adjustments from rolls
* Current status (open / closed / expired / assigned)
* Exit date and exit price (if closed)
* Realized P&L

Positions are grouped by chain, with the chain header showing aggregate cost basis and total P&L. Cost basis naturally accumulates on the position through its lifecycle.

### Action View (toggle)

Each row is an order — OPENING, ROLLING, CLOSING — showing:

* Order date and type
* Transactions grouped by action
* Roll credits/debits displayed like TT
* Running P&L per order

This is similar to the current Chains page expanded view but within the new Ledger context.

### Toggle

Within each expanded chain detail, a tab or toggle switches between:

* **Positions**: lots grouped by leg, showing lifecycle and cost basis
* **Actions**: orders grouped chronologically, showing credits/debits

### Cost Basis Flow

* Shares position: purchase price is the starting cost basis
* Covered call positions: premium collected tracked per position
* At the underlying level: sum shares cost basis + CC realized P&L = adjusted cost basis
* No chain merging needed — linking happens naturally at the underlying level

## Data Model

Existing tables already support both views:

* `raw_transactions` — source of truth
* `position_lots` — position lifecycle tracking (entry, remaining qty, status)
* `lot_closings` — how positions get closed (partial/full, price, P&L)
* `orders` — grouped transactions by order
* `order_chains` / `order_chain_members` — chain relationships

No schema changes expected — this is a display/query layer change.

## Pages & Routes

* New page: `static/ledger.html` at `/ledger`
* New nav item between Chains and Reports
* Shares the same Alpine.js patterns, account selector, and filter controls as other pages

## Relationship to Other Features

* Supersedes the cost basis use case from OPT-57 (chain merge)
* Chain merge (OPT-57) remains useful for its original purpose: combining chains split by TT's 4-leg order limit
* The Ledger page may eventually replace or complement the Chains page

## Comments

### 2026-02-16 — Steve Johnson

## Implementation Complete

All planned steps for the Ledger page have been implemented:

### Changes Made

**Database schema** (`src/database/db_manager.py`):
- Added `position_groups` table (group_id, account_number, underlying, strategy_label, status, source_chain_id, dates)
- Added `position_group_lots` table (group_id, transaction_id) — uses transaction_id for reprocessing survival
- Added indexes for both tables

**Batch query methods** (`src/models/lot_manager.py`):
- `get_lots_for_groups_batch()` — single query joins position_lots with position_group_lots for multiple groups
- `get_lot_closings_batch()` — single query for closings across multiple lots
- `get_unassigned_lots()` — finds lots not in any group (LEFT JOIN pattern)

**Backend API** (`app.py`):
- `GET /ledger` — page route
- `GET /api/ledger` — main data endpoint with auto-seeding, batch loading, order derivation
- `POST /api/ledger/seed` — explicit seed trigger
- `PUT /api/ledger/groups/{group_id}` — update strategy label
- `POST /api/ledger/move-lots` — move lots between groups (with same-underlying constraint)
- `POST /api/ledger/groups` — create new empty group
- `DELETE /api/ledger/groups/{group_id}` — delete group
- `seed_position_groups()` — seeds from existing chains, handles ungrouped lots
- `seed_new_lots_into_groups()` — called after all 4 reprocessing paths

**Frontend** (`static/ledger-dense.html`):
- Position view: lot lifecycle table with entry date, qty, expiration, DTE, strike, type, entry price, cost basis, status, realized P&L, closings as sub-rows
- Action view: derived order sequence with credit/debit badges (reuses chains order template)
- Edit mode: checkboxes on lots, floating action bar for moving lots between groups, inline strategy label editing
- Filters: account selector, symbol search, time period, open/closed status, sort options
- Stats bar: group counts, open/closed breakdown, total realized P&L
- State persistence via localStorage

**Nav bar updates**: Added "Ledger" link between Chains and Reports on all 5 existing pages.

**CLAUDE.md**: Added Position Ledger entry to Frontend Structure section.

---

### 2026-02-17 — Steve Johnson

Actions view renamed to Orders view.
