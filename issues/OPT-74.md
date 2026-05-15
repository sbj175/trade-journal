---
id: OPT-74
title: There is a bug in the time filtering on the Ledger
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-19
started: 2026-02-20
completed: 2026-02-20
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-74/there-is-a-bug-in-the-time-filtering-on-the-ledger
---

# OPT-74: There is a bug in the time filtering on the Ledger

I just closed LQDA today, but it does not show when I select the "7D" time filter.

## Comments

### 2026-02-20 — Steve Johnson

Fixed. The time filter in `applyFilters()` only checked `opening_date`, so a position opened 2+ weeks ago but closed today would be hidden under the 7D filter. Now the filter includes groups where **either** the opening or closing date falls within the selected time period.
