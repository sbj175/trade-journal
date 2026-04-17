# Frontend Refactor Plan

## Naming Convention

All page-level `App.vue` files should be renamed to `index.vue`. The `App.vue` name is conventionally reserved for the root component (`src/App.vue`) and causes ambiguity in IDE tabs and search. Using `index.vue` is idiomatic for the primary file in a directory — consistent with how `pages/` folder structure already implies context.

| Current | Rename to |
|---------|-----------|
| `pages/ledger/App.vue` | `pages/ledger/index.vue` |
| `pages/positions/App.vue` | `pages/positions/index.vue` |
| `pages/positions-equities/App.vue` | `pages/positions-equities/index.vue` |
| `pages/settings/App.vue` | `pages/settings/index.vue` |
| `pages/reports/App.vue` | `pages/reports/index.vue` |
| `pages/risk/App.vue` | `pages/risk/index.vue` |
| `pages/privacy/App.vue` | `pages/privacy/index.vue` |
| `pages/components/App.vue` | `pages/components/index.vue` |

Router imports in `router/index.js` must be updated alongside each rename.

---

## Current State

All components use `<script setup>` (100% adoption). Stores are Pinia composition API. Router guards are solid. The main issues are **component size**, **composable sprawl**, **performance during live trading**, and a few consistency gaps.

---

## Issues by Priority

### HIGH — Structural

#### 1. Oversized Page Components

| File | Lines | Problem |
|------|-------|---------|
| `pages/ledger/index.vue` | 995 | Layout + filtering + sorting + notes + tags inline |
| `pages/positions/index.vue` | 941 | Card layout, detail panels, notes, tags, roll analysis all in one |
| `pages/settings/index.vue` | 717 | All tab content in one file |
| `components/DateFilter.vue` | 576 | Presets, calendar, dropdown positioning in one component |

**Proposed decompositions:**

`pages/ledger/index.vue` → extract:
- `pages/ledger/LedgerGroupRow.vue` — single group row (expand/collapse, columns)
- `pages/ledger/LedgerDetailPanel.vue` — expanded lot detail, inline editors
- `pages/ledger/LedgerFilters.vue` — filter bar (direction, type, status toggles)

`pages/positions/index.vue` → extract:
- `pages/positions/PositionCard.vue` — single position card (mobile + desktop)
- `pages/positions/PositionDetailPanel.vue` — expanded detail (roll chain, notes, tags)
- `pages/positions/PositionsFilters.vue` — filter/sort controls

`pages/settings/index.vue` → extract one component per tab (each already has its own composable, so this is purely additive):
- `pages/settings/SettingsConnection.vue`
- `pages/settings/SettingsAccounts.vue`
- `pages/settings/SettingsTags.vue`
- `pages/settings/SettingsTargets.vue`
- `pages/settings/SettingsPreferences.vue`

**`pages/positions/Detail.vue` (432 lines)** — exceeds the size threshold but was not audited as part of the initial review. Evaluate before touching positions composables; it may need its own decomposition or share components extracted from `positions/index.vue`.

`components/DateFilter.vue` → extract:
- `components/DateFilterCalendar.vue` — calendar picker sub-component

**Note on `components/GlobalToolbar.vue` (439 lines):** Initially flagged as oversized, but on closer review the pattern is intentional — page filter content is teleported *into* the toolbar from each page, which is clean separation of concerns. The only extraction worth making is `components/SyncControls.vue` for the sync button and status indicator.

---

#### 2. Oversized Composables

| File | Lines | Problems |
|------|-------|---------|
| `pages/positions/usePositionsData.js` | 674 | Data fetch + WebSocket + quoting + filtering + sorting + P&L calcs |
| `pages/ledger/useLedgerGroups.js` | 466 | Filtering + sorting + notes CRUD + tags CRUD |

**Proposed splits:**

`usePositionsData.js` → split into:
- `usePositionsData.js` — fetch, state structure only
- `usePositionsQuotes.js` — WebSocket management, quote caching (extract from lines ~170-450)
- `usePositionsFilters.js` — filter/sort state and logic
  - **Caution**: verify dependency direction before splitting — filter logic likely references the positions array. If so, pass data in as a parameter rather than importing from the data composable, to avoid circular imports.
- P&L calculation helpers — if stateless pure functions, extract to `lib/formatters.js` or `lib/math.js` rather than a composable

`useLedgerGroups.js` → split into:
- `useLedgerGroups.js` — core group data, filtering, sorting
- `useLedgerTags.js` — tag management

