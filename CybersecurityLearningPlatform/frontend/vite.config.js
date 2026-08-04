import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:5000'
const devHost = process.env.VITE_DEV_HOST || '127.0.0.1'

export default defineConfig({
  plugins: [react()],
  server: {
    host: devHost,
    port: 3000,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true
      }
    }
  }
})
