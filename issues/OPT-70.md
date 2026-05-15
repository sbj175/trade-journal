---
id: OPT-70
title: Ledger Positions view: clean up cost basis, realized P&L, and $0.00 display
status: Done
priority: Medium
assignee: Steve Johnson
created: 2026-02-18
started: 2026-02-18
completed: 2026-02-18
labels: [Improvement]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-70/ledger-positions-view-clean-up-cost-basis-realized-pandl-and-dollar000
---

# OPT-70: Ledger Positions view: clean up cost basis, realized P&L, and $0.00 display

## Changes

Refine the Ledger Positions view to reduce visual noise and better align with standard accounting display (modeled after Wingman):

1. **Blank cost basis for closed legs**: Don't show a cost basis dollar amount when a lot's status is CLOSED — leave it blank. The status column already indicates "CLOSED", and cost basis is only meaningful for open positions.
2. **Remove realized P&L from closing transaction rows**: Only show realized P&L at the leg (lot) level, not on individual closing transaction sub-rows. The leg-level number is the summary; the transaction-level number is redundant.
3. **Suppress $0.00 values**: Don't display "$0.00" — show blank/dash instead. Applies to cost basis, realized P&L, total P&L, and entry price where the value is zero.
4. **Better column alignment between leg and transaction rows**: Ensure the expanded transaction sub-rows (opening + closing events) visually align their columns with the parent lot row above them.

## Comments

### 2026-02-18 — Steve Johnson

Merged to main. Changes:
- Blank cost basis for closed legs
- Remove realized P&L from closing transaction sub-rows
- Suppress $0.00 values across all columns
- Fix column alignment between leg and transaction rows
- Remove redundant Total P&L column (was identical to Realized)
- Increase header and sub-row fonts to match data rows
- Add spacing between Entry $ and Cost Basis columns

---

### 2026-02-18 — Steve Johnson

Reopened and fixed equity lot alignment issues on the Ledger Positions view. Three changes:

1. **Column alignment**: Removed `ml-6` from derived lot rows (was shifting all columns right). The `↳` derivation indicator now renders inside the Entry Date column so Qty/Exp/Strike/Status/etc. stay grid-aligned with headers.

2. **Cost basis wrapping**: Added `whitespace-nowrap` to transaction sub-row cost basis to prevent large equity amounts ($248,000.00 cr) from line-wrapping.

3. **Strike styling**: Removed the pill background from the Strike column when empty (equity rows). The "—" with a styled background looked cluttered for share rows — now shows as plain muted text.
