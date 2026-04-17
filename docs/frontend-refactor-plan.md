# Frontend Refactor Plan

## Current State

All components use `<script setup>` (100% adoption). Stores are Pinia composition API. Router guards are solid. The main issues are **component size**, **composable sprawl**, and a few consistency gaps.

---

## Issues by Priority

### HIGH — Structural

#### 1. Oversized Page Components

| File | Lines | Problem |
|------|-------|---------|
| `pages/ledger/App.vue` | 995 | Layout + filtering + sorting + notes + tags inline |
| `pages/positions/App.vue` | 941 | Card layout, detail panels, notes, tags, roll analysis all in one |
| `pages/settings/App.vue` | 717 | All tab content in one file |
| `components/GlobalToolbar.vue` | 439 | Title, filters, account selector, sync controls — multi-purpose |
| `components/DateFilter.vue` | 576 | Presets, calendar, dropdown positioning in one component |

**Proposed decompositions:**

`pages/ledger/App.vue` → extract:
- `pages/ledger/LedgerGroupRow.vue` — single group row (expand/collapse, columns)
- `pages/ledger/LedgerDetailPanel.vue` — expanded lot detail, inline editors
- `pages/ledger/LedgerFilters.vue` — filter bar (direction, type, status toggles)

`pages/positions/App.vue` → extract:
- `pages/positions/PositionCard.vue` — single position card (mobile + desktop)
- `pages/positions/PositionDetailPanel.vue` — expanded detail (roll chain, notes, tags)
- `pages/positions/PositionsFilters.vue` — filter/sort controls

`pages/settings/App.vue` → extract one component per tab:
- `pages/settings/SettingsConnection.vue`
- `pages/settings/SettingsAccounts.vue`
- `pages/settings/SettingsTags.vue`
- `pages/settings/SettingsTargets.vue`
- `pages/settings/SettingsPreferences.vue`

`components/GlobalToolbar.vue` → extract:
- `components/SyncControls.vue` — sync button + status indicator

`components/DateFilter.vue` → extract:
- `components/DateFilterCalendar.vue` — calendar picker sub-component

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
- `usePositionsPnl.js` — P&L calculation helpers

`useLedgerGroups.js` → split into:
- `useLedgerGroups.js` — core group data, filtering, sorting
- `useLedgerNotes.js` — notes CRUD (currently in `usePositionsNotes.js` pattern)
- `useLedgerTags.js` — tag management (currently duplicated from positions)

---

#### 3. Duplicated Logic — Extract to Shared Utilities

**GCD calculation** appears identically in two files:
- `pages/positions/App.vue`
- `pages/ledger/App.vue`

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

### MEDIUM — Consistency

#### 4. Hardcoded Strings

Strings that appear in multiple files and should live in `lib/constants.js`:

- Account type labels: `'Roth IRA'`, `'Individual'`, `'Traditional IRA'` (3+ files)
- Filter direction options: `'Bullish'`, `'Bearish'`, `'Neutral'` (ledger + positions)
- Filter type options: `'Credit'`, `'Debit'`
- Position status values: `'OPEN'`, `'CLOSED'`, `'PARTIAL'`
- Fallback tag color: `'#6b7280'` (appears inline in template `style` bindings)

---

#### 5. Event Naming

`components/DateFilter.vue` emits a generic `'update'` event. Should be `'change'` (Vue convention for value-changing inputs) or a named semantic event like `'date-range-change'`. All other modals/components consistently use `'close'` — keep that.

---

### LOW — Polish

#### 6. Inline Styles That Could Be Tailwind

| File | Style | Tailwind equivalent |
|------|-------|---------------------|
| `components/RollChainModal.vue` | `style="width: 24px; height: 24px;"` | `w-6 h-6` |
| `pages/ledger/App.vue` (spinner) | `style="width: 32px; height: 32px; border-width: 3px;"` | `w-8 h-8 border-[3px]` |

Dynamic color bindings (`{ background: tag.color }`) are justified — keep those.

#### 7. Console Calls

~41 `console.error` / `console.log` calls throughout composables. These are fine for now but worth a sweep before any production hardening — either remove or route to a logger.

#### 8. Prop Validation Gaps

`components/StreamingPrice.vue` accepts `quote: { type: Object, default: null }` with no shape validation. Low risk given internal usage, but worth documenting expected shape.

---

## What's Working Well — Don't Touch

- **Composable-per-concern pattern** (positions has 4 composables) — extend this pattern, don't collapse
- **Pinia setup stores** — all well-structured, no anti-patterns
- **Router guard architecture** — meta-based (`requiresAuth`, `requiresTastytrade`), cached config check
- **Responsive layout approach** — `hidden md:block` / `md:hidden` splitting is clean and explicit
- **WebSocket + polling fallback** in `usePositionsData.js` — sophisticated, keep intact
- **localStorage persistence** for UI state (filter preferences, etc.)
- **Teleport for modals** — prevents z-index issues, keep using this
- **FontAwesome consistency** — icon meanings are consistent across the app

---

## Suggested Order of Work

1. Extract `lib/math.js` (gcd) and add constants to `lib/constants.js` — small, safe, unblocks everything else
2. Extract `pnlColorClass` to `lib/formatters.js` — removes template ternary chains
3. Split `pages/settings/App.vue` into per-tab components — lowest risk, no logic changes
4. Split `pages/ledger/App.vue` → `LedgerGroupRow`, `LedgerDetailPanel`, `LedgerFilters`
5. Split `pages/positions/App.vue` → `PositionCard`, `PositionDetailPanel`, `PositionsFilters`
6. Split `usePositionsData.js` into 4 focused composables
7. Split `useLedgerGroups.js` into 3 focused composables
8. Fix `DateFilter.vue` event name
9. Convert unjustified inline styles to Tailwind
