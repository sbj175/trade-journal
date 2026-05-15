---
id: OPT-5
title: Possible Chains bug
status: Done
priority: None
assignee: Steve Johnson
created: 2026-01-31
completed: 2026-02-03
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-5/possible-chains-bug
---

# OPT-5: Possible Chains bug

Multiple-order chain Cost Basis may be wrong - needs investigation

Example: Roth HSBC chain started with order 429067175 which was supposed to be 5 contracts, but made it 1 by accident. Followup order 429071334 for 4 contracts was correctly added to the chain making it 5 contracts total, but not sure the cost basis is correct. Current P&L shows 303.00 and per shares Cost Basis shows 3.03. TT uses "Avg Trade" and shows 0.61.
