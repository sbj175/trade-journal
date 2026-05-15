---
id: OPT-10
title: Sync slow on Chains page
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-03
completed: 2026-02-03
labels: [Improvement]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-10/sync-slow-on-chains-page
---

# OPT-10: Sync slow on Chains page

See if there are any optimizations that can be done to speed up the Sync on the Chains page

## Comments

### 2026-02-03 — Steve Johnson

Optimize sync performance with incremental chain processing

* Skip chain reprocessing entirely when no new transactions saved
* Add incremental processing for small syncs (<50 new txns, <=10 underlyings)
* Only reprocess affected underlyings instead of all 270 chains
* Parallelize account position fetching using ThreadPoolExecutor
* Eliminate duplicate strategy detection by using cached values
* Add incremental cache updates that only clear/rebuild affected chains
