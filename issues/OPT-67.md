---
id: OPT-67
title: position_groups can go stale when chain IDs change during reprocessing
status: Done
priority: Low
assignee: Steve Johnson
created: 2026-02-17
completed: 2026-02-17
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-67/position-groups-can-go-stale-when-chain-ids-change-during-reprocessing
---

# OPT-67: position_groups can go stale when chain IDs change during reprocessing

## Problem

`position_groups` is a persistent table keyed on `source_chain_id`, but chain IDs can change during reprocessing (e.g. when the Symbol Change fix in OPT-66 changed `FI_OPENING_20251111_SYSTEM_S` to `FISV_OPENING_20251111_SYMCHG_O`). When this happens, the group retains the old underlying, strategy label, and chain reference while the lots it contains now point to the new chain.

The root cause is a coupling problem: `position_group_lots` links groups to lots via `transaction_id` (stable across reprocessing), but the group metadata (`underlying`, `strategy_label`, `source_chain_id`) is set once at seeding time and never updated. `seed_new_lots_into_groups` only handles *unassigned* lots and returns early if there are none, so it can't fix stale groups.

## Current Workaround

OPT-66 added `_reconcile_stale_groups()` — a standalone function that detects orphaned groups (source_chain_id not in order_chains) and updates them from their lots' current chain data. It's called after `seed_new_lots_into_groups()` at 3 call sites (sync, initial-sync, reprocess-chains). It works but is a band-aid.

## Cleaner Alternatives

1. **Clear** `position_group_lots` during reprocessing alongside `position_lots`, so everything re-seeds fresh. Simplest, but loses manual group customizations (renames, lot moves).
2. **Key groups on something stable** (underlying + account + date range) rather than `source_chain_id`, which is a derived value that can change.
3. **Make seeding always authoritative** — have it update existing groups from their lots' current chain data, not just assign unassigned lots. This would subsume the reconciliation logic naturally.

## Comments

### 2026-02-17 — Steve Johnson

Closing — addressed by the Positions/Ledger unification work (commit `002eb2d`).

Both pages now read from `position_groups` + `position_lots` as a single source of truth. The `order_chains` table is no longer read for display, so the two-source drift problem this issue described is eliminated.

`_reconcile_stale_groups()` remains in place to keep `source_chain_id` correct for `seed_new_lots_into_groups()` matching, but this is now an adequate solution rather than a band-aid — there's no second display path that could disagree. The "cleaner alternatives" listed here are still nice-to-haves but no longer necessary.
