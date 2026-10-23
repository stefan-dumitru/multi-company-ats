/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on 127.0.0.1 (not "localhost"): on Windows, "localhost" can resolve to IPv6 first
// and hang. Proxying keeps the browser on a single origin, as in production (no CORS to configure).
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': backend,
      '/ready': backend,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