**Notes/tags unification opportunity**: `usePositionsNotes.js` already exists for positions. Before creating a separate `useLedgerNotes.js`, compare the two — they are likely the same CRUD pattern against the same API endpoints. If so, extract a shared `composables/useNotes(entityType, entityId)` that both pages consume, eliminating the duplication entirely.

---

#### 3. Circular Dependency in Equity Positions

`pages/positions-equities/index.vue` resolves a circular dependency between `useEquityQuotes` and `useEquityPositions` using a lazy getter:
```js
{ get value() { return filteredItems.value } }
```
This works but is a code smell — the two composables are too tightly coupled. Resolve by restructuring so one composable explicitly receives the other's output as a parameter rather than creating a circular reference.

---

#### 4. Duplicated Logic — Extract to Shared Utilities

**GCD calculation** appears identically in two files:
- `pages/positions/index.vue`
- `pages/ledger/index.vue`

Extract to `lib/math.js`:
```js
export function gcd(a, b) {
  a = Math.abs(a); b = Math.abs(b)
  while (b) { [a, b] = [b, a % b] }
  return a
}
```

**Account type sort order** is duplicated in:
- `pages/ledger/useLedgerGroups.js` (lines 47–57)
- `pages/positions/usePositionsData.js` (lines 62–70)

Move to `lib/constants.js`.

**P&L color class logic** is inlined in multiple templates:
```js
// Repeated in ledger, positions, reports templates
group.realized_pnl > 0 ? 'text-tv-green' : group.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'
```
Extract to `lib/formatters.js`:
```js
export function pnlColorClass(value) {
  if (value > 0) return 'text-tv-green'
  if (value < 0) return 'text-tv-red'
  return 'text-tv-muted'
}
```

---

### HIGH — Performance

#### 5. `groupedPositions` Computed Runs Roll Analysis on Every Quote Update

**File:** `pages/positions/usePositionsData.js` ~line 536

The `groupedPositions` computed depends on `quoteUpdateCounter`, which increments every 1–2 seconds during market hours. On every tick it:
- Re-sorts all items
- Calls `getRollAnalysis()` for every group (a multi-iteration calculation)
- Recalculates subtotals

Result: 60+ full sorts and 100+ roll analyses per minute during live trading hours. Roll analysis results don't change on quote updates — they only change when positions change structurally.

**Fix:** Split into two computeds — one for structural data (filtered/sorted positions, roll analysis) that only reacts to position changes, and one for live quote values. Memoize `getRollAnalysis()` results per group ID.

---

#### 6. Method Calls in Templates + `groupedPositions` Restructure

**Files:** `pages/positions/index.vue` lines 335–920, `pages/positions/usePositionsData.js` ~line 536

