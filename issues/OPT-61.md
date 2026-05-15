---
id: OPT-61
title: All settings need to be in the DB
status: Backlog
priority: None
assignee: Steve Johnson
created: 2026-02-15
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-61/all-settings-need-to-be-in-the-db
---

# OPT-61: All settings need to be in the DB

Currently some settings from the Setting page are stored in browser local data. Everything should be in the DB for browser independence.

## Comments

### 2026-02-15 — Steve Johnson

STRATEGY_TARGETS is one groups of settings already in the DB. Not sure if it would be worth refactoring them into a SETTINGS table. Maybe they should be left as a 1st class entity.
