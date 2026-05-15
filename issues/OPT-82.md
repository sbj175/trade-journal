---
id: OPT-82
title: Ledger page should aggregate share lots into a position row which can in turn be expanded to show the lots
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-19
started: 2026-02-19
completed: 2026-02-19
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-82/ledger-page-should-aggregate-share-lots-into-a-position-row-which-can
---

# OPT-82: Ledger page should aggregate share lots into a position row which can in turn be expanded to show the lots


## Comments

### 2026-02-19 — Steve Johnson

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/8ac55190-0e8b-4d8e-8baa-54aa554a7e94/9d0091ca-35a3-40d8-8562-d1a47f52a971)

---

### 2026-02-19 — Steve Johnson

Implemented equity lot aggregation on the Ledger page (`static/ledger-dense.html`). Frontend-only change — no backend modifications.

**What changed:**
- Added 3 helper methods: `sortedOptionLots()`, `openEquityLots()`, `equityAggregate()`
- Split the lot rendering into two sections:
  - **Section A**: Equity aggregate row — shows total qty, avg price, total cost basis for all open equity lots. Expandable to reveal individual lots, each with its own expand for opening events.
  - **Section B**: Option lots + closed equity lots — rendered individually as before, with open/closed separator preserved.
- Subtle separator between sections A and B when both exist.

**Verification needed:**
1. IBIT in Trad IRA — should show 3 option lots + 1 aggregated "Shares" row (not 3 + 17)
2. Expand Shares summary → see 17 individual equity lots
3. Expand an individual equity lot → see BTO opening event
4. Pure spread groups (no equity) — unchanged rendering
5. Groups with closed equity lots — closed lots still appear individually in section B
