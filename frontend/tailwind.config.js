/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './src/**/*.{vue,js}',
  ],
  theme: {
    extend: {
      colors: {
        tv: {
          bg: '#131722',
          panel: '#1e222d',
          border: '#2a2e39',
          text: '#d1d4dc',
          muted: '#868c99',
          green: '#55aa71',
          red: '#fe676c',
          blue: '#2962ff',
        },
      },
    },
  },
  plugins: [],
}
