# Design Updates R2 — Branch `feature/design-updates-r2`

## Overview

Mobile-first polish pass and desktop navigation restructure. No backend changes. All modifications are in `frontend/src/`.

---

## Navigation (`NavBar.vue`)

### Mobile header page title
- Active page name now surfaces in the mobile top bar (between logo and controls), derived from route config.
- Updates reactively on navigation.

### Animated hamburger → X
- Replaced Font Awesome icons with an inline SVG (3 lines).
- On open: top line rotates +45°, middle fades/collapses, bottom rotates −45°, forming an X.
- Uses `transform-box: fill-box` so each line pivots around its own center.

### Mobile menu active indicator
- Active nav link shows a filled `tv-blue` dot on the right side.
- Applies to all link variants: child routes (Options, Equities), top-level routes, and Settings.

### Desktop nav flattened
- Removed the Positions dropdown (Options / Equities sub-nav).
- Desktop nav is now a flat list: **Options · Equities · Ledger · Reports · Risk**.
- Dropdown code preserved in an HTML comment for potential re-use.

### Desktop right-side order
- Reordered: **Theme toggle → User dropdown**.
- Removed standalone Settings link and standalone logout button from the top bar.

### User dropdown (auth-enabled)
- Hovering the user email reveals a dropdown containing **Settings** and **Sign out**.
- Icons right-aligned on each item (`justify-between`).
- `user-circle` icon added to the left of the email address.
- Settings item highlights when active route is `/settings`.
- `pt-1.5` bridge on the dropdown wrapper prevents it closing when moving the mouse from trigger to items.
- When auth is disabled, Settings renders as a standalone link (previous behaviour).

---

## Settings Page (`pages/settings/index.vue`)

### Mobile layout
- Replaced the fixed-height sidebar layout (which caused overflow on narrow viewports) with a stacked layout:
  - **Mobile**: dropdown selector at the top showing the active tab.
  - **Desktop (md+)**: sidebar unchanged.
- Dropdown trigger shows the active tab's icon, label, and connection status dot (Connection tab).
- Animated chevron rotates on open.
- Fixed-inset backdrop closes dropdown on outside click.

### Tab state persistence
- Switching tabs now updates `?tab=` in the URL via `router.replace`.
- On page refresh the correct tab is restored from the query parameter.

---

## Positions Page — Desktop (`PositionsDesktopRow.vue`, `PositionsDesktopHeader.vue`, `positionsDesktopCols.js`)

- **View in Ledger** column hidden (book icon link). Column removed from the CSS grid (13 → 12 columns). Header spacer commented out to keep alignment.
- **+ Tag** pill button hidden. Existing tag chips and the tag popover remain functional.

---

## Ledger Page — Desktop (`LedgerDesktopRow.vue`)

- **Edit strategy** pencil icon hidden. Strategy label still renders; inline edit input preserved in comments.

---

---

## InfoPopover (`components/InfoPopover.vue`)

- Teleported popover panel now uses `border-tv-blue/60` border and a blue-tinted drop shadow (`shadow-[0_4px_24px_rgb(var(--tv-blue)/0.18)]`) when open, replacing the flat `border-tv-border` style.
- Increases visual prominence so users notice the popover content.

---

## RollChainModal (`components/RollChainModal.vue`)

### Mobile layout
- Table replaced with card-per-row layout on screens below `md` breakpoint.
- Each card: date range (`Opened → Closed`) on the left, premium + realized P&L values on the right.
- Totals block (Chain Realized / Unrealized / Chain Total) rendered as labeled rows below the cards.
- Modal height increased to `max-h-[90vh]` on mobile (was `80vh` on all sizes).

### Header
- Title and metadata (underlying · strategy label) stack vertically on mobile; inline on desktop.
- Close button gets `shrink-0` to prevent compression on narrow viewports.

### Desktop
- Table layout unchanged. Number column no longer hidden on `md+` (was `hidden md:table-cell`).

---

## Light Mode Accessibility — Contrast (`styles/main.css`)

Five accent colors failed WCAG AA (4.5:1) when rendered on `--tv-bg` or `--tv-row` surfaces. The existing comment said "WCAG AA on #fdfaf6" — that was panel only; bg and row are measurably darker.

| Variable | Old | New | Worst-case ratio |
|---|---|---|---|
| `--tv-muted` | `#7a7068` | `#706860` | 4.60:1 (row) |
| `--tv-green` | `#5d7a5f` | `#507252` | 4.56:1 (row) |
| `--tv-amber` | `#9e7030` | `#8a6028` | 4.66:1 (row) |
| `--tv-orange` | `#a85838` | `#a05434` | 4.65:1 (row) |
| `--tv-cyan` | `#3a7878` | `#387070` | 4.75:1 (row) |

Red, blue, purple already passed on all surfaces — unchanged.

---

## Files Changed

| File | Change |
|---|---|
| `components/NavBar.vue` | Flat nav, animated SVG burger, page title, user dropdown, mobile active dot |
| `pages/settings/index.vue` | Mobile dropdown nav, URL tab persistence |
| `lib/positionsDesktopCols.js` | Removed ledger-link column |
| `components/PositionsDesktopHeader.vue` | Commented out ledger spacer |
| `components/PositionsDesktopRow.vue` | Commented out ledger link + tag button |
| `components/LedgerDesktopRow.vue` | Commented out pencil edit button |
| `components/InfoPopover.vue` | Blue border + glow shadow when popover open |
| `components/RollChainModal.vue` | Mobile card layout, stacked header, taller modal |
| `styles/main.css` | Light mode contrast fixes for 5 accent colors |
| Various mobile card components | Left/right alignment and layout refinements |
