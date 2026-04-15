/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html'],
  theme: {
    extend: {
      fontFamily: {
        display: ['Newsreader', 'Georgia', 'serif'],
        sans: ['Outfit', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      colors: {
        cream: '#FDFAF5',
        parchment: '#F5F0E8',
        ink: '#1a1a2e',
        terracotta: {
          400: '#d4715a',
          500: '#c45d3e',
          600: '#b04e32',
          700: '#943f28',
        },
        muted: '#6b7280',
      },
    },
  },
  plugins: [],
};
