---
id: OPT-64
title: Allow user to override strategy label on order chains
status: Done
priority: Low
assignee: Steve Johnson
created: 2026-02-16
completed: 2026-02-17
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-64/allow-user-to-override-strategy-label-on-order-chains
---

# OPT-64: Allow user to override strategy label on order chains

## Summary

Add the ability for users to manually override the auto-detected strategy label on an order chain. Our strategy detection is good but not perfect — users know their own trading intent and should be able to correct or customize the label.

## Motivation

* Auto-detection can misidentify strategies (e.g., labeling something "Multi-Leg Strategy" when the user knows it's a Jade Lizard)
* Users may have their own naming conventions or want more specific labels
* Wingman offers this feature ("change strategy label") and it's a natural UX expectation
* Inspired by OPT-63 competitive analysis

## Proposed Approach

* Add an edit icon or click-to-edit on the strategy label in the Chains page
* Store the user override in the `order_chains` table (new column `user_strategy_type` or similar)
* Display the user override when set, falling back to auto-detected `strategy_type`
* User override should survive re-sync (partial sync won't touch it; full resync should preserve user overrides)
* Consider a dropdown of known strategies plus a free-text option

## Edge Cases

* What happens on full resync? The auto-detected `strategy_type` may change but the user override should be preserved in its own column
* Reports page aggregation should use the displayed label (user override if set, else auto-detected)
