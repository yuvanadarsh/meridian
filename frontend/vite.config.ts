import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Single-page app: unknown client routes (e.g. /settings, /chat/:id) fall back
  // to index.html so React Router can resolve them on dev server and preview.
  appType: 'spa',
  server: {
    host: true,
    port: 5173,
  },
})
