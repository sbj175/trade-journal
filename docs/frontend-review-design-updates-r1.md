# Frontend Review — `feature/design-updates-r1`

**Date:** 2026-04-18  
**Scope:** 74 files, ~1,000 net lines added across 21 commits

---

## Architecture Refactors

**Component decomposition** — every major page (positions, equities, ledger, reports, settings) went from monolithic `index.vue` files to proper component hierarchies. Desktop header, desktop row, mobile card, and filter bar are now separate files for positions, equities, and ledger. Settings split into 7 per-tab components.

**Composable extraction** — logic pulled out of page components into named composables (`usePositionsData`, `useLedgerGroups`, `useReportsData`, etc.). Pages are now mostly wiring — lifecycle, state bundling, teleports.

**CSS Grid columns** — positions, equities, and ledger desktop tables all use shared JS constants (`positionsDesktopCols.js`, `ledgerDesktopCols.js`, `equitiesDesktopCols.js`) for grid column definitions. Header and row share the same class, eliminating the previous static-width drift problem.

**Pre-computed group fields** — `applyFilters()` in `useLedgerGroups` and `groupedPositions` in positions now enrich each row once (initialPremium, returnPercent, strikes, contractCount, optionLegs, etc.) instead of recomputing in templates.

---

## Feature Work

**Dark/light theme toggle** — CSS custom properties replace hardcoded hex values throughout. Dark is the default (`:root`); light is a warm linen beige override (`:root.light`). Flash prevention inline script in `index.html`. Toggle persists to `localStorage` and respects `prefers-color-scheme` on first visit.

**Mobile layouts** — Ledger gets mobile cards with expandable detail. Reports gets compact 3-column summary cards and per-strategy breakdown cards. Nav flattens the Positions submenu and moves Settings into the drawer.

**Reports extraction** — `ReportsSummaryCards`, `ReportsBreakdownTable`, `ReportsFilters` extracted from what was a single 300-line page component.

---

## Open Items

### Accessibility

**Light theme WCAG gaps** — amber, cyan, orange, and green accent colors fail the 4.5:1 contrast ratio on the `row` surface (`#f0e9e0`). Current palette is visually intentional but not fully AA-compliant on every surface. Validated darker variants exist (see prior session) — worth revisiting before public launch.

### Functional

**Chart colors not theme-aware** — `design-tokens.js` `chart` export is hardcoded dark-theme hex values. ApexCharts on the Risk page will not adapt to light mode. Noted in a comment in the file. Requires either a reactive chart palette computed from the active theme or two separate palettes toggled on theme change.

### Architecture

**`LedgerDesktopRow` size** — the extracted row component is large (~400 lines). Tag popover, notes textarea, equity aggregate, option legs, and strategy edit mode all live in one file. Could be split further but not urgent given the clear internal structure.

**Filter state pattern** — ledger and reports pass raw refs inside plain objects (`filterState = { filterDirection, ... }`). Works, but requires `.value` access in child templates — a non-standard Vue pattern. Worth documenting for new contributors or migrating to `toRefs`/`defineModel` in a future pass.
