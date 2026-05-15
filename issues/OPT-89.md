---
id: OPT-89
title: %Max on Credit spreads?
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-20
started: 2026-02-23
completed: 2026-02-23
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-89/percentmax-on-credit-spreads
---

# OPT-89: %Max on Credit spreads?

Does it make sense, or is it redundant with %Return?

## Comments

### 2026-02-20 — Steve Johnson

## Analysis: % Max vs % Return on Credit Spreads

### How each is calculated

**% Return** (`getGroupPnLPercent`):
```
Open P&L / |Cost Basis| × 100
```
For a credit spread, cost basis = credit received (positive). So this is `P&L / credit received`.

**% Max** (`getGroupMaxPercent`):
```
Open P&L / Max Profit × 100
```
For a credit spread, max profit = credit received (i.e., `|cost basis|`). So this is also `P&L / credit received`.

### Verdict: They are identical for credit spreads

For credit spreads, max profit equals the credit received, which equals `|cost basis|`. Both formulas divide current P&L by the same denominator. **% Max and % Return will always show the same number for credit spreads.**

### Where they differ

For **debit spreads**, they diverge:
- **% Return** = P&L / debit paid (cost basis)
- **% Max** = P&L / (spread width × 100 × contracts - debit paid)

Example: $2 wide Bull Call Spread bought for $80. Max profit = $120.
- If P&L is +$60: % Return = 75%, % Max = 50%

So % Max adds real value for debit spreads but is redundant for credit spreads.

### Options
1. **Keep as-is** — redundant but not harmful, and consistent display across all spreads
2. **Hide % Max for credit spreads** — show `—` when the position is a credit spread, only display for debit spreads where it's informative
3. **Relabel** — rename % Max to "% of Max Profit" to make the distinction clearer even when values overlap
