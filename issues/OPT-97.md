---
id: OPT-97
title: Filter expired option legs from Positions page
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-22
started: 2026-02-22
completed: 2026-02-22
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-97/filter-expired-option-legs-from-positions-page
---

# OPT-97: Filter expired option legs from Positions page

Follow-up from OPT-96 research. Filter expired option legs (DTE ≤ 0) at the API level so they don't appear on the Positions page. They'll be properly closed on next sync — this just hides them from display.\\n\\nChanges:\\n- `src/routers/positions.py`: Skip option lots with past expiration dates when building API response\\n- `static/positions-dense.html`: Remove DTE clamp to 0 for consistency with getMinDTE()
