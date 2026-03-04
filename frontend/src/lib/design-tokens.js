/**
 * Design Tokens — single source of truth for all visual values.
 *
 * Imported by:
 *   - tailwind.config.js  → generates utility classes (bg-tv-*, text-tv-*, etc.)
 *   - risk/App.vue        → ApexCharts configs (needs raw hex strings)
 *   - main.css            → via Tailwind theme() function
 */

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------

export const colors = {
  // Neutrals
  bg:       '#131722',
  panel:    '#1e222d',
  border:   '#2a2e39',
  hover:    '#363a45',
  text:     '#d1d4dc',
  muted:    '#868c99',

  // Accents
  green:    '#55aa71',   // profit, positive values, long positions
  red:      '#fe676c',   // loss, negative values, short positions
  blue:     '#2962ff',   // brand, interactive, links
  amber:    '#fbbf24',   // warnings, DTE, gamma, expiration, order types
  orange:   '#fb923c',   // assignments, derived positions, severe warnings
  cyan:     '#22d3ee',   // credit filter, informational highlights
  purple:   '#a78bfa',   // vega, exercise, account badges, shares filter
}

// ---------------------------------------------------------------------------
// Typography
// ---------------------------------------------------------------------------

export const fonts = {
  sans: ['-apple-system', 'BlinkMacSystemFont', 'Trebuchet MS', 'Roboto', 'Ubuntu', 'sans-serif'],
  mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
}

// ---------------------------------------------------------------------------
// Chart-specific palette (ApexCharts needs raw hex, can't use CSS vars)
// ---------------------------------------------------------------------------

export const chart = {
  green:      '#55aa71',
  red:        '#fe676c',
  blue:       '#2962ff',
  muted:      '#868c99',
  text:       '#d1d4dc',
  grid:       '#2a2e39',
  tooltipBg:  '#1e222d',
  tooltipHdr: '#131722',
  white:      '#ffffff',
}
