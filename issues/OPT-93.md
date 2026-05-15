---
id: OPT-93
title: Ability to move shares by Leg
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-20
started: 2026-02-20
completed: 2026-02-20
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-93/ability-to-move-shares-by-leg
---

# OPT-93: Ability to move shares by Leg

Currently shares can only be moved by selecting each lot

## Comments

### 2026-02-20 — Steve Johnson

## Plan: Move Shares by Leg (OPT-93)

### Problem

When a group has multiple equity lots (e.g., 5 separate share purchases or assignment events), the user must check each lot's checkbox individually to move them. For a group with 10 equity lots, that's 10 clicks before you can even start the move.

### Current Flow
1. Click move icon on group → checkboxes appear next to every lot
2. Check each equity lot one at a time
3. Click target group or "+ New Group"

### Proposed Changes

**Add a "select all" checkbox to the equity aggregate row.**

When the group is in move mode and the equity aggregate row is visible, show a checkbox on the aggregate row. Checking it selects/deselects all open equity lots in that group at once.

#### Frontend changes (ledger-dense.html only)

**1. Aggregate-level checkbox** — Add a checkbox to the equity aggregate summary row (the collapsed "X lots | Total Qty | Avg Price" row). When checked, all open equity lot `transaction_id`s get added to `selectedLots`. When unchecked, they all get removed.

```javascript
toggleAllEquityLots(group) {
    const eqLots = this.openEquityLots(group);
    const ids = eqLots.map(l => l.transaction_id);
    const allSelected = ids.every(id => this.selectedLots.includes(id));
    if (allSelected) {
        this.selectedLots = this.selectedLots.filter(id => !ids.includes(id));
    } else {
        const newIds = ids.filter(id => !this.selectedLots.includes(id));
        this.selectedLots.push(...newIds);
    }
}
```

**2. Visual state** — The aggregate checkbox shows:
- Checked: all open equity lots selected
- Indeterminate: some selected
- Unchecked: none selected

**3. Auto-expand** — When the aggregate checkbox is checked, auto-expand the equity section so the user can see which lots are selected.

#### No backend changes needed

The existing `/api/ledger/move-lots` endpoint already accepts a list of `transaction_ids` — it doesn't care whether they were selected individually or in bulk. No schema or API changes required.

### Scope
- **In scope**: Aggregate-level select-all checkbox for equity lots in move mode
- **Out of scope**: Option leg grouping (options are typically 1-2 lots per group, individual selection is fine)

### Estimate
Small change — ~20 lines of JS + ~10 lines of HTML template. No backend work.
