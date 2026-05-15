---
id: OPT-72
title: Align Ledger strategy labels with standard naming convention
status: Backlog
priority: Low
assignee: Steve Johnson
created: 2026-02-18
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-72/align-ledger-strategy-labels-with-standard-naming-convention
---

# OPT-72: Align Ledger strategy labels with standard naming convention

## Context

The Ledger page currently shows strategy labels like "CSP", "Covered Call", "Unknown", etc. These come from the strategy detection system and aren't standardized. Wingman uses a well-defined dropdown of strategy names that serves as a good industry-standard reference.

## Proposal

Adopt Wingman's strategy naming convention for the Ledger's strategy labels. This gives users a consistent, recognizable vocabulary and makes the rename dropdown more useful.

## Reference: Wingman Strategy Names

See `screenshots/img_70.png` for the full dropdown. The naming pattern is `{Strategy} ({Direction})`:

**Multi-leg:**

* Big Lizard (Long/Short)
* Broken Wing Butterfly (Long Call/Long Put/Short Call/Short Put)
* Butterfly (Long Call/Long Put/Short Call/Short Put)
* Calendar (Long Call/Long Put/Short Call/Short Put)
* Collar (Long/Short)
* Condor (Call/Put)
* Covered Strangle (Long/Short)
* Diagonal (Long Call/Long Put/Short Call/Short Put)
* Double Calendar (Long/Short)
* Double Diagonal (Long/Short)
* Iron Condor (Long/Short)
* Iron Fly (Long/Short)
* Jade Lizard (Long/Short)
* Ratio (Long Call/Long Put/Short Call/Short Put)
* Rev Big Lizard (Long/Short)
* Rev Jade Lizard (Long/Short)
* Risk Reversal (Long)
* Straddle (Long/Short)
* Strangle (Long/Short)
* Synthetic (Long/Short)
* Unbalanced Butterfly (Long Call/Long Put/Short Call/Short Put)
* Vertical (Long Call/Long Put/Short Call/Short Put)

**Single-leg / simple:**

* Covered (Call/Put)
* Custom
* Future (Long/Short)
* Future Calendar (Long/Short)
* Naked (Long Call/Long Put/Short Call/Short Put)
* Stock (Long/Short)

## Mapping from current labels

Some current → Wingman mappings to start:

* "CSP" / "Cash Secured Put" → **Naked (Short Put)**
* "Covered Call" → **Covered (Call)**
* "Iron Condor" → **Iron Condor (Short)**
* "Vertical" → **Vertical (Short Put)** / **Vertical (Short Call)** etc.
* "Unknown" → needs investigation or **Custom**

## Implementation

1. Update `StrategyDetector` to output Wingman-style labels
2. Add a strategy rename dropdown on the Ledger using this list
3. Map existing labels to new names during reprocessing
