---
id: OPT-66
title: Handle "Symbol Change" transactions in order processing
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-17
completed: 2026-02-17
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-66/handle-symbol-change-transactions-in-order-processing
---

# OPT-66: Handle "Symbol Change" transactions in order processing

## Problem

When a company changes its ticker (e.g., FI → FISV), Tastytrade generates 2 "Symbol Change" transactions per leg (close old symbol + open new symbol). For a 2-leg spread, that's 4 transactions total.

These were processed incorrectly:

* Each got a unique system-generated order_id → 4 separate 1-leg orders instead of 2 grouped 2-leg orders
* All 4 had `underlying_symbol` = old ticker ("FI"), so the new chain showed under FI instead of FISV
* Strategy detection failed because legs weren't grouped ("Short Call" instead of "Bear Call Spread")

P&L was already correct ($150 + -$30 = $120, matching TT).

## Fix

Added a pre-scan in `_preprocess_transactions()` that:

1. Filters for `transaction_sub_type == "Symbol Change"`
2. Groups by (account, old_underlying, date)
3. Separates close legs (TO_CLOSE) from open legs (TO_OPEN)
4. Derives new underlying from open transactions' symbol field
5. Generates shared order_ids: `SYMCHG_CLOSE_...` and `SYMCHG_OPEN_...`
6. Overrides `underlying_symbol` on open legs to use new ticker

Result: close legs grouped into one 2-leg CLOSING order (under old ticker), open legs grouped into one 2-leg OPENING order (under new ticker). Strategy detection works correctly.

## Comments

### 2026-02-17 — Steve Johnson

## Root cause of persisting FI / "Short Call" on Ledger

The `order_processor.py` fix was working correctly — `order_chains` and `order_chain_cache` had the right data (underlying=FISV, strategy=Bear Call Spread). But the **Ledger page** reads from `position_groups`, not `order_chains`.

The `position_groups` table had a stale group (created before the fix) with:
- `underlying = 'FI'`
- `strategy_label = 'Short Call'`
- `source_chain_id = 'FI_OPENING_20251111_SYSTEM_S'` (old pre-fix chain ID)

The FISV lots were still linked to this old group via `position_group_lots` (keyed by `transaction_id`, which doesn't change across reprocessing). `seed_new_lots_into_groups` skipped them because they appeared "assigned".

## Fix

Added a reconciliation step in `seed_new_lots_into_groups()` (app.py) that runs after lot assignment:
1. Finds position_groups whose `source_chain_id` no longer exists in `order_chains`
2. Looks up the actual chain_id from the group's lots in `position_lots`
3. Updates the group's `underlying`, `strategy_label`, `source_chain_id`, and dates from the new chain

This handles any case where reprocessing changes chain IDs (symbol changes, algorithm improvements, etc.).
