import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// COIN frontend; production assets are served from this project's dist directory.
export default defineConfig({
  plugins: [react()],
  root: '.',
  server: {
    port: 18011,
    host: '0.0.0.0',
    watch: process.env.VITE_INOTIFY === '1' ? {} : { usePolling: true, interval: 300 },
    proxy: {
      '/api': 'http://127.0.0.1:18012',
      '/charts': 'http://127.0.0.1:18012',
      '/ws': {
        target: 'ws://127.0.0.1:18012',
        ws: true,
      },
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
