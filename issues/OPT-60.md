---
id: OPT-60
title: Drop tables
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-15
started: 2026-02-18
completed: 2026-02-18
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-60/drop-tables
---

# OPT-60: Drop tables

OPTION_LEGS, STOCK_LEGS, TRADES tables are empty.

Make sure they're not used first, but they are currently empty and appear to be not used.

## Comments

### 2026-02-18 — Steve Johnson

Done. Confirmed all three tables were empty (0 rows) and unused by application code, then:

- Dropped `option_legs`, `stock_legs`, `trades` from the database
- Removed 4 legacy cleanup scripts: `backup_legacy_tables.py`, `backup_obsolete_tables.py`, `drop_legacy_tables.py`, `LEGACY_CLEANUP_SUMMARY.md`
- Added `*.db.bak` to `.gitignore`
