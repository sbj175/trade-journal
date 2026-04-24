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

## Files Changed

| File | Change |
|---|---|
| `components/NavBar.vue` | Flat nav, animated SVG burger, page title, user dropdown, mobile active dot |
| `pages/settings/index.vue` | Mobile dropdown nav, URL tab persistence |
| `lib/positionsDesktopCols.js` | Removed ledger-link column |
| `components/PositionsDesktopHeader.vue` | Commented out ledger spacer |
| `components/PositionsDesktopRow.vue` | Commented out ledger link + tag button |
| `components/LedgerDesktopRow.vue` | Commented out pencil edit button |
| Various mobile card components | Left/right alignment and layout refinements |
