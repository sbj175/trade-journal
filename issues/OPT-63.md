---
id: OPT-63
title: Research: Wingman trial — competitive analysis for chain grouping design
status: Done
priority: Medium
assignee: Steve Johnson
created: 2026-02-15
started: 2026-02-17
completed: 2026-03-22
labels: [Research]
related: [OPT-57, OPT-62]
linear_url: https://linear.app/optionedge/issue/OPT-63/research-wingman-trial-competitive-analysis-for-chain-grouping-design
---

# OPT-63: Research: Wingman trial — competitive analysis for chain grouping design

## Summary

Evaluating Wingman as a reference for how they handle position grouping, roll tracking, and cumulative P&L — directly relevant to the chain groups design being explored in [OPT-57](https://linear.app/optionedge/issue/OPT-57/manual-chain-merge-select-and-merge-chains-within-the-same-underlying) and [OPT-62](https://linear.app/optionedge/issue/OPT-62/short-call-opening-orders-dont-merge-into-existing-chains-with-open).

## Wingman's Approach (from their site)

> **How Wingman solves these problems:**
>
> * Automatically groups options/stock/futures into positions
> * Built-in logic to auto-detect which trades belong together, even through rolls
> * Keeps old options from rolls in open, ongoing positions
>   * Ex: A Strangle rolled from April to May — keeps April options in the ongoing position
> * Tracks total debit/credit and P/L for each position, through rolls, assignments, dividends, etc.
>   * Know your cumulative cost basis immediately — no digging up history. Bake in the realized P/L from rolls/dividends/assignments/commission.
> * In-depth, customizable performance analysis at the position level
> * And Wingman lets you create custom tags to bucket performance your way.

## What to evaluate during trial

* How does Wingman define a "position" vs our "chain"? Is it more like our proposed "chain group"?
* How does auto-detection work through rolls — especially for Iron Condors (4-leg limit on TT)?
* How does the cumulative cost basis display work? Where does it show up?
* How are closed options from rolls displayed within an ongoing position?
* Custom tags — is this similar to our chain group concept? How granular?
* How does it handle ACAT-transferred shares with no order history?
* How does performance analysis aggregate at the position level?

## Related issues

* OPT-57: Manual chain merge / chain groups design
* OPT-62: STO calls not merging into stock chains

## Comments

### 2026-02-15 — Steve Johnson

## Initial findings from Wingman trial

- Positions are **automatically grouped by underlying** — no manual grouping needed
- A "Covered Call" is the **position name**, not a strategy on an individual order/chain
- The position has legs:
  - Leg 1: shares
  - Leg 2: calls
- This is fundamentally different from our model where each call cycle is a separate chain. In Wingman, the entire thing is one "position" with the shares and calls as legs within it.

**Key takeaway**: Wingman's "position" is conceptually equivalent to our proposed "chain group" — a container that holds all related activity on an underlying. The difference is they do it automatically, we're considering user-initiated.

---

### 2026-02-15 — Steve Johnson

## Onboarding flow

Wingman does NOT use API integration. It's CSV-based:

1. **Account setup**: Import a CSV of current positions (portfolio snapshot) exported from TT desktop
2. **Trade history**: Import a separate CSV of transactions
3. Going forward, you import new transaction CSVs to keep it updated

> "To add a brokerage account, you will import a CSV file that snapshots your current portfolio. Note: this is a different CSV file from the one you'll use to import trades going forward."

**Key differences from our approach**:
- We use live API (OAuth2) for real-time sync — no manual CSV exports
- They need two separate imports (positions snapshot + transaction history) to bootstrap
- Their position grouping logic presumably runs on the imported CSV data, not live API data
- No real-time quotes or WebSocket streaming (TBD — need to verify)

---

### 2026-02-16 — Steve Johnson

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/cc212a5f-779d-4cfc-ae62-106092961bbb/ec92b3e8-ee35-403f-9f26-207c43c104ba)

---

### 2026-02-16 — Steve Johnson

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/37b5f8c5-6316-4cdb-bac0-affd4b41db5b/c203347b-00c2-40ad-8b9d-8c6cc1d2ce46)

---

### 2026-02-16 — Steve Johnson

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/d3dc9381-0eb8-47a9-ba59-98d3f285a801/4329e81b-1c09-419b-80e6-15016a18a73d)

Get a load of this crap "Note: The earliest date allowed is the day you added the account to Wingman."

---

### 2026-02-16 — Steve Johnson

## Major limitation: no historical transaction import

From the Import Trades page:

> "Note: The earliest date allowed is the day you added the account to Wingman."

Wingman cannot ingest transactions from before signup. The initial positions CSV only provides a current snapshot — no history. This means:

- No historical P&L or roll chain reconstruction
- Cost basis for existing positions is limited to the snapshot data
- Any analysis of past performance requires manual entry or is simply unavailable
- The "cumulative cost basis" they advertise only works going forward from signup

**Our advantage**: We pull full transaction history from TT's API. All historical chains, rolls, and P&L are available from day one. The chain grouping problem we're solving is about *presentation* of data we already have — not a data availability gap.

---

### 2026-02-16 — Steve Johnson

## Import limitations: 500 transaction cap per file

