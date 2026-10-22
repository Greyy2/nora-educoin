import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vite.config.js — build riêng cho EDU standalone product
export default defineConfig({
  plugins: [react()],
  root: '.',
  server: {
    port: 18021,
    host: '0.0.0.0',
    watch: process.env.VITE_INOTIFY === '1' ? {} : { usePolling: true, interval: 300 },
    proxy: {
      '/api': 'http://127.0.0.1:18022',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: { main: './index.html' },
    },
  },
})
