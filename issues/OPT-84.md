---
id: OPT-84
title: Total Return incorrect for rolled positions on Positions page
status: Done
priority: High
assignee: Steve Johnson
created: 2026-02-20
started: 2026-02-20
completed: 2026-02-20
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-84/total-return-incorrect-for-rolled-positions-on-positions-page
---

# OPT-84: Total Return incorrect for rolled positions on Positions page

## Bug

On the Positions page, Total Return for rolled positions (roll_count > 0) is calculated as `Realized + Net Liq` instead of `Realized + Open P&L`, which inflates the total.

### Example: JNJ (1 roll)

| Field | Value |
| -- | -- |
| Cost Basis | \-$2,043.00 |
| Net Liq | $2,482.50 |
| Realized | $2,076.00 |
| Open P&L | $439.50 |
| **Displayed Total** | **$4,558.50** (Realized + Net Liq) |
| **Correct Total** | **$2,515.50** (Realized + Open P&L) |

### Root Cause

`positions-dense.html` line \~495 in `getGroupTotalPnL()`:

```javascript
if (group.roll_count > 0) {
    // For rolled chains, cost basis is already in realized,
    // so use net liq to avoid double-counting
    return realized + this.getGroupNetLiqWithLiveQuotes(group);
}
return realized + this.getGroupOpenPnL(group);
```

The rolled-chain branch uses Net Liq (market value of the position) instead of Open P&L (unrealized gain/loss). The comment claims "cost basis is already in realized" to justify using net liq, but this inflates the total by the current position's cost basis.

Non-rolled positions use the correct formula: `Realized + Open P&L`.
