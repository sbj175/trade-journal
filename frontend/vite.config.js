import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  root: __dirname,
  build: {
    outDir: resolve(__dirname, '../static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        settings: resolve(__dirname, 'src/pages/settings/main.js'),
        reports: resolve(__dirname, 'src/pages/reports/main.js'),
        risk: resolve(__dirname, 'src/pages/risk/main.js'),
        ledger: resolve(__dirname, 'src/pages/ledger/main.js'),
        positions: resolve(__dirname, 'src/pages/positions/main.js'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: '[name].[ext]',
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
})
