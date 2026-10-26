import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// dev: `npm run dev` (port 5173) proxies /api to the Python server on 8770; prod: server.py serves dist/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8770' } },
  build: {
    chunkSizeWarningLimit: 1800,
    rollupOptions: { output: { manualChunks: { antd: ['antd', '@ant-design/icons'] } } },
  },
})
