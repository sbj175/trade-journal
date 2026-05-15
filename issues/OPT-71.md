---
id: OPT-71
title: Call assignment creates equity lot with wrong direction
status: Done
priority: High
assignee: Steve Johnson
created: 2026-02-18
started: 2026-02-18
completed: 2026-02-18
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-71/call-assignment-creates-equity-lot-with-wrong-direction
---

# OPT-71: Call assignment creates equity lot with wrong direction

## Bug

When a short call is assigned, the system creates a derived equity lot with positive quantity (+800 shares, BTO) instead of negative quantity (-800 shares, STC). The raw transaction has action `SELL_TO_CLOSE` but `create_derived_lot()` in `lot_manager.py` takes `quantity` directly from the transaction, which is always positive. The sign should be determined by the option type or action.

**Example**: MSTR account 5WZ28644

* Sep 26: STO 8 Call 310 @ 9.65
* Oct 3: Assignment → equity transaction is "Sell to Close 800 MSTR @ 310.00"
* Lot created: +800 shares OPEN (wrong — should be -800 or should close existing long shares)

## Root Cause

`lot_manager.py:311-314` — `quantity = int(stock_transaction.get('quantity', 0))` always gets a positive number. The comment says "the transaction already has the correct sign" but it doesn't — raw transaction quantities are always positive.

## Fix

Use the source option type to determine direction:

* Short **Put** assigned → user buys shares → positive quantity (correct today)
* Short **Call** assigned → user sells/delivers shares → negative quantity (broken today)

## Related

* OPT-69: Equity lots from synced stock transactions (the subsequent equity sells that should close these lots aren't processed)

## Comments

### 2026-02-18 — Steve Johnson

Fixed and merged to main.

**Code fix**: `lot_manager.py:create_derived_lot()` — now uses the source option type to determine equity lot direction. Call assignment → negative quantity (sell/deliver), put assignment → positive quantity (buy/receive).

**Data fix**: Corrected 4 existing lots with wrong direction:
- HUT lot 32323: 100 → -100
- OKLO lot 32327: 1600 → -1600
- OKLO lot 32329: 400 → -400
- MSTR lot 32358: 800 → -800
