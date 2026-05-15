---
id: OPT-78
title: Unify Positions page grouping with Ledger (equity + options)
status: Done
priority: Medium
assignee: Steve Johnson
created: 2026-02-19
completed: 2026-02-19
labels: [Improvement]
related: []
parent: OPT-73
linear_url: https://linear.app/optionedge/issue/OPT-78/unify-positions-page-grouping-with-ledger-equity-options
---

# OPT-78: Unify Positions page grouping with Ledger (equity + options)

On the Ledger page, shares and options for the same underlying (e.g., IBIT covered calls) are grouped together in the same position group. On the Positions page, shares and option chains showed up as separate rows.

**Fixed:** Switched Positions page to source all data from `position_lots`/`position_groups`, eliminating the `positions` table dependency. Groups with both equity and option lots now display as a single unified row.
