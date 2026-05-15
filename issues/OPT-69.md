---
id: OPT-69
title: Create equity lots from synced stock transactions
status: Done
priority: Low
assignee: Steve Johnson
created: 2026-02-17
started: 2026-02-18
completed: 2026-02-18
labels: [Bug]
related: [OPT-68]
linear_url: https://linear.app/optionedge/issue/OPT-69/create-equity-lots-from-synced-stock-transactions
---

# OPT-69: Create equity lots from synced stock transactions

## Context

The `OrderProcessor` currently filters out pure equity transactions (lines 258-266 of `order_processor.py`) — only option transactions and assignment/exercise events create `position_lots`. Stock purchase/sale transactions exist in `raw_transactions` but are skipped during chain processing.

This means equity positions have no `position_lot` records and can't participate in the group management system. They're displayed on the Positions page via a separate path (TT API `positions` table).

## Proposal

Extend the `OrderProcessor` to create `position_lots` for equity transactions (buys and sells). This would allow stock positions to be:

* Displayed on the Ledger alongside option lots
* Moved into position groups with related options (e.g., shares + covered calls in one group)
* Tracked with the same lot lifecycle (open → partial → closed) as options

## Per-Lot Cost Basis Tracking

Each share buy/sell should create its own lot, just like options do today. For example, buying 1,000 shares at $50 and then 500 shares at $45 should produce two distinct lots, each with its own `entry_price`, `quantity`, and `entry_date`. When shares are sold, FIFO matching closes against the earliest lot first, giving accurate per-lot realized P&L and correct cost basis throughout.

This is important for:

* Accurate realized P&L on partial sales (which lot was sold matters)
* Correct remaining cost basis after partial closes
* Tax lot tracking (FIFO matches what most brokers report)
* Meaningful per-lot display on the Ledger (see exactly when and at what price each tranche was acquired)

The lot system already handles this for options — equity just needs the same treatment.

## Reconciliation Against Broker Positions

Transaction history processing may not always produce the same share count as the TT positions API reports (e.g., shares transferred in from another broker, pre-sync holdings, stock splits, corporate actions). A reconciliation step should compare lot-derived share totals against TT's reported quantity and create adjustment lots when there's a mismatch.

This is the same pattern already used for options — `reconcile_positions_vs_chains` compares TT positions against lot-derived quantities. As of 2026-02-17, option reconciliation shows 74/74 matched with zero mismatches, confirming the lot system accurately tracks option positions. Equity reconciliation would be an extension of the same mechanism.

Adjustment lots could be flagged with `derivation_type = 'RECONCILIATION'` to distinguish them from transaction-derived lots. The TT positions API provides average price which can be used as the entry price for adjustment lots.

Note: this same reconciliation pattern could also be applied to options if mismatches ever arise in the future (missed transactions, corporate actions, etc.), though no option mismatches exist today.

## Implementation Notes

* The equity transactions are already in `raw_transactions` — no additional sync needed
* Equity lots would have `instrument_type = 'EQUITY'`, no `option_type`/`strike`/`expiration`
* FIFO closing should work naturally (buy creates lot, sell closes it)
* Need to decide how equity lots relate to chains — they could be standalone or grouped with option chains for the same underlying
* The Ledger frontend already handles `instrument_type === 'EQUITY'` display (shows "Shares" / "Stk")
* The Positions page would need to transition from TT API equity display to lot-based equity display once lots are reliable

## Relationship to Other Issues

* Enables the unified covered call tracking use case described in [OPT-68](https://linear.app/optionedge/issue/OPT-68/manual-position-entry-for-pre-sync-holdings)
* [OPT-68](https://linear.app/optionedge/issue/OPT-68/manual-position-entry-for-pre-sync-holdings) (manual position entry) would still be needed for shares transferred in from another broker or acquired before TT history begins
* This issue covers the common case (shares bought/sold through TT); [OPT-68](https://linear.app/optionedge/issue/OPT-68/manual-position-entry-for-pre-sync-holdings) covers the edge case

## Comments

### 2026-02-18 — Steve Johnson

## Implementation Complete — `opt-69-equity-lots-from-stock-transactions`

### Changes Made

**`src/models/lot_manager.py`**
- Added `close_long: Optional[bool] = None` parameter to `close_lot_fifo()` — filters lots by direction (long/short) so equity sells only close long lots and vice versa, while preserving backward-compatible `None` default for options.

**`app.py`**
- New `process_equity_transactions()` function:
  - Queries `raw_transactions` for `InstrumentType.EQUITY` + `Trade` type
  - BUY_TO_OPEN/SELL_TO_OPEN → creates lots via `lot_manager.create_lot()` with `chain_id=''`
  - SELL_TO_CLOSE → calls `close_lot_fifo(close_long=True)` to close long positions
  - BUY_TO_CLOSE → calls `close_lot_fifo(close_long=False)` to close short positions
  - Idempotent: skips already-processed transaction IDs
- Wired into all 3 sync flows (full reprocess, initial sync, explicit reprocess)
- Extended `reconcile_positions_vs_chains()` to include `EQUITY` instrument type in all 4 queries (lot aggregation, TT position filter, stale auto-close, ghost group detection)

### Verification Steps
1. Reprocess Chains to trigger equity lot processing
2. Check MSTR Ledger — assignment lots (+200, +500) should show CLOSED from Oct 15 sells
3. Check other equity symbols (IBIT, SLV, GLD) for correct buy/sell lot matching
4. Run Reconciliation — equity positions should now appear in comparison
5. Verify option processing is unaffected (direction filter defaults to None)

---

### 2026-02-18 — Steve Johnson

Merged to main. MSTR Ledger verified — all equity lots correctly created and closed:
- ACAT +900 shares → STC -100 → netting closes remaining +800 against call assignment -800
- Put assignment +200/+500 → STC -700 closes both
- Covered Call group shows -800 shares CLOSED via netting pass

Two commits:
1. Core implementation: equity lot creation/closing from Trade transactions, direction-aware FIFO, reconciliation extension
2. Follow-up fix: include Receive Deliver transactions (ACAT) and netting pass for opposing lots