Attempted to import full history for one account (888 transactions). Result:

> "Something isn't quite right. We can't process a file larger than 500 transactions at a time. Please try exporting in smaller date-range chunks (in chronological order)."

So the actual onboarding workflow for 3 TT accounts would be:
1. 3 position snapshot CSVs (one per account)
2. 3+ transaction CSVs per account (split into ≤500 transaction chunks, in chronological order)
3. Minimum **9+ file exports and imports** just to get started
4. No historical data before signup date anyway (per previous finding)
5. And this is a **manual, recurring process** for ongoing updates

**Our approach**: One-click sync pulls all transactions across all accounts via API. No file exports, no chunking, no manual imports. The IBIT account alone has thousands of transactions imported seamlessly.

**Verdict so far**: Wingman's position grouping UX may be worth studying, but their data pipeline is significantly weaker than ours.

---

### 2026-02-16 — Steve Johnson

One thing they do which is interesting is they keep track of individual stock transactions as well.

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/7687da41-8007-4c10-bf58-289df4119e74/51b99ed0-a304-4ea0-a253-ba2dd43e200b)

---

### 2026-02-16 — Steve Johnson

The app presents an API - here's the documentation: [https://docs.wingmantracker.com/api-documentation](<https://docs.wingmantracker.com/api-documentation>)

---

### 2026-02-16 — Steve Johnson

I imported my entire history for one TT account (ignoring their message about not importing prior transactions). The app accepted the transactions gracefully, but they all showed up in the Open Positions tab. Apparently you have to mark them closed manually. They do surface a message telling you about it.

![image.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/56653b95-799d-465f-8fc6-662ebacad6a1/308cc068-59a0-4cc9-92fc-8fbf24381e38)

---

### 2026-02-16 — Steve Johnson

## ORCL position display

![img_47.png](https://uploads.linear.app/368b4f80-8415-4c32-ba2e-38cfe8af53f0/7cb2572d-a71a-4255-8e03-86b36ba12a45/ae1ec5b6-c7ed-4e37-844c-d9b14fb886e4)

Screenshot shows Wingman's expanded view for ORCL with "Cost Basis Mode" active.

### What they show

* **ORCL** grouped at underlying level — "2 uploaded today, 1 to close"
* **Vertical (Long Put) 165/175** — Closed, 0 contracts, Realized P/L: $648.98
  * Leg: 175 PUT — Closed, 2 contracts sold to close, then 0 remaining
  * Leg: 165 PUT — Closed, 2 contracts bought to close
* **Vertical (Long Put) 145/155** — Open, shows 2 contracts, P/L: -$2.24
  * Leg: 155 PUT — 2 contracts (1 opened 2/3, 1 opened 2/15)
  * Leg: 145 PUT — -2 contracts (1 sold 2/3, 1 sold 2/15)

### Bug in Wingman's display

The 145/155 spread shows **2 contracts open**, but in reality it was **partially closed** — only 1 contract remains open. Our app handles this correctly and shows the partial close.

This is notable because their auto-grouping UX is slick, but the underlying position tracking has accuracy issues that our system gets right.

### UI observations worth noting

* Clean hierarchy: Underlying → Strategy → Legs → Transactions
* "Cost Basis Mode" vs "P/L Mode" toggle at the top — interesting dual view
* Cumulative Cost Basis column tracks running total
* Each leg shows its transactions chronologically
* Edit/tag/action icons on each strategy row
* Realized P/L shown at the strategy level (green for profit, red for loss)

---

### 2026-02-16 — Steve Johnson

## Transaction-level actions menu (img_48)

Wingman offers per-transaction actions:
- Move Transaction into New Position
- Move Transaction into Existing Position
- Duplicate Transaction
- Edit Transaction
- Delete Transaction

These are manual data correction tools needed because their CSV import pipeline is error-prone. "Move to Existing Position" is their equivalent of our chain merge concept (OPT-57).

**Assessment**: We don't need most of these. Our API sync provides clean authoritative data — no need to manually edit/duplicate/delete transactions. The "move to existing position" concept is already covered by the chain groups design in OPT-57.

---

### 2026-02-16 — Steve Johnson

## IBIT covered call comparison

### In their favor
- Wingman grouped the current IBIT 39.5/40.5/41.5 covered calls into a **single position**, despite being entered as separate orders. We split them into two chains because separate orders created separate chains. This is exactly the use case that chain groups (OPT-57) or the merge capability (OPT-62) needs to solve.

### In our favor
- Wingman **double-counted the contracts**, showing -120 each instead of the correct -60 each. Another accuracy issue in their position tracking.
- We show transaction-level data within expanded order chains
- We offer a direct link from the Positions page to the specific chain on the Chains page
- Our contract counts are accurate

### Running tally of Wingman accuracy bugs found
1. ORCL 145/155 spread: shows 2 contracts open when only 1 is (partial close not tracked)
2. IBIT covered calls: double-counted contracts (-120 shown vs -60 actual)

### Takeaway
Their grouping UX is solving the right problem (presenting related trades as one position), but their underlying data accuracy is significantly worse than ours. We need to adopt their grouping concept while maintaining our accuracy advantage.
