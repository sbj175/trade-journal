---
id: OPT-62
title: Short call opening orders don't merge into existing chains with open stock lots
status: Done
priority: High
assignee: Steve Johnson
created: 2026-02-15
completed: 2026-02-16
labels: [Bug]
related: [OPT-63]
linear_url: https://linear.app/optionedge/issue/OPT-62/short-call-opening-orders-dont-merge-into-existing-chains-with-open
---

# OPT-62: Short call opening orders don't merge into existing chains with open stock lots

## Summary

When a user opens a short call (STO) against shares they already own, the call creates a new chain instead of merging into the existing chain that holds the shares. This means covered call positions are fragmented — the stock sits in one chain (or no chain at all) and each round of calls gets its own separate chain.

## Root Cause

In `order_processor.py` `_derive_chains()` (line \~670), the merge-target check for opening orders only fires for **stock-only** orders:

```python
is_stock_only = all(tx.strike is None for tx in order.transactions)
if is_stock_only:
    merged_into = self._find_stock_merge_target(...)
```

There is no corresponding check for option-only opening orders (e.g., STO calls) to see if an existing chain holds open stock lots on the same underlying/account. The merge logic is one-directional.

## Real-World Impact

IBIT in account 5WZ26959: shares have been held continuously since March 2025, with covered calls written repeatedly. The result is **18 separate chains** — all labeled "Covered Call" or "Short Call" — with the actual shares outside the chain system entirely.

## Expected Behavior

When a short call opening order arrives and there's an existing open chain on the same underlying/account with open stock lots, the call order should merge into that chain. This correctly models the covered call relationship.

## Constraints

* Should only merge STO calls into stock chains, not arbitrary option strategies (e.g., don't merge an Iron Condor opening into a stock chain)
* Quantity awareness: only merge if the number of calls is ≤ the number of shares / 100
* If no stock chain exists (e.g., shares have `order_id=None`), behavior is unchanged — this is where OPT-57 manual merge fills the gap

## Related

* OPT-57: Manual chain merge (covers cases where automatic detection isn't possible)

## Comments

### 2026-02-15 — Steve Johnson

## Update: Chain Groups may be the better solution

Investigation of this bug led to a deeper design discussion. Rather than modifying chain derivation logic to physically merge STO calls into stock chains, a "Chain Groups" concept may address this more cleanly.

See comment on OPT-57 for the full chain groups design exploration.

Key insight: the real need is aggregate P&L across related chains feeding into the Positions page cost basis — not physically combining chains into one. Chain groups achieve this non-destructively while preserving individual chain granularity.

Putting this on hold pending further design input on the chain groups approach.

---

### 2026-02-16 — Steve Johnson

I'm going to mark this Done for now. I think the whole thing goes away with the new Ledger model.
