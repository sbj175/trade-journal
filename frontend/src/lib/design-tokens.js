/**
 * Design Tokens — single source of truth for all visual values.
 *
 * Imported by:
 *   - tailwind.config.js  → generates utility classes (bg-tv-*, text-tv-*, etc.)
 *   - risk/App.vue        → ApexCharts configs (needs raw hex strings)
 *   - main.css            → via Tailwind theme() function
 *
 * Colors use CSS custom properties so dark/light themes work via class on <html>.
 * The <alpha-value> placeholder enables Tailwind opacity modifiers (bg-tv-blue/50 etc).
 * CSS vars are defined in styles/main.css as space-separated RGB channels.
 */

// ---------------------------------------------------------------------------
// Palette — CSS variable references (dark/light switched via :root.light)
// ---------------------------------------------------------------------------

export const colors = {
  bg:     'rgb(var(--tv-bg) / <alpha-value>)',
  panel:  'rgb(var(--tv-panel) / <alpha-value>)',
  row:    'rgb(var(--tv-row) / <alpha-value>)',
  border: 'rgb(var(--tv-border) / <alpha-value>)',
  hover:  'rgb(var(--tv-hover) / <alpha-value>)',
  text:   'rgb(var(--tv-text) / <alpha-value>)',
  muted:  'rgb(var(--tv-muted) / <alpha-value>)',
  green:  'rgb(var(--tv-green) / <alpha-value>)',
  red:    'rgb(var(--tv-red) / <alpha-value>)',
  blue:   'rgb(var(--tv-blue) / <alpha-value>)',
  amber:  'rgb(var(--tv-amber) / <alpha-value>)',
  orange: 'rgb(var(--tv-orange) / <alpha-value>)',
  cyan:   'rgb(var(--tv-cyan) / <alpha-value>)',
  purple: 'rgb(var(--tv-purple) / <alpha-value>)',
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
// Dark theme values — charts are always dark-on-dark panel.
// ---------------------------------------------------------------------------

export const chart = {
  green:      '#00dc82',
  red:        '#ff4757',
  blue:       '#3b82f6',
  muted:      '#bfc5cd',
  text:       '#e6e9f0',
  grid:       '#1e2536',
  tooltipBg:  '#141926',
  tooltipHdr: '#0b0f19',
  white:      '#ffffff',
}
