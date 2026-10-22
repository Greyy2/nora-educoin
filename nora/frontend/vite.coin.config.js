import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vite.coin.config.js — build riêng cho COIN product -> frontend/dist-coin
// Dùng: npx vite build --config vite.coin.config.js
// Dev:  npx vite --config vite.coin.config.js
export default defineConfig({
  plugins: [react()],
  root: '.',
  server: {
    port: 18011,
    host: '0.0.0.0',
    watch: process.env.VITE_INOTIFY === '1' ? {} : { usePolling: true, interval: 300 },
    proxy: {
      '/api': 'http://127.0.0.1:18010',
      '/charts': 'http://127.0.0.1:18010',
      '/ws': {
        target: 'ws://127.0.0.1:18010',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist-coin',
    emptyOutDir: false,
    sourcemap: false,
    rollupOptions: {
      input: { main: './index.coin.html' },
    },
  },
})
