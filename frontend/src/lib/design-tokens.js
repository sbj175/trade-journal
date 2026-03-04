/**
 * Design Tokens — single source of truth for all visual values.
 *
 * Imported by:
 *   - tailwind.config.js  → generates utility classes (bg-tv-*, text-tv-*, etc.)
 *   - risk/App.vue        → ApexCharts configs (needs raw hex strings)
 *   - main.css            → via Tailwind theme() function
 */

// ---------------------------------------------------------------------------
// Palette — "Deep Finance"
// Deeper backgrounds for bolder contrast; vivid accents that pop.
// ---------------------------------------------------------------------------

export const colors = {
  // Neutrals — deep layered dark with cool undertone
  bg:       '#0b0f19',
  panel:    '#141926',
  border:   '#1e2536',
  hover:    '#283148',
  text:     '#e6e9f0',
  muted:    '#bfc5cd',

  // Accents — bold and unmistakable
  green:    '#00dc82',   // profit, positive values, long positions
  red:      '#ff4757',   // loss, negative values, short positions
  blue:     '#3b82f6',   // brand, interactive, links
  amber:    '#f59e0b',   // warnings, DTE, gamma, expiration, order types
  orange:   '#f97316',   // assignments, derived positions, severe warnings
  cyan:     '#06b6d4',   // credit filter, informational highlights
  purple:   '#9d7aff',   // vega, exercise, account badges, shares filter
}

// ---------------------------------------------------------------------------
// Typography
// ---------------------------------------------------------------------------

export const fonts = {
  sans: ['Plus Jakarta Sans', 'system-ui', 'sans-serif'],
  mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
}

// ---------------------------------------------------------------------------
// Chart-specific palette (ApexCharts needs raw hex, can't use CSS vars)
// ---------------------------------------------------------------------------

export const chart = {
  green:      '#00dc82',
  red:        '#ff4757',
  blue:       '#3b82f6',
  muted:      '#7f8a9a',
  text:       '#e6e9f0',
  grid:       '#1e2536',
  tooltipBg:  '#141926',
  tooltipHdr: '#0b0f19',
  white:      '#ffffff',
}
