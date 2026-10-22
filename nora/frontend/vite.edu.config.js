import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vite.edu.config.js — build riêng cho EDU product -> frontend/dist-edu
// Dùng: npx vite build --config vite.edu.config.js
// Dev:  npx vite --config vite.edu.config.js
export default defineConfig({
  plugins: [react()],
  // EDU dùng index.edu.html làm entrypoint
  root: '.',
  server: {
    port: 18021,
    host: '0.0.0.0',
    watch: process.env.VITE_INOTIFY === '1' ? {} : { usePolling: true, interval: 300 },
    proxy: {
      '/api': 'http://127.0.0.1:18020',
      // EDU không có /charts hay /ws trực tiếp; nếu cần add sau
    },
  },
  build: {
    outDir: 'dist-edu',
    emptyOutDir: false,
    sourcemap: false,
    rollupOptions: {
      input: { main: './index.edu.html' },
    },
  },
})
