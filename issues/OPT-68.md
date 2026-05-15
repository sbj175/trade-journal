---
id: OPT-68
title: Manual Position Entry for Edge Cases
status: Backlog
priority: Low
assignee: Steve Johnson
created: 2026-02-17
labels: []
related: [OPT-69]
linear_url: https://linear.app/optionedge/issue/OPT-68/manual-position-entry-for-edge-cases
---

# OPT-68: Manual Position Entry for Edge Cases

## Context

The Positions and Ledger pages now use `position_groups` / `position_lots` as a single source of truth. Equity positions are currently sourced from the TT API `positions` table because the lot system depends on having complete transaction history. Shares acquired before the first sync have no corresponding lots.

## Motivating Use Case: Unified Covered Call Tracking

A user consolidates their entire covered call history for a symbol into a single position group — 35 closed calls, 3 open calls, 16 rolls, all in one group alongside 7,600 shares. The Ledger shows total P&L across all calls, and the Positions page carries that cumulative P&L into the portfolio totals. This is exactly the kind of holistic strategy view the system should enable.

The missing piece: the shares are displayed as a separate row because they predate the sync history and have no `position_lot` records. With manual position entry, the user could add the shares as a lot in the same group, giving a complete picture in one place — cost basis on the shares, total premium collected from calls, and the net P&L of the entire covered call campaign. This lets you see your effective cost basis on the stock after accounting for all harvested premium.

## Enhancement

Add a manual position entry capability so users can backfill positions that predate their sync history. This would create synthetic `position_lot` records (no `opening_order_id` or `chain_id`) that participate in the normal group management system.

## Key Considerations

* **UI**: Form for entering symbol, quantity, entry price, entry date
* **Validation**: Ensure manual entries don't conflict with synced transaction data
* **Closing behavior**: Decide how synced closing transactions interact with manually-created lots (FIFO matching should work naturally)
* **Editability**: Whether manual lots can be edited or deleted after creation (synced lots cannot)
* **Scope**: Primarily needed for equity, but could apply to any instrument type

## Why

This would enable a unified display path where both equity and options are sourced from the lot system, allowing stock positions to be grouped and moved between position groups just like option legs. Currently equity takes a separate display path through the TT API positions table.