These two issues are the same piece of work and should be done together. `groupedPositions` needs to be split (issue #5) so that structural data — including per-group derived values — is computed once and cached. Once that split exists, template functions like `getGroupOpenPnL(group)`, `getGroupStrikes(group)`, `getPositionCount(group)`, `getGroupCostBasis(group)` can be moved into the structural computed so each group object carries its own display data. Templates then read a property instead of calling a function, eliminating 300+ invocations per render cycle.

**Fix:** Do issues #5 and #6 in a single pass on `usePositionsData.js`.

---

#### 7. Black-Scholes Recalculated on Every Quote (Risk Page)

**File:** `pages/risk/useRiskData.js` ~line 37

`enrichedPositions` is a computed that maps every position through `enrichPosition()`, which runs Black-Scholes for greeks. This fires on every quote update with no memoization — 50 positions × 1 quote/sec = 50 BS calculations/sec during market hours.

**Fix:** Memoize `enrichPosition()` results keyed by `(positionId, quoteTimestamp)`. Only recalculate a position if its underlying's quote actually changed.

---

#### 8. Duplicate Data Fetches — No Stale Cache Check

**Files:** `pages/positions/index.vue` lines 151–174, all page `index.vue` files

Pages fetch data in both `onMounted` and `onActivated` with no staleness check. Navigating Positions → Ledger → Positions triggers a full re-fetch of `/api/open-chains` (potentially 500KB+) every visit. Additionally, the `lastSyncTime` watcher fires simultaneously on every page that has it mounted, causing 3 parallel full fetches after a sync.

**Fix:** Add a short TTL (5–10 sec) to position/ledger/quote fetches. On `onActivated`, skip the fetch if data is fresh. For the sync watcher, only re-fetch on the active page — or centralize post-sync refresh in a Pinia action.

---

#### 9. Event Listeners Not Cleaned Up on `onDeactivated`

**File:** `pages/positions/index.vue` lines 152–153, 176–178

`document.addEventListener` calls happen in `onMounted`. `onDeactivated` calls `cleanupWebSocket()` but does **not** remove the click listeners. When the user navigates back, `onMounted` fires again and adds a second copy of each listener. Navigating back and forth 5 times = 5 document click listeners active simultaneously.

**Fix:** Mirror every `addEventListener` in `onMounted` with a `removeEventListener` in `onDeactivated`.

---

### MEDIUM — Performance

#### 10. No Virtual Scrolling on Large Lists

**Files:** `pages/positions/index.vue`, `pages/ledger/index.vue`

Both pages render all rows into the DOM simultaneously with `v-for`. A trader with 50 open chains × 3 legs each = 150+ table rows fully rendered, plus collapsed detail panels held in the DOM via `v-show`. On mobile this causes noticeable jank.

**Fix:** For lists likely to exceed 30–40 items, implement virtual scrolling (`vue-virtual-scroller` or similar). Use `v-if` instead of `v-show` for expanded detail panels — the content is complex enough (roll analysis, leg tables, notes) that keeping it in the DOM when hidden is wasteful.

---

#### 11. No Debounce on Symbol Filter Input

**File:** `pages/positions/index.vue` ~line 196

The symbol filter calls `onSymbolFilterCommit()` on every keystroke, which triggers `applyFilters()` + `loadCachedQuotes()` (API call) + `requestLiveQuotes()` (WebSocket re-subscribe). Typing "SPY" fires 3 API calls.

**Fix:** Debounce `onSymbolFilterCommit` by 300ms. Use a small inline debounce utility rather than adding lodash as a dependency — a single use case doesn't justify the import weight:
```js
function debounce(fn, ms) {
  let t
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
}
```

---

#### 12. Strategy Targets Fetched on Every Detail Page Mount

**File:** `pages/positions/index.vue` ~line 161, `pages/positions/Detail.vue` ~line 79

`loadStrategyTargets()` is called in both the positions page and the detail page on every mount. Viewing 3 position details in one session fetches targets 4 times (1 in index, 3 in detail). Strategy targets are slow-changing config data.

**Fix:** Load once in a Pinia store on first access and cache there. Both pages read from the store instead of fetching independently.

---

#### 13. `v-show` on Large Detail Panels Should Be `v-if`

**Files:** `pages/positions/index.vue` lines 418, 667; `pages/ledger/index.vue`

Expanded detail panels (roll analysis, option legs, notes, tags) are hidden with `v-show`, meaning their full DOM — 50+ nodes per panel — is always rendered. With 50 positions at 10% expanded rate, that's still 45 invisible panels in the DOM. This is independent of virtual scrolling and is a one-line change per panel.

**Fix:** Switch detail panel wrappers from `v-show` to `v-if`. The expand/collapse transition may need a short CSS fade, but the DOM reduction is worth it.

---

#### 14. ApexCharts Redraws All 4 Charts Every 2 Seconds

**File:** `pages/risk/useRiskCharts.js` lines 35–50

The debounced chart update re-renders all 4 charts (Delta, Theta, Treemap, Scenario) together on a 2-second timer. Each update triggers ApexCharts internal animations. Charts that haven't changed (e.g., Treemap when only delta moved) still redraw.

**Fix:** Track a change hash per chart. Only call `updateOptions` on charts whose underlying data has changed since the last render.

---

### MEDIUM — Consistency

#### 13. Hardcoded Strings

Strings that appear in multiple files and should live in `lib/constants.js`:

- Account type labels: `'Roth IRA'`, `'Individual'`, `'Traditional IRA'` (3+ files)
- Filter direction options: `'Bullish'`, `'Bearish'`, `'Neutral'` (ledger + positions)
- Filter type options: `'Credit'`, `'Debit'`
- Position status values: `'OPEN'`, `'CLOSED'`, `'PARTIAL'`
- Fallback tag color: `'#6b7280'` (appears inline in template `style` bindings)

---

#### 15. Event Naming

`components/DateFilter.vue` emits a generic `'update'` event. Should be `'change'` (Vue convention for value-changing inputs) or a named semantic event like `'date-range-change'`. **This is a breaking change** — find and update all consumers before renaming. All other modals/components consistently use `'close'` — keep that.

---

### LOW — Polish

#### 16. Inline Styles That Could Be Tailwind

| File | Style | Tailwind equivalent |
|------|-------|---------------------|
| `components/RollChainModal.vue` | `style="width: 24px; height: 24px;"` | `w-6 h-6` |
| `pages/ledger/index.vue` (spinner) | `style="width: 32px; height: 32px; border-width: 3px;"` | `w-8 h-8 border-[3px]` |

Dynamic color bindings (`{ background: tag.color }`) are justified — keep those.

#### 17. Document Firefox Eager-Import Workaround

**File:** `router/index.js` lines 5–8

The Risk page is eagerly imported (not lazy-loaded like other routes) as a workaround for a Firefox chunk corruption bug. This is not documented in the file. A future cleanup pass could accidentally convert it to a dynamic import and re-introduce the Firefox issue.

**Fix:** Add a one-line comment explaining the Firefox workaround so it doesn't get "fixed" by accident.

#### 18. Console Calls

~41 `console.error` / `console.log` calls throughout composables. Remove them — don't redirect to a logger service, that's over-engineering for this app.

---

## What's Working Well — Don't Touch

- **Composable-per-concern pattern** (positions has 4 composables) — extend this pattern, don't collapse
- **Pinia setup stores** — all well-structured, no anti-patterns
- **Router guard architecture** — meta-based (`requiresAuth`, `requiresTastytrade`), cached config check
- **Responsive layout approach** — `hidden md:block` / `md:hidden` splitting is clean and explicit
- **WebSocket + polling fallback** in `usePositionsData.js` — sophisticated, keep intact
- **localStorage persistence** for UI state (filter preferences, etc.)
- **Teleport for modals** — prevents z-index issues, keep using this
- **Teleport for page filters into GlobalToolbar** — clean separation of concerns, keep this pattern
- **FontAwesome consistency** — icon meanings are consistent across the app

---

## Suggested Order of Work

1. Rename all page `App.vue` → `index.vue` and update `router/index.js` imports — mechanical, zero logic risk
2. Document Firefox eager-import workaround in `router/index.js` — one comment, prevents future regression
3. Extract `lib/math.js` (gcd) and add constants to `lib/constants.js` — small, safe, unblocks everything else
4. Extract `pnlColorClass` to `lib/formatters.js` — removes template ternary chains
5. Split `pages/settings/index.vue` into per-tab components — purely additive, no logic changes, independent of everything else
6. **Fix `onDeactivated` listener cleanup** — add `removeEventListener` calls; quick and high-impact
7. **Add debounce to symbol filter input** — stops 3 API calls per keystroke; use inline debounce utility, not lodash
8. **Move strategy targets into Pinia store** — eliminates duplicate fetches from index + Detail pages
9. **Split `groupedPositions` computed + move per-group display values** — do both in one pass on `usePositionsData.js`; separates structural from quote-reactive, eliminates 300+ template function calls per render
10. **Switch detail panel `v-show` → `v-if`** — independent one-liner per panel, large DOM reduction
11. **Add stale cache check to `onActivated` fetches** — prevents redundant 500KB re-fetches on navigation
12. **Memoize `enrichPosition()` in Risk page** — only recalculate if the position's underlying quote changed
13. Audit `pages/positions/Detail.vue` — evaluate against decomposition patterns being established; may share components with positions index
14. Audit `usePositionsNotes.js` vs ledger notes pattern — decide on shared `useNotes` before touching either page
15. Split `usePositionsData.js` — extract `usePositionsQuotes.js` first (clearest boundary), then `usePositionsFilters.js` once dependency direction is confirmed
16. Split `useLedgerGroups.js` — extract `useLedgerTags.js`, then wire in shared `useNotes` if applicable
17. Resolve `useEquityQuotes` / `useEquityPositions` circular dependency
18. Split `pages/ledger/index.vue` → `LedgerGroupRow`, `LedgerDetailPanel`, `LedgerFilters`
19. Split `pages/positions/index.vue` → `PositionCard`, `PositionDetailPanel`, `PositionsFilters`
20. Add virtual scrolling for lists likely to exceed 30–40 items
21. Per-chart change detection in `useRiskCharts.js` to avoid full redraws
22. Fix `DateFilter.vue` event name (update all consumers)
23. Remove console calls
24. Convert unjustified inline styles to Tailwind
