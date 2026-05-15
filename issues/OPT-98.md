---
id: OPT-98
title: Migrate from deprecated on_event to lifespan context manager
status: Backlog
priority: Low
assignee: Steve Johnson
created: 2026-02-23
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-98/migrate-from-deprecated-on-event-to-lifespan-context-manager
---

# OPT-98: Migrate from deprecated on_event to lifespan context manager

The `@app.on_event("startup")` pattern in `app.py:80` is deprecated since FastAPI 0.93.0 (March 2023). The recommended replacement is the `lifespan` async context manager.

**Why switch:**

* If any future dependency sets `lifespan=` on the app, our `on_event` handler would be silently ignored — no warning, no error
* `on_event` will be removed in Starlette 1.0
* Co-locates startup/shutdown logic in one function (we only have startup today, but cleaner for future shutdown needs)

**Scope:** Single refactor — one `@app.on_event("startup")` in `app.py`, no shutdown handler, no third-party conflicts. Low risk.
