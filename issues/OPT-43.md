---
id: OPT-43
title: Wingman parity
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-07
started: 2026-02-14
completed: 2026-03-22
labels: [Research]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-43/wingman-parity
---

# OPT-43: Wingman parity

[https://wingmantracker.com/](<https://wingmantracker.com/>)

## Comments

### 2026-02-14 — Steve Johnson

Review the claims on the given URL and 1) make sure we have the data to calculate all of those things, 2) if not, figure out what is needed

---

### 2026-02-14 — Steve Johnson

## Wingman Tracker Parity Research

Completed a thorough analysis comparing Wingman Tracker ($49/mo SaaS) features against OptionLedger.

### Score: 19 features at parity/better, 10 gaps, 5 areas where we're already ahead

**OptionLedger advantages over Wingman:**

* Live API sync (vs CSV import)
* Real-time WebSocket quotes (vs 15-min delayed)
* DTE tracking with visual warnings
* Price position indicators for spreads
* Full Risk Dashboard (Greeks, Black-Scholes, scenario analysis)

**Key gaps to close:**

1. Avg P&L per day metric
2. Fee tracking/reporting (data exists in raw_transactions, not surfaced)
3. Filter reports by underlying
4. Running P&L chart (cumulative over time)
5. Cumulative cost basis / breakeven display
6. Custom position tags + tag performance analysis
7. Bucketed reports (by underlying, by tag)

**Critical finding: All 9 achievable gaps can be closed with data already in our database.** No new API calls needed — these are purely data presentation/aggregation features.

Lower priority gaps (manual leg regrouping, sharing/export, dividend tracking) are nice-to-haves that don't affect core parity.
