---
id: OPT-88
title: Why is there a WOLF1 symbol in the Roth IRA?
status: Canceled
priority: Low
assignee: Steve Johnson
created: 2026-02-20
started: 2026-02-20
canceled: 2026-02-20
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-88/why-is-there-a-wolf1-symbol-in-the-roth-ira
---

# OPT-88: Why is there a WOLF1 symbol in the Roth IRA?


## Comments

### 2026-02-20 — Steve Johnson

## Findings

`WOLF1` is an **OCC adjusted option symbol** from a corporate action on Wolfspeed (WOLF). The OCC appends a number to tickers when deliverables change due to mergers, spinoffs, reverse splits, etc.

### Transaction History (Roth IRA - 5WZ28644)

| Date | Action | Symbol | Value |
|------|--------|--------|-------|
| May 14, 2025 | STO | WOLF 250620P3 | +$97 |
| Jun 2 | BTC/STO roll | WOLF 250815P3 | -$196/+$226 |
| Jul 25 | BTC/STO roll | WOLF 250919P3 | -$151/+$180 |
| Aug 29 | BTC/STO roll | WOLF 251017P3 | -$188/+$207 |
| **Sep 29** | BTC/STO roll | WOLF→**WOLF1** 251017P3 | -$207/+$207 |
| Oct 17 | Assignment | WOLF1 251017P3 | $300 (shares) |

### What Happened

The Sep 29 roll is where the symbol changed. The system correctly tracked the WOLF chain through 4 rolls, but when the symbol changed to WOLF1, it created a new chain:

- **WOLF chain**: $175 realized (5 orders, May–Sep) — CLOSED
- **WOLF1 chain**: $300 realized (2 orders, Sep–Oct, assigned) — CLOSED

### Impact

Both chains are CLOSED so this only affects the Ledger view — WOLF1 appears as a separate underlying when it's really a continuation of the WOLF trade. This is a known limitation: the chain system keys on underlying symbol, so symbol changes from corporate actions break the chain linkage.

### Possible Fix

Could add a symbol alias/mapping table to link adjusted symbols (WOLF1→WOLF) so they group under the same underlying. Low priority since both are closed and P&L is correct — it's just a cosmetic grouping issue.

---

### 2026-02-20 — Steve Johnson

Closing. Not a bug.
