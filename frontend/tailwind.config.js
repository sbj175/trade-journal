import { colors, fonts } from './src/lib/design-tokens.js'

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './src/**/*.{vue,js}',
  ],
  theme: {
    extend: {
      colors: {
        tv: colors,
      },
      fontFamily: {
        sans: fonts.sans,
        mono: fonts.mono,
      },
    },
  },
  plugins: [],
}
