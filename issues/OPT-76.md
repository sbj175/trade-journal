---
id: OPT-76
title: Ledger account selector doesn't persist across page navigation
status: Done
priority: Low
assignee: Steve Johnson
created: 2026-02-19
completed: 2026-02-19
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-76/ledger-account-selector-doesnt-persist-across-page-navigation
---

# OPT-76: Ledger account selector doesn't persist across page navigation

The Ledger page account selector does not stay in sync with other pages. Selecting an account on Positions, then navigating to Ledger, resets to "All Accounts."

**Root cause:** Ledger used `selectedAccount` as the localStorage key while all other pages (Positions, Reports, Risk) use `trade_journal_selected_account`.

**Fix:** Updated Ledger to use the shared `trade_journal_selected_account` key.
