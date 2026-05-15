---
id: OPT-99
title: Address codebase deprecations and anti-patterns
status: Backlog
priority: Low
assignee: Steve Johnson
created: 2026-02-23
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-99/address-codebase-deprecations-and-anti-patterns
---

# OPT-99: Address codebase deprecations and anti-patterns

Audit of deprecations and anti-patterns found in the codebase. The `on_event` deprecation is tracked separately in OPT-98.

## Actual Deprecations

### `from typing import List, Dict, Optional, ...` (19 files)

Soft-deprecated since Python 3.9. On Python 3.12, built-in types can be used directly as generics (`list`, `dict`, `str | None`). Purely cosmetic — no runtime impact.

## Anti-Patterns

### Bare `except:` clauses (13 occurrences, 5 files)

Silently swallows `KeyboardInterrupt`, `SystemExit`, and generator exit signals. Should be `except Exception:` at minimum.

* `src/routers/accounts.py` line 87
* `src/routers/ledger.py` line 91
* `src/routers/quotes.py` line 180
* `src/models/order_models.py` lines 1062, 1073, 2460
* `src/models/order_processor.py` lines 298, 309, 635
* `src/models/position_inventory.py` lines 265, 276
* `src/models/lot_manager.py` lines 126, 137

### `sys.path.append` hacks (3 files)

Legacy pattern from when modules were run as standalone scripts. Unnecessary when running via FastAPI from the project root.

* `src/database/db_manager.py`
* `src/api/tastytrade_client.py`
* `src/sync_trades.py`

### Mixed `logging` vs `loguru` (7 model files)

Routers/services use `loguru`, but model/database files use stdlib `logging`. Not broken, but inconsistent.

## CDN Version Hygiene

* **Alpine.js** uses `@3.x.x` floating version across all 5 HTML pages — could break on CDN cache refresh
* **ApexCharts** has no version pin at all in `risk-dashboard.html`
* **Font Awesome** pinned to 6.4.0 (2023), current is 6.7.x
