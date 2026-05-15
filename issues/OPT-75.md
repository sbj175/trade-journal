---
id: OPT-75
title: Break up the monolithic code files into more manageable pieces
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-19
started: 2026-02-20
completed: 2026-02-23
labels: [Bug, SaaS Migration]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-75/break-up-the-monolithic-code-files-into-more-manageable-pieces
---

# OPT-75: Break up the monolithic code files into more manageable pieces


## Comments

### 2026-02-20 — Steve Johnson

All 3 phases complete and merged to main:

**Phase 1** — Extracted schemas (`src/schemas.py`), dependencies (`src/dependencies.py`), and 4 service modules (`src/services/`) from `app.py`

**Phase 2** — Split 47 routes into 11 focused APIRouter files (`src/routers/`). `app.py` reduced from 3,971 → 121 lines

**Phase 3** — Extracted shared JS utilities (`static/js/utils.js`) and constants (`static/js/constants.js`). Removed ~90 lines of duplicated inline JS from 4 HTML files

Final structure:
- `app.py`: 121 lines (was 3,971)
- `src/schemas.py`: 9 Pydantic models
- `src/dependencies.py`: 8 singletons
- `src/services/`: 4 service modules (~1,600 lines)
- `src/routers/`: 11 router files (~1,900 lines)
- `static/js/`: 2 shared JS files
