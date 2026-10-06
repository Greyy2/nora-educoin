import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 18011,
    host: '0.0.0.0',
    // Máy chung: quota inotify của user thường bị IDE khác dùng hết (ENOSPC) -> theo dõi file bằng polling (thư mục nhỏ, tốn ít CPU).
    // VITE_INOTIFY=1 để dùng lại inotify khi máy còn quota.
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
  build: { outDir: 'dist', sourcemap: false },
})
