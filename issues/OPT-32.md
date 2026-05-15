---
id: OPT-32
title: Sync Behavior Documentation
status: Canceled
priority: None
assignee: Steve Johnson
created: 2026-02-04
canceled: 2026-02-17
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-32/sync-behavior-documentation
---

# OPT-32: Sync Behavior Documentation

Chains page Sync (/api/sync):                                                                                                                                                                                                                                                                                       - Fetches transactions from Tastytrade → saves to database

* Fetches current positions → saves to database
* Fetches account balances → saves to database
* Reprocesses order chains

Positions page Sync (/api/sync-positions-only by default):

* Fetches current positions → saves to database
* Fetches account balances → saves to database
* Does NOT fetch transactions or reprocess chains

So:

* Chains → Positions: Yes, syncing on Chains updates the positions data too
* Positions → Chains: No, syncing on Positions only updates positions (fast mode), not transactions/chains

The Positions page uses "fast mode" by default for speed - it skips the transaction fetch and chain reprocessing which can be slow. This means if you make a new trade and only sync on Positions, the trade won't appear on the Chains page until you sync there.

## Comments

### 2026-02-17 — Steve Johnson

This info is now out of date as Sync behavior has evolved. Closing.
