import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: true,
    proxy: {
      '/search':    'http://localhost:5000',
      '/parts':     'http://localhost:5000',
      '/vendors':   'http://localhost:5000',
      '/summary':   'http://localhost:5000',
      '/health':    'http://localhost:5000',
      '/inventory':   'http://localhost:5000',
      '/bulk-lookup': 'http://localhost:5000',
      '/recent':      'http://localhost:5000',
    }
  }
})
