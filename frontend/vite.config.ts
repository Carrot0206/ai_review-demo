import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'


export default defineConfig({
  base: '/rule-library/',
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_DEV_PORT || 5174),
    strictPort: true,
    proxy: {
      '/api/rule-engine': {
        target: process.env.VITE_ENGINE_API_TARGET || process.env.VITE_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
        ws: false,
      },
      '/api/rule-library': {
        target: process.env.VITE_ENGINE_API_TARGET || process.env.VITE_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
        ws: false,
      },
      '/api': {
        target: process.env.VITE_ENGINE_API_TARGET || process.env.VITE_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
        ws: false,
      },
    },
  },
})
