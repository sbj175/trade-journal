#!/usr/bin/env node
// Copies the exact WOFF2 files the landing page needs from @fontsource
// packages into landing/fonts/. Run as a prebuild step so styles.css's
// @font-face src paths resolve against committed files.

const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, '..', 'fonts');
fs.mkdirSync(OUT, { recursive: true });

const NM = path.join(__dirname, '..', 'node_modules', '@fontsource');

const files = [
  // Newsreader (display serif)
  ['newsreader', 'newsreader-latin-400-normal.woff2'],
  ['newsreader', 'newsreader-latin-400-italic.woff2'],
  ['newsreader', 'newsreader-latin-500-normal.woff2'],
  ['newsreader', 'newsreader-latin-500-italic.woff2'],
  ['newsreader', 'newsreader-latin-600-normal.woff2'],
  ['newsreader', 'newsreader-latin-700-normal.woff2'],
  // Outfit (sans)
  ['outfit', 'outfit-latin-300-normal.woff2'],
  ['outfit', 'outfit-latin-400-normal.woff2'],
  ['outfit', 'outfit-latin-500-normal.woff2'],
  ['outfit', 'outfit-latin-600-normal.woff2'],
  ['outfit', 'outfit-latin-700-normal.woff2'],
  // IBM Plex Mono
  ['ibm-plex-mono', 'ibm-plex-mono-latin-400-normal.woff2'],
  ['ibm-plex-mono', 'ibm-plex-mono-latin-500-normal.woff2'],
];

for (const [pkg, name] of files) {
  const src = path.join(NM, pkg, 'files', name);
  const dst = path.join(OUT, name);
  fs.copyFileSync(src, dst);
}

console.log(`Copied ${files.length} font files to fonts/`);
